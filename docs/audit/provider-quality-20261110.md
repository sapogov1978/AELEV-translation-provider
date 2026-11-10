# OpenAI provider quality evidence — 2026-11-10

## Scope and result

`PROVIDER_QUALITY_PASS` for
`ghcr.io/sapogov1978/aelev-translation-provider@sha256:0a09783d072ccc7c60ec8e6fbe5ce56def95a56601888d5c3e4cf083da3ee016`,
built from `f0c538767809bf7e7ddd52a9b4760d442ea6cad2`.

The exact running provider image matched the immutable Docker reference.
A separate read-only client container used the opaque UDS, without a network
or credential mount. It submitted the existing 20-case repository corpus once,
without retries. All requests returned HTTP 200 and passed opaque contract,
required-warning and corpus literal checks. The model and prompt remained
those in `provider.lock.json`; no runtime override was supplied.

Codex reviewed all 20 source/translation pairs against the corpus meanings.
Negation, uncertainty, conditions, names, numbers, units, identifiers,
placeholders, list order and line breaks were preserved in the sampled cases.
The ambiguous lock/castle and factory/power-plant cases preserved their context.
The central-bank cases added no country. This is an explicit reviewer check of
this bounded corpus, not an independent linguistic benchmark or a claim about
every supported language.

Hash-only machine evidence is in
[provider-quality-20261110.json](provider-quality-20261110.json).
The local raw exchanges are retained outside Git at
`/var/tmp/aelev-production-admission.wDuzQd/translation-quality.json`.
No provider key, Authorization header, upstream response or runtime database
is included in the repository evidence.

## Supply chain

The source audit workflow `42615608601` and image publication `42615707050`
completed successfully. Cosign 3.1.4 verified the exact image signature,
certificate chain and transparency-log claims with issuer
`https://token.actions.githubusercontent.com` and exact signing identity
`https://github.com/sapogov1978/AELEV-translation-provider/.github/workflows/release.yml@refs/heads/main`.

BuildKit exposes SLSA provenance and SPDX SBOM for both `linux/amd64` and
`linux/arm64`. Live execution in this evaluation used native `linux/arm64`.
The provider source checks passed: 26 tests, Ruff and Pyright.

## Remaining admission boundary

This evidence closes provider access/quota at the time of the test and bounded
provider quality for this exact image. It does not promise future quota,
broader semantic quality or a different image. The joint Platform Infrastructure
clean-room, exact Translator worker pairing, recovery and deployment gates
remain open and are evaluated in the infrastructure stage. No queue command or
`RESUME` was issued by this evaluation.
