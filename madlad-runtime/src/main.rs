use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::Path;

use anyhow::{bail, Context, Result};
use candle_core::{Device, Tensor};
use candle_transformers::generation::LogitsProcessor;
use candle_transformers::models::quantized_t5 as t5;
use serde::{Deserialize, Serialize};
use tokenizers::Tokenizer;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TranslationRequest {
    texts: Vec<String>,
    max_output_tokens: Option<usize>,
}

#[derive(Serialize)]
#[serde(untagged)]
enum TranslationResponse {
    Success { translations: Vec<String> },
    Failure { error: &'static str },
}

struct Runtime {
    device: Device,
    config: t5::Config,
    tokenizer: Tokenizer,
    model: t5::T5ForConditionalGeneration,
}

impl Runtime {
    fn load(model_root: &Path) -> Result<Self> {
        let device = Device::Cpu;
        let config = std::fs::read_to_string(model_root.join("config.json"))
            .context("cannot read MADLAD config")?;
        let mut config: t5::Config =
            serde_json::from_str(&config).context("cannot parse MADLAD config")?;
        config.use_cache = true;
        let tokenizer = Tokenizer::from_file(model_root.join("tokenizer.json"))
            .map_err(anyhow::Error::msg)
            .context("cannot load MADLAD tokenizer")?;
        let weights = model_root.join("model-q4k.gguf");
        let builder = t5::VarBuilder::from_gguf(&weights, &device)
            .context("cannot load MADLAD Q4K weights")?;
        let model = t5::T5ForConditionalGeneration::load(builder, &config)
            .context("cannot construct MADLAD model")?;
        Ok(Self {
            device,
            config,
            tokenizer,
            model,
        })
    }

    fn translate(&mut self, text: &str, max_output_tokens: usize) -> Result<String> {
        if text.is_empty() || text.len() > 4096 {
            bail!("translation input length is invalid")
        }
        self.model.clear_kv_cache();
        let tokens = self
            .tokenizer
            .encode(text, true)
            .map_err(anyhow::Error::msg)?
            .get_ids()
            .to_vec();
        let input_token_ids = Tensor::new(tokens.as_slice(), &self.device)?.unsqueeze(0)?;
        let encoder_output = self.model.encode(&input_token_ids)?;
        let mut output_token_ids = vec![self
            .config
            .decoder_start_token_id
            .unwrap_or(self.config.pad_token_id) as u32];
        let mut logits_processor = LogitsProcessor::new(299_792_458, None, None);
        for index in 0..max_output_tokens {
            let decoder_token_ids = if index == 0 {
                Tensor::new(output_token_ids.as_slice(), &self.device)?.unsqueeze(0)?
            } else {
                let last_token = *output_token_ids.last().context("missing output token")?;
                Tensor::new(&[last_token], &self.device)?.unsqueeze(0)?
            };
            let logits = self
                .model
                .decode(&decoder_token_ids, &encoder_output)?
                .squeeze(0)?;
            let next_token_id = logits_processor.sample(&logits)?;
            if next_token_id as usize == self.config.eos_token_id {
                break;
            }
            output_token_ids.push(next_token_id);
        }
        let translated = self
            .tokenizer
            .decode(&output_token_ids[1..], true)
            .map_err(anyhow::Error::msg)?;
        if translated.trim().is_empty() {
            bail!("translation output is empty")
        }
        Ok(translated.trim().to_string())
    }
}

fn main() -> Result<()> {
    let model_root = std::env::args().nth(1).context("model root is required")?;
    let mut runtime = Runtime::load(Path::new(&model_root))?;
    let stdin = std::io::stdin();
    let mut stdout = BufWriter::new(std::io::stdout().lock());
    stdout.write_all(b"{\"status\":\"ready\"}\n")?;
    stdout.flush()?;
    for line in BufReader::new(stdin.lock()).lines() {
        let line = line.context("cannot read request")?;
        let request: TranslationRequest = match serde_json::from_str(&line) {
            Ok(request) => request,
            Err(_) => {
                write_response(
                    &mut stdout,
                    &TranslationResponse::Failure {
                        error: "TRANSLATOR_RUNTIME_REQUEST_INVALID",
                    },
                )?;
                continue;
            }
        };
        let max_output_tokens = request.max_output_tokens.unwrap_or(192);
        if request.texts.is_empty()
            || request.texts.len() > 32
            || !(16..=192).contains(&max_output_tokens)
        {
            write_response(
                &mut stdout,
                &TranslationResponse::Failure {
                    error: "TRANSLATOR_RUNTIME_REQUEST_INVALID",
                },
            )?;
            continue;
        }
        let translations = request
            .texts
            .iter()
            .map(|text| runtime.translate(text, max_output_tokens))
            .collect::<Result<Vec<_>>>();
        let response = match translations {
            Ok(translations) => TranslationResponse::Success { translations },
            Err(error) if error.to_string() == "translation output is empty" => {
                TranslationResponse::Failure {
                    error: "TRANSLATOR_EMPTY_OUTPUT",
                }
            }
            Err(_) => TranslationResponse::Failure {
                error: "TRANSLATOR_RUNTIME_REQUEST_FAILED",
            },
        };
        write_response(&mut stdout, &response)?;
    }
    Ok(())
}

fn write_response(
    stdout: &mut BufWriter<std::io::StdoutLock<'_>>,
    response: &TranslationResponse,
) -> Result<()> {
    serde_json::to_writer(&mut *stdout, response)?;
    stdout.write_all(b"\n")?;
    stdout.flush()?;
    Ok(())
}
