# translator-service

Собственный издатель имеет `stop_grace_period: 2m`: это время на завершение текущего запроса и подтверждение отписки через удалённый HTTPS, не запасное значение env и не бесконечное ожидание. Если связь недоступна, неподтверждённый выход сохраняется в журнале, а UI не скрывает строку как штатно завершённую.

В «Состоянии» верхняя строка называется «Перевод текстов» (`Text translation`) и отражает назначение, а раскрываемый состав показывает технологии и процессы этой поставки. Названия публикует сам владелец в ревизии 2; оболочка не содержит таблицы переименований. UUID, identity, состав и последовательность сохраняются.

Самодостаточный инфраструктурный сервис асинхронного перевода. Он нужен, когда нескольким сервисам требуется один воспроизводимый выпуск модели, устойчивая очередь, дедупликация, повтор после отказа и единый контракт результата. Клиенты публикуют `TranslationRequested` в обычный или приоритетный Kafka topic; translator-service сохраняет задание в собственной PostgreSQL, выполняет его локальной копией MADLAD и публикует `TranslationCompleted`. Он ничего не знает о назначении перевода и составе клиентов.

Нормативные документы: [SPEC](SPEC.md), [Kafka-контракт](../../../docs/api/translation.md) и [ADR-0096](../../../docs/adr/20261009-0096-consumer-agnostic-scalable-translator.md).

## Состав поставки

| Роль | Назначение | Режим |
|---|---|---|
| `kafka` | обязательный транспорт из канонической поставки `../kafka` | постоянная, только совместный односерверный режим |
| `translator-database` | собственная очередь, результаты, leases и outbox | постоянная |
| `translator-migrator` | применяет схему БД | одноразовая |
| `translator-topic-provisioner` | после готовности Kafka создаёт и сверяет три принадлежащих сервису topic; при недоступности повторяется | обязательная одноразовая |
| `translator-priority-consumer` | сохраняет `translation.requests.priority.v1` с приоритетом 0 | постоянная |
| `translator-normal-consumer` | сохраняет `translation.requests.v1` с приоритетом 100 | постоянная |
| `translator-model` | offline MADLAD runtime через локальный Unix socket | постоянная |
| `translator-worker` | арендует задания и обращается к локальной модели | постоянная |
| `translator-outbox` | публикует сохранённые результаты | ровно один активный экземпляр |
| `translator-api` | read-only health, readiness и агрегированное состояние | постоянная |

## Подготовка и запуск

В поставке две операторские точки запуска: `compose.yml` для совместного размещения и `compose.remote.yml` для отдельно размещённой Kafka. Все роли и настройки определены только в `compose.remote.yml`. Короткий собственный `compose.local.yml` включает БД без профиля, обязательное ожидание healthy Kafka и сеть провайдера. Его вместе с канонической моделью включает как самостоятельный `compose.yml`, так и корневая оркестрация по [ADR-0104](../../../docs/adr/20261010-0104-owner-contained-compose-recipes.md); runtime, тома и секреты не дублируются. Самостоятельная точка добавляет каноническую Kafka, корень включает её независимо, поэтому отказ от переводчика не лишает инфраструктуру брокера. Прежнее имя `compose.service.yml` в ADR-0097 отражает историческую раскладку, не ещё один действующий файл. Отдельного сетевого скрипта нет.

Команды выполняются из `services/infrastructure/translator-service`. OpenSSL нужен оператору только для генерации секрета и не устанавливается в runtime-образ. Обычный `compose.yml` предназначен для совместного размещения: он загружает Kafka только из `../kafka/compose.yml` и `../kafka/.env`, поднимает собственную PostgreSQL переводчика, Kafka и все роли одной командой. Kafka при отдельном запуске из `../kafka` по-прежнему поднимает только Kafka.

```sh
command -v openssl >/dev/null || { echo "OpenSSL is required" >&2; exit 1; }
test -f ../kafka/.env || cp ../kafka/.env.example ../kafka/.env
cp .env.example .env
mkdir -p secrets
openssl rand -out secrets/postgres-password -hex 32
if [ "$(uname -s)" = Linux ]; then sudo chown 10001:10001 secrets/postgres-password; fi
chmod 600 secrets/postgres-password
python3 prepare-api-tls.py --local --output runtime/api-pki
docker compose --env-file .env config
docker compose --env-file .env up --build -d --wait --wait-timeout 600
docker compose --env-file .env ps
curl --fail http://127.0.0.1:8096/readyz
```

Provisioner запускается автоматически после healthcheck Kafka, создаёт отсутствующие topics и прекращает работу с ошибкой, если существующие параметры не совпадают с декларацией translator-service. Consumer, outbox и API не стартуют до его успешного завершения. `/readyz` проверяет собственную БД, фактическое соединение с Kafka и наличие всех трёх topics; потеря broker делает сервис неготовым. Параметры broker не копируются в `.env` переводчика: совместная поставка читает их непосредственно из Kafka `.env`.

Если Kafka уже развёрнута отдельно своей поставкой, используйте `compose.remote.yml --profile bundled-database` и её существующую сеть: так переводчик подключается к одному действующему broker, а не запускает его второй экземпляр в другом Compose-проекте. Именно этот порядок применяется в тесте жизненного цикла ниже.

Runtime работает с UID/GID `10001:10001`. На Linux пароль и закрытые TLS-ключи с правами `600` должны принадлежать этому UID; каталог должен допускать проход runtime. Для файловых secrets Compose использует bind mount и не переназначает владельца атрибутами `uid`/`gid`, поэтому это проверяется на host, а не исправляется добавлением фиктивных настроек Compose ([Docker](https://docs.docker.com/reference/compose-file/services/#secrets)). Docker Desktop на macOS использует собственное отображение файловых прав; чтение секрета с правами `600` пользователем runtime проверено отдельно без раскрытия содержимого.

Для географически разнесённых узлов настройте в `.env` маршрутизируемые `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_BOOTSTRAP_SERVERS`, `SSL` и имена CA, сертификата и ключа, установите `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_NETWORK_EXTERNAL=false` и запустите распределённую точку входа. Она не создаёт второй локальный broker; Kafka развёртывается своей поставкой на назначенном узле, а переводчик не проходит provisioning и readiness до фактической доступности endpoint. Если PostgreSQL также удалена, не включайте профиль `bundled-database`; если нужна собственная БД на узле переводчика, добавьте этот профиль.

```sh
docker compose -f compose.remote.yml --env-file .env config
docker compose -f compose.remote.yml --env-file .env --profile bundled-database up --build -d --wait --wait-timeout 600
```

Docker Compose управляет только одним Docker daemon и не может сам запустить контейнер на географически удалённой машине. Двухузловое развёртывание выполняется адресно на обоих узлах либо кластерным оркестратором; гарантия со стороны translator-service состоит в обязательной проверке реального удалённого endpoint, а не в создании локального контейнера с тем же именем. Production Kafka должна предоставлять защищённый listener и минимальные ACL для раздельных runtime и deployment identities.

## Настройки `.env`

Все настройки, используемые выбранной точкой запуска, обязательны: Compose прекращает разрешение с явной ошибкой, если переменная отсутствует. `.env` не коммитится, `.env.example` не содержит секретов.

| Переменная | Значение примера | Назначение и необходимость |
|---|---|---|
| `AELEV_INFRASTRUCTURE_TRANSLATOR_ENVIRONMENT` | `local` | Разрешает локальные соединения без TLS; любое другое значение включает обязательный TLS Kafka и PostgreSQL. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_COMPOSE_PROJECT` | `aelev-infrastructure-translator` | Изолирует имена Compose-ресурсов этой поставки. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_ENV_FILE` | `../kafka/.env` | Указывает совместной точке входа на канонический рабочий `.env` Kafka; исключает копирование параметров broker в translator-service. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_BUILD_CONTEXT` | `.` | Определяет точный контекст сборки образа. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_IMAGE` | `aelev/translator-service:local` | Закрепляет единый образ Python-ролей и модели. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_IMAGE` | `postgres:17.6-alpine` | Закрепляет поддерживаемый образ собственной PostgreSQL. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_HOST` | `translator-database` | Адрес БД поставки; может быть маршрутизируемым endpoint принадлежащего ей кластера. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_PORT` | `5432` | TCP-порт PostgreSQL. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_NAME` | `translator_service` | Собственная база translator-service. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_USER` | `translator_service` | Собственная runtime-роль БД. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_SSLMODE` | `disable` | Политика TLS PostgreSQL; вне `local` допустимы только `require`, `verify-ca`, `verify-full`. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_CA_FILE` | `NONE` | Имя CA-файла в каталоге секретов либо `NONE` локально. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_CLIENT_CERT_FILE` | `NONE` | Имя клиентского сертификата PostgreSQL либо `NONE`. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_CLIENT_KEY_FILE` | `NONE` | Имя клиентского ключа PostgreSQL либо `NONE`. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_VOLUME` | `aelev-infrastructure-translator-database` | Явное имя постоянного volume; исключает случайную новую пустую БД. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_NETWORK` | `aelev-infrastructure-translator-data` | Имя внутренней сети БД локальной поставки. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_MEMORY_LIMIT` | `1g` | Верхняя граница памяти встроенной PostgreSQL. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_CPUS` | `1` | Верхняя граница CPU встроенной PostgreSQL. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_SECRET_ROOT` | `./secrets` | Закрытый каталог пароля БД и TLS-файлов. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_NETWORK` | `aelev-infrastructure-kafka` | Локальная Docker-сеть транспортного компонента. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_NETWORK_EXTERNAL` | `true` | Используется распределённой точкой входа: `true` подключает существующую локальную сеть, `false` создаёт обычную выходную сеть для маршрутизируемого удалённого endpoint; совместный `compose.yml` получает внутреннюю сеть из поставки Kafka. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Маршрутизируемые Kafka bootstrap endpoints. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_SECURITY_PROTOCOL` | `PLAINTEXT` | Транспорт Kafka; вне `local` разрешён только `SSL`. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_CA_FILE` | `NONE` | CA runtime identity либо `NONE` локально. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_CLIENT_CERT_FILE` | `NONE` | Сертификат runtime identity для чтения и публикации. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_CLIENT_KEY_FILE` | `NONE` | Ключ runtime identity. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_ADMIN_CA_FILE` | `NONE` | CA отдельной deployment identity provisioner. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_ADMIN_CLIENT_CERT_FILE` | `NONE` | Сертификат identity с правом создавать только topics переводчика. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_ADMIN_CLIENT_KEY_FILE` | `NONE` | Закрытый ключ deployment identity. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_PRIORITY_KAFKA_GROUP` | `aelev-translator-priority-v1` | Независимая consumer group приоритетного topic. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_NORMAL_KAFKA_GROUP` | `aelev-translator-normal-v1` | Независимая consumer group обычного topic. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_TOPIC_PARTITIONS` | `6` | Параллелизм каждого topic и предел полезных consumer одной группы. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_TOPIC_REPLICATION_FACTOR` | `1` | Число Kafka replicas; пример соответствует одноузловой Kafka. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_TOPIC_RETENTION_MS` | `604800000` | Временная retention Kafka, здесь семь суток; БД хранит состояние выполнения. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_TOPIC_RETENTION_BYTES` | `-1` | Не вводит байтовую границу поверх временной retention. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_TOPIC_MAX_MESSAGE_BYTES` | `1048576` | Оставляет запас над runtime-пределом события 262 144 байта для Kafka record overhead. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_TOPIC_MIN_INSYNC_REPLICAS` | `1` | Минимум синхронных replicas для успешной записи. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_HIGH_PRIORITY_BURST` | `4` | После четырёх срочных leases выдаётся готовое обычное задание. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_MODEL_MEMORY_LIMIT` | `4g` | Верхняя граница памяти локальной копии MADLAD. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_MODEL_CPUS` | `2` | CPU локального вычислителя. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_MODEL_BATCH_SIZE` | `1` | Размер model batch; ограничивает память и задержку. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_REQUEST_TIMEOUT_SECONDS` | `240` | Общий deadline обращения к модели. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_SEGMENT_TIMEOUT_SECONDS` | `180` | Deadline сегмента, после которого runtime перезапускается. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_ROLE_MEMORY_LIMIT` | `256m` | Память каждой лёгкой роли. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_ROLE_CPUS` | `0.25` | CPU каждой лёгкой роли. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_BIND_ADDRESS` | `127.0.0.1` | Интерфейс read-only API; loopback закрывает его извне по умолчанию. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_PORT` | `8096` | Порт API на узле. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_CONTAINER_PORT` | `8096` | Порт Uvicorn внутри контейнера. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_NETWORK` | `aelev-infrastructure-translator-ingress` | Отдельная сеть операционного ingress. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_NETWORK_EXTERNAL` | `false` | Определяет, создаёт ли Compose сеть API или подключает существующую. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_PUBLIC_URL` | `https://localhost:18496` | Точный HTTPS origin операционного API, доступный браузеру оператора; издатель добавляет собственный путь `/docs`. Для удалённого узла задайте его FQDN и порт, совпадающие с SAN сертификата. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_HTTPS_BIND_ADDRESS` | `127.0.0.1` | Интерфейс опубликованного HTTPS-порта; для удалённого доступа задайте конкретный адрес узла либо `0.0.0.0` и ограничьте firewall. Это не адрес внутреннего HTTP. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_HTTPS_PORT` | `18496` | HTTPS-порт на узле; должен совпадать с публичным адресом или его явным внешним маршрутом. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_HTTPS_CONTAINER_PORT` | `8443` | Отдельный TLS listener в том же процессе `translator-api`; не может совпадать с внутренним HTTP-портом. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_TLS_ROOT` | `./runtime/api-pki/api-tls` | Каталог собственных `server.crt`, `server.key`, `clients-ca.crt`; Compose монтирует только эти три файла в API и запрещает создание пустых замен. Каталог не должен находиться внутри общего `SECRET_ROOT`, чтобы другим ролям не достался серверный ключ. |

## Swagger операционного API

`translator-api` обслуживает два listener в одном контейнере: прежний частный HTTP для собственных проверок и HTTPS/mTLS для оператора. `/docs` существует только на HTTPS; он показывает те же пять операций чтения, не приватные POST модели. `/openapi.json` генерируется из тех же обработчиков. При отсутствии TLS-файла, недействительной конфигурации или завершении любого listener весь API прекращает работу; plaintext fallback отсутствует. Штатные SIGTERM/SIGINT завершают оба listener. Внутренний host-порт разрешён только на loopback, его прежние пути и ответы сохранены.

Swagger UI 5.33.1, CSS и Apache-2.0 LICENSE доставляются из официального выпуска при сборке с SHA-256 в Dockerfile и затем отдаются с собственного origin. Браузеру не нужны CDN, внешний валидатор или доступ к поставщику модели. CSP запрещает внешние scripts/connections и встраивание; токен оболочки не передаётся, браузерная авторизация не сохраняется JavaScript. Основа: [самостоятельная поставка файлов Swagger в FastAPI](https://fastapi.tiangolo.com/how-to/custom-docs-ui-assets/), [выпуск Swagger UI](https://github.com/swagger-api/swagger-ui/releases/tag/v5.33.1), [TLS-настройки Uvicorn](https://www.uvicorn.org/settings/#https).

HTTPS обязательно требует собственный клиентский сертификат оператора, подписанный явно доверенной `clients-ca.crt` с `clientAuth`. Эта CA должна выдавать только ограниченные удостоверения чтения этого API. Серверу передаются только его ключ/цепочка и открытая CA клиентов: закрытый ключ CA, операторские PEM/PKCS12 и пароль PKCS12 не монтируются ни в API, ни в издатель. mTLS удостоверяет доступ к чтению; административных HTTP-операций здесь нет. Для рабочей среды установите утверждённые серверную цепочку, отдельную CA разрешённых клиентов и операторское удостоверение; файлы и Compose те же, самоподписанный локальный корень не становится автоматически доверенным рабочим корнем.

Для подготовки локального loopback сначала проверьте инструменты:

```sh
python3 --version
command -v openssl
openssl version
```

Скрипт использует стандартную библиотеку Python, а не пакеты runtime. Нужен OpenSSL 3; он используется только оператором, в Dockerfile устанавливать CLI не требуется. Если его нет, на Debian/Ubuntu выполните `sudo apt-get update` и `sudo apt-get install openssl`; на macOS с установленным Homebrew — `brew install openssl@3` и `export PATH="$(brew --prefix openssl@3)/bin:$PATH"`. Затем повторите проверку версии. Установку нового Python/ОС и изменение рабочего стека этот порядок не выполняет.

```sh
python3 prepare-api-tls.py --local --output runtime/api-pki
openssl verify -CAfile runtime/api-pki/api-ca/ca.crt runtime/api-pki/api-tls/server.crt runtime/api-pki/api-operator/operator.crt
```

Повторная генерация поверх существующего каталога запрещена, старые удостоверения не перезаписываются. Локальная CA живёт год, серверное и операторское удостоверения — 30 суток; SAN сервера ограничены `localhost`, `127.0.0.1` и `::1`. Получаются `api-ca` для закрытого выпуска, `api-tls` для сервера и `api-operator` для человека. Все находятся в игнорируемом `runtime`, исключённом из build context и отдельно от монтируемого другим ролям `secrets`. На Linux обеспечьте проход к трём серверным файлам и чтение `server.key` контейнерным UID 10001: `sudo chown -R 10001:10001 runtime/api-pki/api-tls`; ключ CA и операторские файлы остаются только у оператора. Права PKI по умолчанию 700/600, секреты в команды не подставляются.

Импортируйте `runtime/api-pki/api-operator/operator.p12` в клиентские удостоверения своего браузера/ОС; пароль читайте локально из `runtime/api-pki/api-operator/p12-password`, не отправляйте в чат. Доверие серверному корню задаётся отдельным импортом `runtime/api-pki/api-operator/api-ca.crt` только для этой локальной проверки. На macOS клиентский PKCS12 можно импортировать через «Связка ключей», на Linux — через управление сертификатами браузера; не импортируйте `api-ca/ca.key`. Для новой PKI используйте новый каталог, настройте `API_TLS_ROOT`, обновите доверие и адресно пересоздайте только API. Ротация не сбрасывает UUID, sequence, очередь или сохранённые результаты.

Если браузер не предъявляет клиентский сертификат, соединение завершается до HTTP: Chrome может показать `ERR_EMPTY_RESPONSE`, а curl — `Empty reply from server`. Это не подтверждение падения API. Сначала сравните запрос с явно переданным удостоверением по команде ниже; доверие серверному корню и наличие клиентского удостоверения — разные обязательные условия. Тестовый браузер получает сертификат явно и не устанавливает его в системное хранилище; его PASS не означает, что обычный браузер оператора уже настроен.

```sh
curl --fail --cacert runtime/api-pki/api-operator/api-ca.crt --cert runtime/api-pki/api-operator/operator.crt --key runtime/api-pki/api-operator/operator.key https://localhost:18496/readyz
```

Запрос без клиентского удостоверения либо с чужой CA отвергается на TLS до HTTP; `--insecure` не является порядком запуска. После включения профиля `ui` собственный издатель в ревизии 3 публикует `/docs` для группы «Перевод текстов» и компонента «Операционный API». Другие компоненты ссылку не наследуют. UUID и журнал остаются прежними; изменение публичного адреса требует большей ревизии по [контракту ссылок](../../../docs/api/platform-ui-injection.md#ссылки-на-собственные-интерфейсы). При откате сначала публикуйте описание без ссылки в большей ревизии совместимым издателем, не запускайте прежнюю ревизию 2 против уже принятой 3 и не сбрасывайте том.

## Масштабирование и географическое размещение

Единица вычислительного масштабирования — пара `translator-model` + `translator-worker` с локальным socket volume. На удалённом узле используется тот же образ и `compose.remote.yml`; узел подключается по TLS к принадлежащим поставке Kafka и PostgreSQL. Unix socket и model volume между узлами не разделяются. Consumer масштабируются не выше числа partitions. `translator-outbox` остаётся одним активным экземпляром до появления отдельного механизма fencing.

Операционный API: `GET /healthz`, `GET /readyz`, `GET /v1/status`, `GET /v1/components`, `GET /metrics`. В нём намеренно отсутствуют POST, PUT, DELETE, тексты заданий и результаты. Защищённая документация описана [выше](#swagger-операционного-api).

## Сборка и проверки

```sh
docker build --build-context translator_tests=./test --target test -t aelev/translator-service:test .
docker run --rm --network none aelev/translator-service:test
docker run --rm --network none aelev/translator-service:test poetry run ruff check src test alembic
docker run --rm --network none aelev/translator-service:test poetry run pyright src test
python3 test/test_configuration.py
```

Проверка Swagger использует работающие API и оболочку, выполняет только чтение и не создаёт переводческих заданий или Docker-ресурсов. В операторском окружении требуются Playwright 1.56.0 и установленный Chromium; пароль пользователя оболочки передаётся только файлом. Из каталога сервиса:

```sh
python3 test/swagger.py \
  --ca runtime/api-pki/api-operator/api-ca.crt \
  --cert runtime/api-pki/api-operator/operator.crt \
  --key runtime/api-pki/api-operator/operator.key \
  --untrusted-cert secrets/status/publisher.crt \
  --untrusted-key secrets/status/publisher.key \
  --chromium <путь-к-установленному-Chromium> \
  --ui-url https://<адрес-оболочки>:<порт> \
  --viewer-user <оператор> \
  --viewer-password-file <файл-пароля>
```

Отрицательная проверка требует удостоверения, которое API не доверяет; для раздельных локальных CA подходит собственное удостоверение издателя. Только при локальной проверке на loopback с локальной PKI можно явно добавить `--allow-local-certificate`: HTTPS-пробы всё равно проверяют CA и SAN, рабочие TLS-проверки не отключаются. [Сводный результат Swagger](test/swagger-validation-result.md), [настоящий браузерный результат](test/swagger-live-result.md) и [снимок](test/swagger.png) отделены от прежнего полного испытания перевода.

Каталог `test` исключён из обычного build context через `.dockerignore` и поэтому не попадает в runtime-образы. Только test-stage получает его явно как именованный контекст `translator_tests`; сборка test-stage без `--build-context translator_tests=./test` должна завершиться ошибкой, а не молча создать образ без проверок.

[`test/lifecycle.py`](test/lifecycle.py) проверяет канонические поставки: Kafka из `../kafka/compose.yml`, переводчик из `compose.remote.yml` с собственной PostgreSQL и настоящей MADLAD. Используются рабочие `.env`, секреты и имена проектов; отдельные тестовые broker, БД, модели или конфигурации не создаются. Проверены оба инициализатора, приоритетная и обычная очереди, повтор без вычисления, сохранность после полного перезапуска, неготовность при отказе Kafka и доставка outbox после восстановления.

Образы подготавливаются отдельно до теста: завершённая сборка рабочей модели является результатом поставки, а не временной тестовой сущностью. Внутри теста запрещены сборка и загрузка образов: запуск использует `--no-build --pull never`. Так в исходную опись уже входят рабочие образы, модель, секреты и кеш; тест их не меняет и не удаляет.

```sh
docker compose -f ../kafka/compose.yml --env-file ../kafka/.env pull kafka
docker compose -f compose.remote.yml --env-file .env --profile bundled-database pull translator-database
docker compose -f compose.remote.yml --env-file .env --profile bundled-database build translator-model
python3 test/lifecycle.py
```

Это полный остановочный тест для чистого стенда. До создания ресурсов он фиксирует опись контейнеров, сетей, volumes и образов, проверяет локальные endpoints собственной PostgreSQL и Kafka, наличие подготовленных образов и отсутствие чужих подключений к используемым сетям. Если контейнеры целевых проектов или их data/socket volumes уже существуют, тест отказывается продолжать без изменения данных; наличие `--allow-disruption` больше не является способом обойти эту защиту. Тестовые задания невозможно адресно удалить из общего Kafka-журнала, поэтому проверка на уже используемой инфраструктуре не могла бы обещать восстановление исходного состояния.

После успеха, ошибки или первого прерывания тест останавливает свои роли и адресно удаляет только ресурсы, отсутствовавшие в исходной описи и принадлежащие запущенным проектам: контейнеры, именованные и анонимные volumes, сети. Вместе с созданными этим прогоном volumes удаляются его Kafka topics, сообщения, задания и результаты. Существовавшие до запуска ресурсы не удаляются; их наличие и состояние сверяются после очистки. Ошибка удаления или остаток ресурса делает весь прогон неуспешным. Нет общего `prune`, принудительного удаления, стирания рабочих `.env`/секретов или перезапуска Docker daemon.

Для проверки аварийной ветви выполните `python3 test/lifecycle.py --fail-after-start`: после готовности всех ролей будет намеренно выброшена ошибка, код завершения `1`, но завершающая очистка должна иметь результат `PASS`. Это не успешный полный жизненный цикл; результат этого сценария сохраняется отдельно в [отчёте аварийной очистки](test/lifecycle-failure-cleanup-result.md) и не перезаписывает полный результат. Текущий полный результат — [`test/lifecycle-result.md`](test/lifecycle-result.md); подробные этапы и обе описи — [`test/lifecycle-result.json`](test/lifecycle-result.json).

Итоговый отчёт — [`test/validation-result.md`](test/validation-result.md): полный жизненный цикл на реальных компонентах пройден, но обнаружена смысловая добавка в переводе MADLAD, поэтому качество перевода не считается подтверждённым. Читаемый отчёт базового набора — [`test/pytest-result.md`](test/pytest-result.md), регрессии повторного provisioning — [`test/provisioner-regression.md`](test/provisioner-regression.md). Конфигурационные проверки выполняются на хосте, поскольку test-образ не содержит Docker CLI. Изолированные SQL-тесты в CI требуют `AELEV_TRANSLATOR_TEST_DATABASE_URL` и одноразовой базы `translator_test` с миграциями; без неё pytest явно отмечает пропуск. Их нельзя направлять на рабочую БД: порядок подготовки закреплён в [сервисном CI](../../../.github/workflows/translator-service-validation.yml). Такие проверки не заменяют полный жизненный цикл, а текущий локальный прогон не подтверждает удалённые TLS/mTLS, физически разнесённые узлы или нагрузочные пределы.

`contracts/translation-v1.json` генерируется из общего канонического каталога. `obsolete/` содержит только исторические рецепты и не входит в активную поставку.

## Собственное состояние в platform-ui

Повторная проверка названия назначения и технологического состава: [результат](test/status-labels-result.md). Она не подменяет прежние испытания жизненного цикла.

Профиль `ui` включает только собственную техническую роль публикации; обычный запуск не зависит от оболочки или IdP. Отдельная строка имеет тип `INFRASTRUCTURE`, не добавляет функциональные разделы. Состав: собственная БД, соединение с Kafka, два consumer, модель, worker, outbox, API и издатель; тексты заданий и сведения о потребителях не публикуются. Подтверждённая отрицательная native readiness отличается от отсутствия связи: transport/TLS-ошибка означает `UNKNOWN`. При штатной остановке издатель подтверждает отписку, и строка исчезает; при исчезновении публикаций без отписки строка остаётся с «Нет связи» после срока свежести приёмника.

Поставка использует собственный образ и включённый публичный `aelev-platform-ui-client==1.1.0` в `vendor`; SHA-256 закреплён собственным Poetry lock. Это библиотека транспорта, не общий runtime-образ/каталог продуктов. Сборка после извлечения этого каталога не читает соседние исходники. Протокол, установка артефакта и пример собственного издателя: [руководство оболочки](../platform-ui/USER_MANUAL.md#отправить-метаданные-из-python).

Из этого каталога, после подготовки удостоверений:

```sh
docker compose --env-file .env --profile ui build translator-service-status-publisher
docker compose --env-file .env --profile provision run --rm translator-service-status-provision
docker compose --env-file .env --profile ui up -d --no-build translator-service-status-publisher
docker compose --env-file .env --profile ui stop translator-service-status-publisher
```

Рабочий процесс получает только `secrets/status/{shell-ca.crt,identity-ca.crt,publisher.crt,publisher.key,client-secret}`. Одноразовый `provision` получает отдельные `secrets/status-admin/{admin-user,admin-password}`, не монтируемые в runtime. Закрытые ключи CA не доставляются в контейнеры. Используйте утверждённые цепочки CA, SAN/EKU и ротацию; генерация локального удостоверения описана в руководстве и не заменяет production PKI/SVID. HTTPS-адреса могут находиться в разных странах; общей Docker-сети с UI/IdP нет. `host.docker.internal` и `keycloak:host-gateway` — только локальные адресные alias примера; для удалённой установки задайте реальные FQDN/порты и доступность сети. Проверка сертификатов не отключается.

| Переменная | Назначение |
|---|---|
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_URL` | HTTPS-адрес платформенного технического API. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_IDENTITY_URL` | HTTPS-адрес IdP; должен совпадать с SAN сертификата. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_REALM` | Realm собственной машинной identity. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_CLIENT_ID` | Client ID только собственной роли публикации. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_AUDIENCE` | Аудитория JWT платформенного API. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_MODULE_ID` | Постоянный UUID собственного описания. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_DESCRIPTION_REVISION` | Положительная ревизия описания, сейчас 3. При изменении публичного адреса/состава увеличьте её, сохранив UUID и журнал; исходники для переноса endpoint менять не требуется. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_INTERVAL_SECONDS` | Интервал публикации; браузер по-прежнему опрашивает раз в минуту. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_TIMEOUT_SECONDS` | Предел каждой собственной сетевой пробы/отправки. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_SECRET_ROOT` | Собственные рабочие удостоверения, без административных файлов. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_SECRET_GID` | Дополнительная группа чтения собственных секретов. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_ADMIN_ROOT` | Отдельные operator credentials только явной одноразовой задачи. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_PROVISION_UID` | UID оператора для одноразовой записи собственного client secret. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_STATE_VOLUME` | Постоянный журнал последовательности и точных повторяемых байтов. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_MEMORY_LIMIT` | Лимит памяти только издателя. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_PRESENCE_INTERVAL_SECONDS` | Период собственного heartbeat роли и локальной пробы модели. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_PRESENCE_TTL_SECONDS` | Возраст, после которого присутствие роли неизвестно. |

Журнал `UI_STATE_VOLUME` сохраняется при stop/start и обновлении; не удаляйте его как кэш: приёмник помнит sequence прежнего UUID. Восстановление требует собственного backup журнала или согласованного нового UUID, не сброса чужой БД/повторного sequence=1. Состояние оболочки восстанавливается повторной публикацией, canonical источник описания/состава остаётся у владельца.

`test/status_publication.py` работает с уже существующей настоящей установкой: OIDC/API/DOM, stop/start частей и издателя, реальное истечение TTL, возврат исходных контейнеров. Пример: `python3.13 test/status_publication.py --ui-url https://<ui-host>:<port> --viewer-user <viewer> --viewer-password-file <password-file> --chromium <installed-chromium> --status-ttl-seconds 120`. Требуются Python 3.13 и Playwright 1.56.0 в операторской тестовой среде; runtime-образ их браузерную роль не запускает. Исключение браузерной проверки сертификата допустимо только явным `--allow-local-certificate` на loopback с локальной PKI; рабочие издатели всегда проверяют TLS. Тест не создаёт фиктивных identities, каталогов, контейнеров, сетей или томов и восстанавливает исходное состояние; отчёт/снимок остаются в `test`. Полный остановленный приёмник UI физически не может доставить собственный свежий отчёт: проверяется UNKNOWN в уже открытом браузере и восстановление после старта.

Результаты текущей проверки публикации состояния: [читаемый отчёт](test/status-validation-result.md), [проверка нативных частей](test/status-native-result.md), [проверка издателя](test/status-publication-result.md). Прежние предметные/кластерные испытания не подменяются этой проверкой.
