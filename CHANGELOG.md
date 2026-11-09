# Changelog

## Unreleased

- Removed the standalone model, weight downloader and native `llama.cpp` runtime
  from the active build and image.
- Added a lock-pinned OpenAI Responses API client using `gpt-6.1-sol` over
  direct HTTPS with system CA verification.
- Added a digest-pinned domain-preserving prompt, full-segment language context,
  `store=false`, strict structured output and bounded opaque failures.
- Added an ignored `.env.local` API-key placeholder; no credential is committed,
  printed, sent in the Docker build context or required by offline validation
  and image build.
- Kept opaque UDS v1 unchanged; the prepared Platform compute recipe leaves the
  local API key as the only missing runtime input before a bounded live check.
- Switched the provider release to an ephemeral GitHub-hosted Ubuntu 24.04 x86_64
  runner, reclaiming unused preinstalled SDK space and disabling the oversized
  release cache; self-hosted infrastructure is now only an evidence-driven
  fallback.
- Published the first verified Linux amd64 provider image with SBOM, provenance,
  keyless signature and an immutable digest artifact.
- Added a bounded GitHub-hosted quality gate that exercises the exact release
  digest over the approved 20-case synthetic corpus through the opaque UDS and
  emits output hashes without user data.
- Quality drift diagnostics may print the expected and actual text only for the
  repository-owned synthetic corpus; arbitrary or user-provided text remains
  excluded from workflow evidence and logs.
- The quality gate completes the entire bounded corpus before reporting all
  synthetic baseline drifts, avoiding one rerun per diagnostic difference.
- Reviewed two release-specific, semantically equivalent synthetic outputs in a
  digest-bound allowlist; the historical baseline, literal checks and all other
  exact comparisons remain unchanged.
- The exact signed provider release passed all 20 approved synthetic quality
  cases on a fresh GitHub-hosted runner and emitted hash-only PASS evidence.

## 2026-11-06

- Provider выделен из исторического дерева `translator-service` в отдельный
  продукт с сохранением Git-истории provider-specific реализации.
- Kafka, PostgreSQL, operator API, очередь, publisher и consumer-specific код
  удалены из provider; граница сведена к opaque HTTP v1 поверх Unix socket.
- Веса Index Translate 9B, `llama.cpp`, prompt, cache, lock, downloader и
  healthcheck закреплены за provider image и не раскрываются Translator.
- Добавлены нормативная спецификация, операторский manual, ADR, contract
  schema, provenance и официальные ссылки производителей.
- Добавлены CI и подписываемый GHCR release с SBOM/provenance; production
  admission по mutable tag запрещён.
- Runtime image содержит официальные Apache-2.0 и llama.cpp MIT license texts;
  неподтверждённая CPU-архитектура явно не считается поддерживаемой.
