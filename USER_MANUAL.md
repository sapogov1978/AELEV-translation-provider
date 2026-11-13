# Руководство оператора AELEV Translation Provider

## Текущее состояние

Provider переведён на OpenAI Responses API. Локальная реализация и тесты не
запускают container и не вызывают API. Compute recipe предоставляет provider
исходящий HTTPS-доступ. Действующий API key предоставляется отдельно для каждой
установки. Проверка от 2026-11-10 подтвердила доступ и 20-case bounded live smoke
точного опубликованного image; она не заменяет допуск новой установки. Для
текущего v0.1.1 выполнена отдельная
[проверка exact release](docs/audit/provider-release-v0.1.1-20261111.md) с новым
live-запуском, проверкой смысла, обеих native-архитектур и UDS-пары.

## Что должен подготовить оператор

1. Локально заменить `REPLACE_WITH_OPENAI_API_KEY` в игнорируемом
   `.env.local`. Не передавать key в чат и не коммитить файл.
2. Для runtime смонтировать этот же `.env.local` только для чтения как
   `/run/secrets/provider/credential.env`; provider принимает единственную
   строку `OPENAI_API_KEY=...` и не раскрывает её Translator.

Корневая инфраструктура не владеет API key, model ID, prompt или
предметными данными. Она предоставляет только generic provider secret mount и
исходящее сетевое подключение.

## Независимый сетевой запуск

Worker и provider получают раздельные локальные TLS-каталоги и собственные ключи.
Provider читает `/run/secrets/compute-provider/transport.json`:

```json
{"schema_version":1,"transport":"mtls","listen_host":"0.0.0.0","listen_port":18487}
```

В том же read-only каталоге `identity.json` содержит ровно `schema_version=1`,
`environment` (`local`, `test`, `production`), `delivery` и точные
`server_spiffe_id`/`client_spiffe_id` под `/translator-service/` одного trust domain.
Например, роли `/translator-service/provider/primary` и
`/translator-service/worker/screening` задаются оператором явно, без discovery.
Это workload identities; replicas получают разные leaf certificates и ключи.

В production `delivery=spire-file-v1`: SPIRE доставляет собственные
`current.json`, `generations/<digest>/tls.pem` и `bundle.pem` с актуальным
маркером, serial, сроком и digest. Private key доступен только своему runtime;
корневые/issuer keys не монтируются. Неактуальная доставка закрывает соединение.
`pem-files-v1` разрешён только в local/test: server читает `server.crt`,
`server.key` (mode 0600) и `client-ca.crt`. Самоподписанный local/test CA
не является production-допуском.

Provider слушает указанный адрес/порт; владелец установки публикует его на
достижимом узле и настраивает DNS/SAN. Worker проверяет CA, hostname и exact
provider identity до отправки текста, используя собственный client key.
Для разных хостов socket/SVID volumes и соседние исходники не нужны.
Конфигурация не содержит API key, model ID или prompt; provider credential
остаётся отдельным прежним mount. HTTP fallback запрещён.

Без transport/identity configuration прежний UDS-запуск совместим.
Присутствующая неверная конфигурация или identity без transport.json
завершает запуск с `PROVIDER_TRANSPORT_CONFIG_INVALID`.

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

`tools/release_quality_smoke.py` принимает только immutable `--image` вида
`ghcr.io/...@sha256:...` и сохраняет прогресс, включая отказ. Необязательный
`--raw-output <path>` записывает полные opaque UDS requests/responses только
фиксированного repository-owned corpus для отдельной проверки смысла.
Результат `PASS` закрывает автоматические проверки; поле
`semantic_review=REQUIRED_SEPARATELY` требует отдельного сопоставления переводов
с ожидаемым смыслом. Идентичность реально запущенного image проверяется
оператором по Docker inspect, подписи и provenance до запуска инструмента.

Healthcheck не заменяет live smoke: он подтверждает только локальную
готовность без billable API call.

## Выпуск и смена модели

1. Измените code, prompt или `provider.lock.json`; для prompt обновите
   SHA-256 и execution reference.
2. Добавьте запись в `CHANGELOG.md` и выполните все проверки.
3. Смена model ID не делается runtime environment override: нужны новый
   lock, representative evals, image digest и admission.
4. Создайте аннотированный version tag `vX.Y.Z`; workflow подписывает точный
   GHCR image digest, сохраняя SBOM, provenance и keyless signature. Подпись
   проверяется у image digest; version tag не является его заменой.
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
