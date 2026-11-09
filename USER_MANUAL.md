# Руководство оператора AELEV Translation Provider

## Текущее состояние

Provider переведён на OpenAI Responses API. Локальная реализация и тесты не
запускают container и не вызывают API. Compute recipe предоставляет provider
исходящий HTTPS-доступ; единственный отсутствующий локальный runtime-ввод —
действующий OpenAI API key.

## Что должен подготовить оператор

1. Локально заменить `REPLACE_WITH_OPENAI_API_KEY` в игнорируемом
   `.env.local`. Не передавать key в чат и не коммитить файл.
2. Для runtime смонтировать этот же `.env.local` только для чтения как
   `/run/secrets/provider/credential.env`; provider принимает единственную
   строку `OPENAI_API_KEY=...` и не раскрывает её Translator.

Корневая инфраструктура не владеет API key, model ID, prompt или
предметными данными. Она предоставляет только generic provider secret mount и
исходящее сетевое подключение.

## Проверка без key

Требуются Python 3.13, Poetry 2.2.1 и Docker с BuildKit:

```sh
poetry install
poetry run ruff check .
poetry run ruff format --check .
poetry run pyright
poetry run pytest -q
docker build --target test .
docker build --target runtime .
```

`verify-config` проверяет lock и prompt digest во время build, но не
читает credential и не делает сетевой запрос. Build не запускает container.

## Bounded live smoke

Live smoke разрешён только после локального добавления key и проверки project
model access и quota. Для проверки используется точный image digest и
ограниченный синтетический corpus. Evidence содержит
только case ID, хеши, warnings и длительности.

Healthcheck не заменяет live smoke: он подтверждает только локальную
готовность без billable API call.

## Выпуск и смена модели

1. Измените code, prompt или `provider.lock.json`; для prompt обновите
   SHA-256 и execution reference.
2. Добавьте запись в `CHANGELOG.md` и выполните все проверки.
3. Смена model ID не делается runtime environment override: нужны новый
   lock, representative evals, image digest и admission.
4. Создайте подписанный tag `vX.Y.Z`; workflow публикует точный
   GHCR digest с SBOM, provenance и keyless signature.
5. В подготовленном Platform clean-room запустите
   `tools/release_quality_smoke.py` против UDS exact digest. Repository workflow
   не создаёт и не хранит API key.
6. Пройдите clean-room gate с exact Translator worker digest.

## Диагностика и откат

- `PROVIDER_CREDENTIAL_UNREADABLE` — key отсутствует, остался placeholder или
  secret file не читается.
- `PROVIDER_RUNTIME_UNAVAILABLE` через opaque-порт — сеть, quota, API access
  или upstream не доступны; сырой upstream-ответ не раскрывается.
- `PROVIDER_RUNTIME_RESPONSE_INVALID` — ответ не совпал с exact model/status/
  structured-output profile.
- `PROVIDER_DEADLINE_EXCEEDED` — bounded timeout; Translator сохраняет job
  для своей retry policy.

Откат — замена только provider digest на ранее допущенный совместимый
digest. Не удаляйте UDS volume, Translator DB, Kafka topics или результаты.
Откат не восстанавливает отозванный credential, не означает `RESUME` и не
запускает остановленный worker.
