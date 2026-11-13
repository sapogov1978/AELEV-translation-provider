# AELEV Translation Provider

Signed [v0.2.0](docs/audit/provider-release-v0.2.0-20261113.json) passed supply-chain,
native security and mTLS transport checks but is **not quality-admitted**: one
translation added an unstated numerical subset. Candidate v0.2.1 pins prompt v2
and safe provider-local failure diagnostics; its new exact-image quality gate
remains pending.

Непрозрачный provider перевода для AELEV. Standalone-модели, весов и
нативного inference runtime в активной поставке больше нет. Provider
вызывает OpenAI Responses API напрямую по HTTPS с проверкой CA/hostname по
закреплённому пакету certifi.
Текущий выбор в [provider.lock.json](provider.lock.json) — `gpt-6.1-sol`.

Подписанный [v0.1.1](docs/audit/provider-release-v0.1.1-20261111.md) проверен
на обеих native-архитектурах по ограниченному security-профилю, прошёл 20
live-переводов с отдельной проверкой смысла и UDS-проверку с exact worker.
Полный инфраструктурный clean-room и допуск площадки остаются отдельными gates.

Новый сетевой режим по [ADR-0003](docs/adr/00-PROVIDER-20261113-0003-independent-mtls-transport.md)
позволяет размещать Translator worker и provider независимо через HTTPS/mTLS;
UDS сохраняется для совместимости. Выпуск v0.1.1 выше не является допуском
нового сетевого runtime.

Translator передаёт через opaque-порт только текст и пару языков.
Provider обогащает запрос provider-owned prompt: модель молча
определяет предметную область всего сегмента и сохраняет
терминологию, регистр, единицы, имена, код и межфразовые связи.
Модель, API, prompt, credential и execution reference не
пересекают opaque-порт.

```mermaid
flowchart LR
    T[translator-service worker] -->|opaque HTTP v1 over mTLS| P[translation provider]
    P -->|bounded HTTPS POST| O[OpenAI Responses API]
    P -. translated text + bounded warnings .-> T
```

## Что где искать

- [SPEC.md](SPEC.md) — нормативные границы.
- [USER_MANUAL.md](USER_MANUAL.md) — проверка, секреты, выпуск и откат.
- [contracts/opaque-translation-v1.json](contracts/opaque-translation-v1.json) — неизменный
  приватный контракт.
- [provider.lock.json](provider.lock.json) — API model ID, prompt digest и execution
  profile; для смены модели нужен новый provider release.
- [prompts/domain-preserving-translation-v2.txt](prompts/domain-preserving-translation-v2.txt)
  — закреплённый domain-preserving prompt.
- [TASKS.md](TASKS.md) — открытые integration/admission gates.

## Проверка без API key

```sh
poetry install
poetry run ruff check .
poetry run ruff format --check .
poetry run pyright
poetry run pytest -q
docker build --target test .
docker build --target runtime .
```

Build не запускает container и не требует API key. Для локальной
подготовки замените плейсхолдер в игнорируемом `.env.local`; этот же файл
монтируется read-only как provider credential и не коммитится. После подготовки
runtime-сети действующий OpenAI API key нужен для реального перевода;
независимый сетевой запуск дополнительно требует явных адресов и TLS identities
по [руководству](USER_MANUAL.md#независимый-сетевой-запуск).
