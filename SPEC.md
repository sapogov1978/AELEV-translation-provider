# Нормативная спецификация AELEV Translation Provider

## Ответственность

Provider — единственный владелец реализации перевода: выбора API
модели, prompt, локального cache, обработки provider credential, HTTPS-клиента,
проверки ответа и image healthcheck. Он не владеет Kafka topics, заданиями
Translator, consumer identity, приоритетом, retry journal, checkpoints,
operator API или применением результата.

Standalone-веса, downloader и native inference runtime запрещены в активной
сборке и runtime image. Их исторические audit-материалы не являются
действующим runtime-контрактом.

## Непрозрачный порт

Для независимо размещаемых worker/provider используется HTTP/1.1 по HTTPS/mTLS
с явным `transport.json` и точными SPIFFE workload identities по
[ADR-0003](docs/adr/00-PROVIDER-20261113-0003-independent-mtls-transport.md).
Прежний Unix socket `/run/aelev-translator/translator.sock` сохраняется как
совместимость. Неверная/неполная сетевая конфигурация не включает UDS.
`POST /v1/translate` принимает ровно
`schema_version`, `source_language`, `target_language` и `text`. Успешный
ответ содержит только `schema_version`, `translated_text` и `warnings`.
Формальная схема — [contracts/opaque-translation-v1.json](contracts/opaque-translation-v1.json).

До JSON parsing и model dispatch body ограничен 262 144 байтами и 10 секундами
чтения, включая поток без `Content-Length` или с неверной заявленной длиной.
Превышение размера даёт 413, времени чтения — 408 с закрытием соединения.
Сетевой listener ограничивает concurrent HTTP connections/tasks числом 32;
собственное inference по-прежнему последовательно и имеет отдельный deadline.

Model/API identity, execution reference, prompt, credential,
request/job identity и provider-specific settings через порт не проходят.
Невалидный запрос и безопасно классифицируемый семантический отказ
дают 422. Deadline, API failure и невалидный ответ дают 503 с
ограниченным кодом без сырого тела upstream-ответа.

## API-исполнение и предметная область

`provider.lock.json` закрепляет OpenAI Responses endpoint, model ID
`gpt-6.1-sol`, reasoning effort, output budget, `store=false`, exact prompt SHA-256 и
direct HTTPS transport profile. Код не привязан к этому model ID: его замена
выполняется новым lock, quality evidence и provider release, не изменением
opaque-контракта.

В Responses API передаётся весь полученный сегмент, коды и названия
языков и provider-owned instructions. Модель должна молча определить
предметную область всего сегмента и сохранить терминологию, смысл,
регистр, единицы, имена, идентификаторы, код и связи между фразами.
Исходный текст считается данными, а не instructions. Ответ принимается
только по strict JSON schema.

Opaque v1 не передаёт job/domain identity, поэтому provider не хранит
межзапросный контекст: это исключает смешивание данных разных заданий.
Предметная область выводится только из текущего полного сегмента.

## Transport, credentials и readiness

Runtime сохраняет Python 3.13.7 и Debian Bookworm сборочного слоя, но получает
только закреплённое окружение приложения. Poetry и его сборочные зависимости,
pip и setuptools в runtime не включаются. Сборка и тесты сохраняют Poetry 2.2.1.
Неиспользуемая библиотека SQLite дистрибутива исключается из runtime. У provider
нет SQL-порта или устойчивой БД; кэш остаётся ограниченным и расположен в памяти.

Каждый API request идёт напрямую по HTTPS к закреплённому endpoint
`api.openai.com/v1/responses` с проверкой CA/hostname по закреплённому certifi bundle, ограниченными timeout
и конкурентностью. API key принадлежит provider, читается из secret file
или локального environment и не входит в image, lock, журнал или ответ.

`GET /healthz` проверяет локальную готовность process/config/credential без
billable upstream-запроса. Это не доказывает квоту, доступ к модели или
успешный перевод. Их доказывает только bounded
live smoke. В UDS-режиме Docker healthcheck обращается к тому же UDS;
в mTLS-режиме он читает свежий локальный сигнал serving loop и собственной
identity, без ключа клиента и upstream-запроса.

## Исполнение, cache и release admission

Допуск CVE привязан к [рассмотренному профилю](security/runtime-profile.json)
и [проверяемым условиям каждой находки](docs/audit/runtime-security-20261111.md).
Новый сетевой runtime дополнительно требует [TLS review](docs/audit/runtime-security-20261113.md),
включая SNI context lifetime, аргументы in-memory TLS и действительные CA stores.
Он действует для штатного opaque entrypoint с non-root, read-only root,
нулевыми capabilities и no-new-privileges; владелец проверяет их при выкладке.
Изменение рассмотренного кода/зависимостей или новая HIGH/CRITICAL закрывает
допуск. Перед подписью release CI требует успешный audit точного main commit
и проверяет опубликованный native digest, сохраняя сырой scan и решения.

Одновременно исполняется один запрос; FIFO-ожидание ограничено общим
deadline. Cache ограничен 2 048 ключами, включает execution reference и не
является источником истины. Тексты и переводы не журналируются.

Каждый ответ помечается `MACHINE_TRANSLATION_UNVERIFIED`; неизменившийся
текст дополнительно получает `UNCHANGED_OUTPUT`.

Release допускается только по exact image digest с SBOM, provenance и
signature после source/type/lint, Docker test target, opaque UDS/mTLS round-trip,
bounded quality smoke exact model, проверки подписи и clean-room
gate Platform Infrastructure. Локальные тесты без key не дают production
admission.
