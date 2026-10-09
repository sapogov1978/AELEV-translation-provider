# translator-service

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

В поставке ровно два Compose-файла: `compose.remote.yml` содержит канонические определения ролей переводчика и работает с внешней Kafka; `compose.yml` использует эти определения, добавляет каноническую поставку Kafka и включает собственную PostgreSQL без профиля. Промежуточных Compose-файлов и отдельного сетевого скрипта нет. Корневая оркестрация использует те же определения из `compose.remote.yml`; прежнее имя `compose.service.yml` в ADR-0097 отражает историческую раскладку файлов, а не отдельный действующий рецепт.

Команды выполняются из `services/infrastructure/translator-service`. OpenSSL нужен оператору только для генерации секрета и не устанавливается в runtime-образ. Обычный `compose.yml` предназначен для совместного размещения: он загружает Kafka только из `../kafka/compose.yml` и `../kafka/.env`, поднимает собственную PostgreSQL переводчика, Kafka и все роли одной командой. Kafka при отдельном запуске из `../kafka` по-прежнему поднимает только Kafka.

```sh
command -v openssl >/dev/null || { echo "OpenSSL is required" >&2; exit 1; }
test -f ../kafka/.env || cp ../kafka/.env.example ../kafka/.env
cp .env.example .env
mkdir -p secrets
openssl rand -out secrets/postgres-password -hex 32
if [ "$(uname -s)" = Linux ]; then sudo chown 10001:10001 secrets/postgres-password; fi
chmod 600 secrets/postgres-password
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

## Масштабирование и географическое размещение

Единица вычислительного масштабирования — пара `translator-model` + `translator-worker` с локальным socket volume. На удалённом узле используется тот же образ и `compose.remote.yml`; узел подключается по TLS к принадлежащим поставке Kafka и PostgreSQL. Unix socket и model volume между узлами не разделяются. Consumer масштабируются не выше числа partitions. `translator-outbox` остаётся одним активным экземпляром до появления отдельного механизма fencing.

Операционный API: `GET /healthz`, `GET /readyz`, `GET /v1/status`, `GET /metrics`. В нём намеренно отсутствуют POST, PUT, DELETE, тексты заданий и результаты.

## Сборка и проверки

```sh
docker build --build-context translator_tests=./test --target test -t aelev/translator-service:test .
docker run --rm --network none aelev/translator-service:test
docker run --rm --network none aelev/translator-service:test poetry run ruff check src test alembic
docker run --rm --network none aelev/translator-service:test poetry run pyright src test
python3 test/test_configuration.py
```

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
