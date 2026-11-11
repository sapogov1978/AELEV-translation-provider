# Changelog

- 2026-11-11: точный подписанный v0.1.1 проверен на обеих native-архитектурах по закреплённому ограниченному security-профилю; 20 новых live-переводов отдельно проверены по смыслу. Пройдена изолированная UDS-проверка с exact Translator worker; сырой CVE scan сохранён, полный инфраструктурный clean-room и допуск площадки остаются отдельными gates.
- 2026-11-11: допуск CVE ограничен закреплёнными исходниками, зависимостями и защищённым режимом opaque provider. Сырой scan сохраняется; новая HIGH/CRITICAL или изменение рассмотренного кода закрывает допуск. Подпись выпуска требует успешного audit точного main commit и проверки опубликованного amd64 digest; доказательства сохраняются в артефакте workflow.
- 2026-11-10: добавлена автономная проверка точного image ID в обоих Python-окружениях: отсутствие сборочных инструментов, SQLite, MiniZip и systemd-homed. CI сохраняет проверяемый отчёт; проверка не требует сети/ключей и не заменяет полный допуск CVE.
- 2026-11-10: неиспользуемая SQLite дистрибутива исключена из runtime после проверки удаления единственного пакета без зависимых удалений. Кэш provider остаётся в памяти; хранилища и очереди Translator не затрагиваются.
- 2026-11-10: release workflow заново выполняет обновление пакетов ОС; сборка проверяет отсутствие сборочных инструментов в глобальном и прикладном Python-окружении.
- 2026-11-10: runtime отделён от слоя Poetry после обнаружения уязвимых сборочных инструментов в опубликованном образе. Python, Debian Bookworm и lock зависимостей приложения сохранены; глобальные и virtualenv-установщики исключены из runtime. Допуск уязвимостей ОС остаётся открытым.

## Unreleased

- Bound the tagged `v0.1.0` image to its own 20/20 UDS smoke, reviewed raw
  translations and tag-identity signature, SBOM and provenance receipts;
  retained the earlier image's quality report as separate historical evidence.
- Repaired the historical standalone quality report's alternates link to its
  immutable source commit after retirement of the active standalone artifact.
- Recorded the 2026-11-10 exact OpenAI image UDS quality evaluation: 20/20
  contract/literal checks and explicit semantic review; platform clean-room
  admission remains separate.
- Quality smoke requires an immutable image reference, persists partial/failure
  evidence, and optionally records the repository corpus opaque exchanges for
  semantic review without provider credentials or upstream headers.
- Provider release publishes one signed multi-platform index for
  `linux/amd64` and `linux/arm64`, so the immutable digest is directly runnable
  on hosted Linux and Apple Silicon Docker without emulation.
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
