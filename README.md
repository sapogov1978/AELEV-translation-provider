# translator-service

## Структура поставки

```text
translator-service/
├── README.md, SPEC.md, USER_MANUAL.md, TASKS.md, CHANGELOG.md
├── compose.yml                   # собственная точка совместного запуска
├── compose.remote.yml            # канонические роли и удалённый брокер
├── compose.local.yml             # собственные локальные зависимости
├── .env.example                  # шаблон; .env — рабочие настройки вне Git
├── Dockerfile, pyproject.toml, poetry.lock
├── src/translator_service/       # API, Kafka, очередь, модель, издатель
├── alembic.ini, alembic/          # собственная схема и миграции БД
├── contracts/, vendor/, typings/ # закреплённые артефакты и типы
├── translator.lock.json          # выпуск модели, размеры и SHA-256
├── download-model.py
├── prepare-api-tls.py             # только новая локальная HTTPS PKI
├── secrets/
│   ├── README.md
│   ├── postgres-password         # отдельная доставка, вне Git/образа
│   ├── status/                   # собственная identity издателя
│   └── ...                       # Kafka/SQL TLS по именам из env
├── runtime/                      # вне Git; не источник настроек
│   ├── api-pki/                  # api-ca/, api-tls/, api-operator/
│   └── status-admin/             # рекомендуемый отдельный UI_ADMIN_ROOT
└── test/                         # проверки, эксперименты и результаты
```

Дерево показывает значимые файлы поставки, а не кэши инструментов. `.env`, содержимое `secrets/` и производные `runtime/` создаются оператором и не входят в Git или образ; документация `secrets/README.md`, где она есть, остаётся в Git. Постоянные данные находятся в именованных Docker volumes из Compose, не в каталоге исходников.

## Назначение


Собственный издатель имеет `stop_grace_period: 2m`: это время на завершение текущего запроса и подтверждение отписки через удалённый HTTPS, не запасное значение env и не бесконечное ожидание. Если связь недоступна, неподтверждённый выход сохраняется в журнале, а UI не скрывает строку как штатно завершённую.

В «Состоянии» верхняя строка называется «Перевод текстов» (`Text translation`) и отражает назначение, а раскрываемый состав показывает технологии и процессы этой поставки. Названия публикует сам владелец; для Index-Translate 9B пример использует ревизию 5, оболочка не содержит таблицы переименований. UUID, identity, состав и последовательность сохраняются.

Самодостаточный инфраструктурный сервис асинхронного перевода. Он нужен, когда нескольким сервисам требуется один воспроизводимый выпуск модели, устойчивая очередь, дедупликация, повтор после отказа и единый контракт результата. Клиенты публикуют `TranslationRequested` в обычный или приоритетный Kafka topic; translator-service сохраняет задание в собственной PostgreSQL, выполняет его локальной копией Index-Translate 9B и публикует `TranslationCompleted`. Он ничего не знает о назначении перевода и составе клиентов. Выбор модели и порядок смены определены [ADR-0112](../../../docs/adr/20261011-0112-index-translate-9b.md).

Нормативные документы: [SPEC](SPEC.md), [Kafka-контракт](../../../docs/api/translation.md) и [ADR-0096](../../../docs/adr/20261009-0096-consumer-agnostic-scalable-translator.md).

## Секреты: получение и подготовка

| Материал | Источник и использование |
|---|---|
| `secrets/postgres-password` | Уникальный пароль собственной БД; первичная локальная команда находится в разделе подготовки. Рабочую выдачу/ротацию выполняет внешнее хранилище и администратор этой БД. |
| SQL CA/сертификат/ключ | PKI собственной SQL-роли; имена файлов задают DATABASE_CA_FILE/DATABASE_CLIENT_CERT_FILE/DATABASE_CLIENT_KEY_FILE. CN соответствует роли, сервер проверяется по реальному имени. |
| Kafka runtime CA/сертификат/ключ | PKI брокера и собственная минимальная identity consumer/outbox/API; имена задают KAFKA_CA_FILE/KAFKA_CLIENT_CERT_FILE/KAFKA_CLIENT_KEY_FILE. |
| Kafka deployment CA/сертификат/ключ | Отдельная identity только подготовки topics переводчика: KAFKA_ADMIN_CA_FILE/KAFKA_ADMIN_CLIENT_CERT_FILE/KAFKA_ADMIN_CLIENT_KEY_FILE. Не заменять runtime правами администратора. |
| API_TLS_ROOT: `server.crt/key`, `clients-ca.crt` | Серверное удостоверение и доверие операторским mTLS-клиентам для HTTPS-режима. CA/key оператора не должны находиться в этом каталоге. |
| API_OIDC_CA_FILE | Публичная CA HTTPS IdP; нужна для OIDC в локальном HTTP и при операторском POST в HTTPS. Доставляется в отдельный каталог API по своему имени из env. |
| Операторский пароль браузера | Действующий пароль пользователя Keycloak с собственными operator-read/operator-translate; не client ID и не пароль SQL или издателя. |

Для новой локальной HTTPS PKI выполните `python3.13 prepare-api-tls.py`: по умолчанию создаются `runtime/api-pki/api-ca` (CA на 365 дней, ключ только оператору), `api-tls` (сервер на 30 дней) и `api-operator` (отдельный clientAuth на 30 дней, PKCS12 и его файл пароля). Скрипт отказывает при существующем корневом каталоге. Операторские PKCS12/ключ не нужны локальному HTTP/OIDC-режиму и не импортируются в системное доверие корпоративной машины. Рабочая PKI выдаётся внешним источником, а не этим локальным генератором.

Ключи API и пароль SQL доступны только UID 10001; для Linux используйте права `0600` и владельца `10001:10001`, как в разделе запуска, с проходом по родительским каталогам. SQL/Kafka filenames разрешаются внутри SECRET_ROOT; при локальных `NONE` и отключённом TLS не создавайте пустые сертификаты. Путь API_TLS_ROOT должен оставаться вне SECRET_ROOT.

Обратите внимание на текущий общий bind SECRET_ROOT: вложенные каталоги также видимы ролям, которые его получают. Шаблон UI_ADMIN_ROOT внутри `secrets/status-admin` не обеспечивает файловую изоляцию административного пароля. Для новой поставки задайте UI_ADMIN_ROOT=`./runtime/status-admin` вне SECRET_ROOT и доставляйте административные файлы туда; существующий материал переносится отдельно согласованной операцией, не этой правкой документации. То же правило действует для закрытых CA и операторских ключей. Текущий общий каталог runtime/deployment Kafka TLS также не доказывает отдельную файловую изоляцию их ключей; исправление mounts остаётся реализационной задачей.

SQL-пароль меняется согласованно в существующей собственной БД и во всех собственных подключениях без очистки очереди. OIDC operator-provision задаёт публичный PKCE-клиент, не пароль для пользователя: пользователь и его действующий пароль принадлежат Keycloak. API_TLS и Kafka/SQL identity обновляются контролируемо с повторной проверкой readiness и Kafka результата; прежний выпуск модели, задания, outbox и последовательность статуса от ротации не меняются.

### Секреты издателя состояния

Пути ниже соответствуют шаблону `UI_SECRET_ROOT=./secrets/status`; при другом значении используйте собственный настроенный каталог. Источники доверия определяются адресами, не совместным размещением: узел в другой стране получает публичные цепочки CA и своё удостоверение через защищённую доставку, а не доступ к чужой папке.

| Файл | Откуда получить и зачем |
|---|---|
| `shell-ca.crt` | Проверенная публичная цепочка CA HTTPS-сервера оболочки; получить у её оператора. Это не CA клиентских издателей. |
| `identity-ca.crt` | Проверенная публичная цепочка CA HTTPS IdP; получить у оператора IdP. |
| `publisher.crt`, `publisher.key` | Собственное удостоверение `clientAuth`; его выпускающая CA должна входить в `publisher-ca.crt` приёмника UI. Закрытый ключ принадлежит только этому издателю. |
| `client-secret` | Выдаёт Keycloak для собственного confidential client; сохраняет `translator-service-status-provision`. Не генерируйте произвольный пароль вместо секрета существующего OIDC-клиента. |

`UI_ADMIN_ROOT` содержит отдельные `admin-user` и `admin-password`: имя и действующий пароль администратора развёртывания Keycloak получают у оператора IdP или из внешнего хранилища. Это не пароль service account и не пароль пользователя браузера. Доставьте их файловым механизмом; например, `install -m 640 /secure/idp-admin-password runtime/status-admin/admin-password`, а имя запишите в `admin-user` без секрета. Provision должен иметь право записи в `UI_SECRET_ROOT`, runtime — только чтение.

Перед локальной подписью проверьте `openssl version` и поддержку OpenSSL 3; при отсутствии используйте утверждённый пакет вашей ОС (`brew install openssl@3` на macOS, `sudo apt-get install openssl` на поддерживаемой Debian/Ubuntu) или подготовленную операторскую станцию. Эти команды не устанавливают CA в системное доверие и не выполняются при запуске контейнера.

Первичная доставка административных файлов (пути источника и имя замените данными своего IdP, не пароль в команде):

```sh
umask 077
install -d -m 750 runtime/status-admin
test ! -e runtime/status-admin/admin-user && test ! -e runtime/status-admin/admin-password || exit 1
STATUS_ADMIN_USER=deployment-admin
printf '%s\n' "$STATUS_ADMIN_USER" > runtime/status-admin/admin-user
install -m 640 /secure/idp-admin-password runtime/status-admin/admin-password
chmod 640 runtime/status-admin/admin-user
```

Имя deployment-admin — пример существующей identity, не команда создания пользователя. Если у вас другое имя или UI_ADMIN_ROOT, задайте их явно; GID каталога/файлов должен совпадать с UI_SECRET_GID, а владелец — с UI_PROVISION_UID. Уже доставленные пароли не перезаписываются первичной командой. После удаления одноразового контейнера пароль не нужен рабочему издателю; локальную административную доставку уберите из runtime-узла или выдавайте заново только на время provision.


Для новой локальной identity можно создать ключ и CSR на доверенной операторской машине. Нужен OpenSSL 3 для `-copy_extensions`; пути `/secure/...` ниже заменяются выбранными операторскими файлами, это не обязательные каталоги сервиса. Публичные CA берутся из проверенного источника; неизвестный сертификат из сети не становится доверенным только потому, что назван `ca.crt`.

```sh
umask 077
install -d -m 750 secrets/status
test ! -e secrets/status/publisher.key && test ! -e secrets/status/publisher.crt || exit 1
openssl req -new -newkey rsa:3072 -nodes -sha256 \
  -subj /CN=publisher -addext 'extendedKeyUsage=clientAuth' \
  -keyout secrets/status/publisher.key -out secrets/status/publisher.csr
# Только локальный тест: ключ CA остаётся на операторской машине, не в runtime.
openssl x509 -req -sha256 -days 30 -copy_extensions copy \
  -in secrets/status/publisher.csr \
  -CA /secure/ui-publisher-ca.crt -CAkey /secure/ui-publisher-ca.key \
  -CAcreateserial -out secrets/status/publisher.crt
install -m 640 /secure/ui-server-ca.crt secrets/status/shell-ca.crt
install -m 640 /secure/idp-ca.crt secrets/status/identity-ca.crt
chmod 640 secrets/status/publisher.key secrets/status/publisher.crt
```

Тестовую CA издателей создаёт оператор локальной оболочки при её явной подготовке PKI; берутся именно `issuer/publisher.crt/key`, не серверный ключ UI. В рабочей среде последнее подписание локальной CA не выполняют: удостоверение и обновляемую identity доставляет утверждённая PKI/SPIRE по [ADR-0017](../../../docs/adr/20260803-0017-zero-trust-and-operational-security.md). CSR можно передать CA, закрытый ключ нельзя. Перед включением издателя доставьте также перечисленные файлы нативных проб и выполните собственный `--profile provision run --rm translator-service-status-provision` из раздела запуска.

### Хранение, доступ и ротация

Секреты разделяются по среде, владельцу и роли. Локальные файлы — только материал стенда или доставка, не каноническое production-хранилище; рабочий источник — внешнее утверждённое хранилище, доставка в память/tmpfs по ADR-0017. Не включайте секреты в Git, образ, архив исходников, команды с подстановкой содержимого или отчёты. Не запускайте `set -x`, не публикуйте раскрытый `docker compose config`; проверяйте через `config --quiet`. Резервные копии секретов хранятся отдельно, зашифрованно, с ограниченным доступом; закрытые CA — только у оператора/KMS/HSM, никогда у рабочего процесса.

Для status-файлов установите каталоги `0750`, файлы `0640`, группу из собственного `UI_SECRET_GID`; владельцем каталога должен быть оператор с `UI_PROVISION_UID`, которому разрешена запись client-secret. UID рабочего издателя остаётся заданным собственным образом/Compose; дополнительная группа даёт только чтение. В командном примере ниже STATUS_SECRET_GID — числовое значение уже настроенного UI_SECRET_GID, не новая переменная сервисного env. Не делайте ключи общедоступными ради запуска. Права нативных секретов описаны отдельно выше.

```sh
: "${STATUS_SECRET_GID:?set the numeric GID from your UI_SECRET_GID}"
chgrp "$STATUS_SECRET_GID" secrets/status secrets/status/*
chmod 750 secrets/status
chmod 640 secrets/status/*
```

Для отдельного административного каталога примените ту же группу, `0750` каталогу и `0640` обоим файлам; владельцу из UI_PROVISION_UID должно быть разрешено чтение admin-password и запись client-secret в status. Keycloak использует административный пароль через env, а не status-admin.

Проверьте срок, SAN/EKU и цепочку сертификата до запуска: `openssl x509 -in secrets/status/publisher.crt -noout -dates -ext extendedKeyUsage`, `openssl verify -CAfile /secure/ui-publisher-ca.crt -purpose sslclient secrets/status/publisher.crt`. Локальное удостоверение из команды действует 30 дней и не обновляется автоматически. Для смены CA сначала доставляют доверие старой и новой цепочкам, затем новые удостоверения, проверяют соединения и только после этого отзывают старые. Ротацию проводят через отдельный подготовленный набор файлов и контролируемое пересоздание собственной роли; генераторы первичного запуска не используют для перезаписи активных ключей. Новый client-secret сначала создают в собственном клиенте Keycloak, затем доставляют повторным собственным provision и пересоздают издателя; обычный повтор provision сам по себе не является ротацией. UUID, identity, ревизия и журнал последовательностей при этом сохраняются.


## Состав поставки

| Роль | Назначение | Режим |
|---|---|---|
| `kafka` | обязательный транспорт из канонической поставки `../kafka` | постоянная, только совместный односерверный режим |
| `translator-database` | собственная очередь, результаты, leases и outbox | постоянная |
| `translator-migrator` | применяет схему БД | одноразовая |
| `translator-topic-provisioner` | после готовности Kafka создаёт и сверяет три принадлежащих сервису topic; при недоступности повторяется | обязательная одноразовая |
| `translator-priority-consumer` | сохраняет `translation.requests.priority.v1` с приоритетом 0 | постоянная |
| `translator-normal-consumer` | сохраняет `translation.requests.v1` с приоритетом 100 | постоянная |
| `translator-model` | автономная Index-Translate 9B через локальный Unix socket | постоянная |
| `translator-worker` | арендует задания и обращается к локальной модели | постоянная |
| `translator-outbox` | публикует сохранённые результаты | ровно один активный экземпляр |
| `translator-api` | частная диагностика; операторский Swagger и авторизованный перевод через Kafka | постоянная |

## Подготовка и запуск

В поставке две операторские точки запуска: `compose.yml` для совместного размещения и `compose.remote.yml` для отдельно размещённой Kafka. Все роли и настройки определены только в `compose.remote.yml`. Короткий собственный `compose.local.yml` включает БД без профиля, обязательное ожидание healthy Kafka и сеть провайдера. Его вместе с канонической моделью включает как самостоятельный `compose.yml`, так и корневая оркестрация по [ADR-0104](../../../docs/adr/20261010-0104-owner-contained-compose-recipes.md); runtime, тома и секреты не дублируются. Самостоятельная точка добавляет каноническую Kafka, корень включает её независимо, поэтому отказ от переводчика не лишает инфраструктуру брокера. Прежнее имя `compose.service.yml` в ADR-0097 отражает историческую раскладку, не ещё один действующий файл. Отдельного сетевого скрипта нет.

Команды выполняются из `services/infrastructure/translator-service`. OpenSSL нужен оператору только для генерации секрета и не устанавливается в runtime-образ. Обычный `compose.yml` предназначен для совместного размещения: он загружает Kafka только из `../kafka/compose.yml` и `../kafka/.env`, поднимает собственную PostgreSQL переводчика, Kafka и все роли одной командой. Kafka при отдельном запуске из `../kafka` по-прежнему поднимает только Kafka.

```sh
command -v openssl >/dev/null || { echo "OpenSSL is required" >&2; exit 1; }
if [ ! -f ../kafka/.env ]; then (umask 077; cp ../kafka/.env.example ../kafka/.env); fi
if [ ! -f .env ]; then (umask 077; cp .env.example .env); fi
mkdir -p secrets
if [ ! -f secrets/postgres-password ]; then
  (umask 077; openssl rand -out secrets/postgres-password -hex 32)
fi
if [ "$(uname -s)" = Linux ]; then sudo chown 10001:10001 secrets/postgres-password; fi
chmod 600 secrets/postgres-password
docker compose --env-file .env config --quiet
docker compose --env-file .env up --build -d --wait --wait-timeout 600
docker compose --env-file .env ps
curl --fail http://127.0.0.1:8096/readyz
```

Перед `config` подготовьте операторский listener по выбранному разделу Swagger ниже: HTTPS требует собственного серверного TLS-каталога, локальный HTTP — настройки OIDC и открытой CA IdP. Генерация `prepare-api-tls.py` применяется только для новой локальной HTTPS PKI; её нельзя повторять поверх существующих удостоверений. При готовой поставке используйте `up -d --no-build --pull never`; повторный запуск не требует смены пароля БД, ключей или весов. Не запускайте отдельный Compose над томами, уже занятыми корневой оркестрацией; команды нужно выполнять в проекте, который владеет запущенными контейнерами.

Provisioner запускается автоматически после healthcheck Kafka, создаёт отсутствующие topics и прекращает работу с ошибкой, если существующие параметры не совпадают с декларацией translator-service. Consumer, outbox и API не стартуют до его успешного завершения. `/readyz` проверяет собственную БД, фактическое соединение с Kafka и наличие всех трёх topics; потеря broker делает сервис неготовым. Параметры broker не копируются в `.env` переводчика: совместная поставка читает их непосредственно из Kafka `.env`.

Если Kafka уже развёрнута отдельно своей поставкой, используйте `compose.remote.yml --profile bundled-database` и её существующую сеть: так переводчик подключается к одному действующему broker, а не запускает его второй экземпляр в другом Compose-проекте. Именно этот порядок применяется в тесте жизненного цикла ниже.

Runtime работает с UID/GID `10001:10001`. На Linux пароль и закрытые TLS-ключи с правами `600` должны принадлежать этому UID; каталог должен допускать проход runtime. Для файловых secrets Compose использует bind mount и не переназначает владельца атрибутами `uid`/`gid`, поэтому это проверяется на host, а не исправляется добавлением фиктивных настроек Compose ([Docker](https://docs.docker.com/reference/compose-file/services/#secrets)). Docker Desktop на macOS использует собственное отображение файловых прав; чтение секрета с правами `600` пользователем runtime проверено отдельно без раскрытия содержимого.

Для отдельно размещённой Kafka настройте в `.env` маршрутизируемые `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_BOOTSTRAP_SERVERS`, `SSL` и имена CA, сертификата и ключа, установите `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_NETWORK_EXTERNAL=false` и запустите `compose.remote.yml` с собственной локальной БД через профиль `bundled-database`. Эта точка не создаёт второй локальный broker; Kafka развёртывается своей поставкой на назначенном узле, а переводчик не проходит provisioning и readiness до фактической доступности endpoint. Текущая Kafka-поставка имеет только PLAINTEXT listener; указание `SSL` у клиента не добавляет TLS на брокере и не делает текущую пару готовой к защищённой WAN-установке.

Удалённая БД предусмотрена настройками и архитектурой, но текущий Compose не обеспечивает выход мигратора и worker за пределы сети `translator-data`: она имеет `internal: true`, а эти роли подключены только к ней. Поэтому одного изменения DATABASE_HOST и отказа от `bundled-database` недостаточно; такое размещение и несколько ячеек на разных hosts пока нельзя считать готовым рецептом. Не отключайте изоляцию вручную и не изображайте удалённую БД локальным alias: отдельная реализационная задача указана в [TASKS](TASKS.md). Команда ниже относится к отдельно размещённой Kafka и собственной локальной БД, не к распределённым вычислительным ячейкам.

```sh
docker compose -f compose.remote.yml --env-file .env config --quiet
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
| `AELEV_INFRASTRUCTURE_TRANSLATOR_IMAGE` | `aelev/translator-service:index-9b-v1` | Выбирает единый образ Python-ролей и модели; production закрепляет неизменяемый digest проверенной сборки. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_IMAGE` | `postgres:17.6-alpine` | Закрепляет поддерживаемый образ собственной PostgreSQL. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_HOST` | `translator-database` | Адрес собственной БД. Параметр допускает удалённый endpoint, но текущая internal-сеть не даёт мигратору/worker нужного выхода; ограничение описано выше. |
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
| `AELEV_INFRASTRUCTURE_TRANSLATOR_MODEL_MEMORY_LIMIT` | `8g` | Верхняя граница памяти локальной Index-Translate 9B; прежних 4 ГиБ недостаточно. Узлу нужен запас для остальных процессов. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_MODEL_CPUS` | `2` | CPU локального вычислителя. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_MODEL_BATCH_SIZE` | `1` | Размер model batch; ограничивает память и задержку. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_REQUEST_TIMEOUT_SECONDS` | `240` | Общий deadline обращения к модели. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_SEGMENT_TIMEOUT_SECONDS` | `180` | Deadline сегмента, после которого runtime перезапускается. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_ROLE_MEMORY_LIMIT` | `256m` | Память каждой лёгкой роли. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_ROLE_CPUS` | `0.25` | CPU каждой лёгкой роли. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_BIND_ADDRESS` | `127.0.0.1` | Интерфейс read-only API; loopback закрывает его извне по умолчанию. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_PORT` | `8096` | Порт API на узле. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_CONTAINER_PORT` | `8096` | Порт Uvicorn внутри контейнера. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_TRANSLATION_ENABLED` | `false` | Явно добавляет операторский POST через Kafka при `true`. При `false` маршрут и описание отсутствуют; обычная HTTPS/mTLS-диагностика не требует IdP. Только точные `true`/`false`, без скрытого значения. В текущем локальном стенде включён. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_TRANSLATION_TIMEOUT_SECONDS` | `300` | Предел ожидания операторского результата, 1–600 секунд. Timeout не отменяет уже опубликованное задание. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_TRANSLATION_MAX_IN_FLIGHT` | `4` | Число одновременно ожидающих операторских запросов в одном API-процессе, 1–16. При исчерпании — 429 до публикации; не ограничивает остальные Kafka-задания. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_NETWORK` | `aelev-infrastructure-translator-ingress` | Отдельная сеть операционного ingress. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_NETWORK_EXTERNAL` | `false` | Определяет, создаёт ли Compose сеть API или подключает существующую. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_PUBLIC_URL` | `https://localhost:18496` | Точный origin операционного API, доступный браузеру оператора; издатель добавляет собственный путь `/docs`. Удалённый доступ — HTTPS с FQDN/портом и SAN сертификата. Только явный локальный режим ниже разрешает HTTP loopback. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_HTTPS_BIND_ADDRESS` | `127.0.0.1` | Интерфейс опубликованного операторского порта. В локальном HTTP разрешён только loopback; для удалённого HTTPS задайте адрес узла либо `0.0.0.0` и ограничьте firewall. Это не адрес внутреннего HTTP. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_HTTPS_PORT` | `18496` | Операторский порт на узле в обоих режимах; должен совпадать с публичным адресом или его явным внешним маршрутом. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_HTTPS_CONTAINER_PORT` | `8443` | Отдельный операторский listener в процессе `translator-api`; протокол выбирает `API_PUBLIC_URL`, порт не может совпадать с внутренним HTTP. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_API_TLS_ROOT` | `./runtime/api-pki/api-tls` | Узкий каталог API: в HTTPS-режиме обязательны `server.crt`, `server.key`, `clients-ca.crt`; локальному HTTP/OIDC нужна только открытая CA IdP. Compose монтирует каталог только в API и запрещает создание пустой замены. Закрытые CA, операторские ключи и административные пароли в нём запрещены. Каталог должен быть вне общего `SECRET_ROOT`, чтобы другим ролям не достался серверный ключ. |

## Swagger операционного API

Документация содержит три группы в порядке `default`, `translator`, `metrics`: техническая диагностика `/healthz`, `/readyz`, `/v1/components` и `/v1/status`; только операторский `POST /v1/translate`; метрики `/metrics`. Группировка по [ADR-0110](../../../docs/adr/20261011-0110-translator-diagnostic-openapi-groups.md) не меняет ответы, права или смысл проверок: `/v1/status` показывает очередь и управление, но сам по себе не доказывает здоровье всех зависимостей. Значения полей описаны в [руководстве](USER_MANUAL.md#группы-и-операции-swagger); операторское исключение через Kafka определяет [ADR-0109](../../../docs/adr/20261011-0109-operator-translation-through-kafka.md).

Текущая группировка проверена в [отчёте диагностики](test/diagnostic-groups-result.md). Прежние [группировка](test/swagger-groups-result.md) и [проверка операторского перевода](test/operator-translation-result.md) сохранены отдельно; архивные результаты не заменяют текущий прогон.

### Локальный Swagger без клиентского сертификата

По [ADR-0108](../../../docs/adr/20261011-0108-loopback-operator-http.md) для корпоративной станции можно явно выбрать HTTP на loopback. Это не сетевой production-режим и не автоматический fallback. В `.env` задайте `ENVIRONMENT=local`, `API_PUBLIC_URL=http://127.0.0.1:18496`, `API_BIND_ADDRESS=127.0.0.1`, `API_HTTPS_BIND_ADDRESS=127.0.0.1`; все ключи имеют полный префикс `AELEV_INFRASTRUCTURE_TRANSLATOR_`. Сохранённые имена `API_HTTPS_PORT`/`API_HTTPS_CONTAINER_PORT` обозначают второй операторский порт в обоих режимах; протокол определяет только явно заданный публичный origin. HTTP запрещён вне `local`, на другом hostname и при публикации любого частного/операторского порта на широком интерфейсе. Разрешены только точные `localhost`, `127.0.0.1`, `::1`; сокращённые/числовые IP не принимаются.

| Суффикс собственного env | Назначение |
|---|---|
| `API_OIDC_ISSUER` | Точный публичный HTTPS issuer существующего realm Keycloak, например `https://127.0.0.1:18443/realms/aelev`; браузерный адрес и проверка `iss` не подменяются backchannel. |
| `API_OIDC_BACKCHANNEL_URL` | HTTPS origin IdP, доступный контейнеру для получения проверенных ключей и одноразовой подготовки. |
| `API_OIDC_CLIENT_ID` | Только собственный публичный клиент операторского API; та же строка — требуемые `aud` и `azp`, не аудитория оболочки. |
| `API_OIDC_CA_FILE` | Имя открытого файла CA IdP внутри собственного `API_TLS_ROOT`, например `identity-ca.crt`; абсолютные пути и выход из каталога запрещены. Нужен только локальному OIDC и его provisioning. |
| `API_OPERATOR_USER` | Точное имя уже существующего включённого оператора: собственная задача явно назначает отдельные client roles `operator-read` и `operator-translate`; другие пользователи не получают право перевода. Пароль не хранится в env. |

Доставьте открытую CA IdP в собственный каталог API, отдельно от закрытых CA/операторских ключей. Для уже подготовленной локальной установки можно скопировать свою CA из `secrets/status/identity-ca.crt` в `runtime/api-pki/api-tls/identity-ca.crt`. Если локальный режим готовится первым, создайте только каталог `API_TLS_ROOT` и доставьте туда CA IdP: серверные TLS-файлы этому режиму не требуются. Compose монтирует в API только этот узкий каталог, а в задачу подготовки — только CA и собственные `status-admin/{admin-user,admin-password}`. В каталог API нельзя класть ключ CA, операторские удостоверения или административные пароли. IdP остаётся HTTPS с проверкой CA/SAN; политика корпоративного браузера и его доверие не меняются.

Из этого каталога, после сборки текущего собственного образа, доставки CA и настройки env:

```sh
docker compose -f compose.remote.yml --env-file .env --profile provision run --rm --no-deps translator-api-provision
docker compose -f compose.remote.yml --env-file .env --profile bundled-database --profile ui up -d --no-deps translator-api translator-service-status-publisher
curl --fail http://127.0.0.1:18496/docs
curl --silent --output /dev/null --write-out '%{http_code}\n' http://127.0.0.1:18496/healthz
```

Последняя проба должна вернуть `401`. На `/docs` нажмите `Authorize`, затем `Authorize` в окне OAuth и войдите своим пользователем Keycloak; Swagger выполняет Authorization Code с PKCE S256 и точным `/docs/oauth2-redirect.html`. После входа `Try it out` → `Execute` для `GET /healthz` должен дать `200`. Остальные операции также требуют собственный access token: чужая аудитория/подпись/срок — `401`, отсутствие `operator-read` — `403`, недоступное доверие IdP — отказ. Статические файлы и OpenAPI публичны, технические ответы — нет. Токен не сохраняется после перезагрузки и не передаётся оболочке; все файлы Swagger/возврата обслуживаются локально, без CDN.

Для публикации HTTP-ссылки сначала обновите API и образ оболочки, затем увеличьте `UI_DESCRIPTION_REVISION`, сохранив UUID и журнал. Исторический переход на HTTP использовал ревизию 4; действующий шаблон после Index 9B использует 5. Для удалённого сервера loopback-ссылка непригодна: она открыла бы компьютер браузера, а не сервер. Задайте его доступный HTTPS origin и обычные удостоверения по следующему разделу. При откате сначала опубликуйте HTTPS в большей ревизии совместимым издателем, затем возвращайте предыдущие образы; данные и sequence не удаляются.

### HTTPS/mTLS для сетевого доступа

Этот раздел применяется только к HTTPS-режиму. На корпоративной станции с запретом установки удостоверений используйте разрешённый выше локальный режим, не изменяйте системное доверие.

`translator-api` обслуживает два listener в одном контейнере: прежний частный HTTP для собственных проверок и HTTPS/mTLS для оператора. `/docs` показывает пять операций чтения и, при `API_TRANSLATION_ENABLED=true`, операторский `POST /v1/translate`, не приватные POST модели. Чтение сохраняет прежнее mTLS-разрешение; включённый POST дополнительно требует собственный OIDC и `operator-translate`. Только для включённого перевода доставьте открытую CA IdP в `API_TLS_ROOT`, настройте `API_OIDC_*` и пределы перевода также в HTTPS-режиме; при `false` запуск не требует IdP. `/openapi.json` генерируется из обработчиков. При отсутствии обязательного для выбранного режима TLS/OIDC-файла, недействительной конфигурации или завершении любого listener весь API прекращает работу; plaintext fallback отсутствует. Штатные SIGTERM/SIGINT завершают оба listener. Внутренний host-порт разрешён только на loopback, его прежние пути и ответы сохранены.

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

Запрос без клиентского удостоверения либо с чужой CA отвергается на TLS до HTTP; `--insecure` не является порядком запуска. После включения профиля `ui` собственный издатель публикует `/docs` для группы «Перевод текстов» и компонента «Операционный API»; первая HTTPS-ссылка появилась в исторической ревизии 3. Другие компоненты ссылку не наследуют. UUID и журнал остаются прежними; изменение публичного адреса требует большей ревизии по [контракту ссылок](../../../docs/api/platform-ui-injection.md#ссылки-на-собственные-интерфейсы). При откате сначала публикуйте описание без ссылки в ревизии выше любой уже принятой, затем меняйте образ; старую ревизию и сброс тома не используйте.

## Масштабирование и географическое размещение

Единица вычислительного масштабирования по ADR-0096 — пара `translator-model` + `translator-worker` с локальным socket volume и подключением к одной принадлежащей переводчику БД. Unix socket и model volume между узлами не разделяются. Consumer масштабируются не выше числа partitions. `translator-outbox` остаётся одним активным экземпляром до появления отдельного механизма fencing. Текущая поставка запускает одну ячейку; удалённые ячейки требуют устранения указанного выше ограничения выхода к БД и отдельного теста. Полный up `compose.remote.yml` на каждом дополнительном узле нельзя использовать как команду масштабирования: он создаст также consumer/API/outbox, а не только вычислительную пару.

Частный API сохраняет только `GET /healthz`, `GET /readyz`, `GET /v1/status`, `GET /v1/components`, `GET /metrics`. Операторский listener дополнительно предоставляет ограниченный POST ниже; PUT, DELETE, административных HTTP-команд и чтения чужих результатов нет. Межсервисный перевод по-прежнему использует только Kafka.

## Операторский перевод

В собственном `.env` явно установите `AELEV_INFRASTRUCTURE_TRANSLATOR_API_TRANSLATION_ENABLED=true`: шаблон поставки оставляет его `false`, чтобы обычный Kafka-перевод и HTTPS/mTLS-диагностика не получили обязательную зависимость от IdP. После настройки и provisioning ниже POST появится только на операторском listener. Для отключения верните `false` и адресно пересоздайте API; уже принятые задания не отменяются. Локальные диагностические GET по HTTP продолжают требовать `operator-read` в обоих случаях.

Схема запроса, ответы и границы задаются [контрактом](../../../docs/api/translation.md#операторский-перевод), пример Swagger — в [руководстве](USER_MANUAL.md#операторский-перевод). Для обновления существующей поставки добавьте в свой `.env` обязательные `AELEV_INFRASTRUCTURE_TRANSLATOR_API_TRANSLATION_TIMEOUT_SECONDS=300` и `AELEV_INFRASTRUCTURE_TRANSLATOR_API_TRANSLATION_MAX_IN_FLIGHT=4`; настройте существующие `API_OIDC_*`, открытую CA IdP и точного `API_OPERATOR_USER`. Сертификат HTTPS сам по себе не даёт право перевода.

Из каталога сервиса, при уже работающих собственных Kafka/БД/ролях:

```sh
docker compose -f compose.remote.yml --env-file .env build translator-api
docker compose -f compose.remote.yml --env-file .env --profile provision run --rm --no-deps translator-api-provision
docker compose -f compose.remote.yml --env-file .env up -d --no-deps --no-build --wait translator-api
```

Существующая одноразовая задача идемпотентно создаёт два разных права и назначает их только явно указанному существующему оператору. Пользователь только с `operator-read` получает 403 на POST; машинный издатель состояния не получает право перевода. Runtime не получает административные секреты. API публикует валидный запрос в выбранный topic, не пишет задание напрямую и не вызывает модель; возвращает только свой точный результат после Kafka ACK outbox. Не создаются новые таблицы, topics, consumer groups или постоянные контейнеры. Для отката отзовите `operator-translate` и верните прежний API-образ, не стирая уже принятые задания.

## Остановка, резервная копия и восстановление

Остановка процессов не удаляет задания, результаты или Kafka offsets. Для обслуживания сначала используйте PAUSE и дождитесь завершения активных leases по [руководству](USER_MANUAL.md#управление-выдачей-заданий); затем остановите собственные consumer, worker, outbox, model, API и издателя. БД оставьте доступной на время логического backup. Если контейнеры запущены корневым Compose, адресные команды выполняйте через него. В совместном самостоятельном проекте общий `down` остановит также включённую Kafka: для обслуживания только переводчика перечисляйте его роли, не весь проект. `down --volumes` не является штатным обслуживанием.

Пример согласованного логического backup собственной встроенной БД из каталога сервиса, когда контейнеры принадлежат этому самостоятельному проекту:

```sh
umask 077
TRANSLATOR_BACKUP_DIR=$(mktemp -d)
docker compose --env-file .env exec -T translator-database sh -c \
  'pg_dump --format=custom --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  > "$TRANSLATOR_BACKUP_DIR/translator.dump"
```

Проверьте успешный код `pg_dump` до использования файла. Backup содержит исходные тексты и переводы: перенесите его из временного каталога в защищённое хранилище с независимой копией вне узла; временный каталог не является долгосрочным backup. Файл не должен попадать в Git или build context. Сохраните вместе с ним точный образ/digest, `translator.lock.json`, артефакт контрактов, настройки и отдельно защищённые удостоверения. Журнал собственного издателя сохраняйте согласованно при остановленном издателе; один dump БД его не заменяет.

Восстановите dump через `pg_restore --exit-on-error --no-owner` в новую отдельную БД, принадлежащую проверке восстановления, а не поверх рабочей. Создайте её роль заранее и укажите только её подключение/пароль в отдельном env проверки. Не запускайте consumer, worker, outbox или migrator против восстановленной копии до проверки; сеть проверки не должна иметь доступ к рабочим topics. В том же закреплённом Python-образе с этим изолированным подключением выполните `python -m translator_service.runtime verify-restored-state`: проверка возвращает `status=VERIFIED` и число заданий, сверяя исходные digest, события, результаты и точные байты outbox без публикации или правки данных. Она не заменяет проверку восстановления модели, Kafka и удостоверений.

Рабочее переключение выполняется только после прекращения прежних писателей и проверки копии; consumer groups/offsets и имена topics не сбрасываются. Для продолжения выдачи используйте RESUME с новой ревизией управления. Порядок смены модели и отката описан ниже; новый образ не разрешает переписать идентификаторы старых результатов. Непроверенные режимы отмечены в [TASKS](TASKS.md).

## Сборка и проверки

[`test/index_model.py`](test/index_model.py) проверяет установленную 9B на уже работающих канонических Kafka и собственной PostgreSQL: обычную/приоритетную очередь, повтор без вычисления, конец длинного текста, неподдерживаемый язык и сохранность задания при перезапуске модели. Это изменяющий локальный тест: он требует пустые собственные очереди/таблицы до начала и явный флаг; после проверки обрезает только доказанно созданный им префикс трёх принадлежащих переводчику topics через отдельную административную роль и удаляет свои SQL-строки по UUID/digest. Topics, volumes, identities и чужие ресурсы сохраняются, собственные роли возвращаются в работу. Неожиданные чужие записи блокируют очистку, а не разрешают их удаление.

```sh
python3 test/index_model.py --allow-restart-and-clean
```

Этот изменяющий тест адресует самостоятельные проекты из сервисных env. Не запускайте его против работающей корневой группы: сначала подготовьте отдельное согласованное окно проверки и условия владения по самому тесту. Для текущей установки используйте уже сохранённые отчёты; чтение документации не разрешает перезапуск модели или очистку очередей.

Результаты установленной 9B: [Kafka-проверка](test/index-model-result.md) и соседний JSON, [SQL-регрессии](test/index-sql-result.md), [Swagger/OIDC](test/index-swagger-result.md) и [сводка перехода](test/index-validation-result.md). Исторические отчёты прежней модели не являются доказательством нового выпуска.

### Сравнение моделей и обновление весов

Действующий выпуск — `IndexTeam/Index-Translate-9B-GGUF`, Q4_K_M, Apache-2.0. Веса, нативная ревизия и профиль `index-plain-v1` закреплены в [`translator.lock.json`](translator.lock.json). Образ проверяет размер и SHA-256 при сборке, вычислитель — при старте; подмена профиля без нового `translator_ref` также закрывает запуск. Канонический идентификатор выбранного выпуска находится в этом lock, а не в дополнительной env-переменной. Операторский POST использует его автоматически; Kafka-клиент обновляет собственную настройку точного идентификатора. Старый идентификатор не переименовывается и не принимает новую модель молча.

Сборочная задача [`download-model.py`](download-model.py) читает тот же lock, получает только официальный закреплённый артефакт диапазонами с ограниченным повтором и проверяет весь собранный файл. Кеш частей ускоряет повтор оборванной сборки, но не заменяет финальную проверку. Загрузчик и его кеш не доставляются рабочему вычислителю; сетевой доступ остаётся только этапом сборки.

Вычислитель запускает свой `llama.cpp` как дочерний процесс в том же `network none` контейнере. Его loopback недоступен другим контейнерам и браузеру; worker использует только прежний приватный socket. Закреплены два потока, контекст 2048, бюджет ответа 1024 токена, температура 0, seed и отключённые рассуждения/кэш контекста. Полный текст разбивается на фрагменты, при переполнении или обрезанном ответе фрагмент уменьшается. Timeout не считается готовым переводом: процесс прекращается, а очередь повторяет задание. Общий deadline 240 секунд не гарантирует перевод любого текста длиной 12 000 символов за это время.

Заявленный поставщиком каталог включает 150 языков, но локально оценены только направления сравнительного корпуса. Коды `en`, `de`, `ru`, `ja`, `zh` разрешаются явно, для вариантов письма есть точные коды, например `sr-latn` и `sr-cyrl`. Неизвестный язык не угадывается. Полный собственный каталог и допустимые псевдонимы находятся в [`index_languages.py`](src/translator_service/index_languages.py); качество непроверенных направлений не обещается.

Оператор явно выбрал 9B после сравнения и разрешил не сохранять старые образы/переводы. Это отдельное разрешение на локальную очистку, не новая общая политика удаления. Прежний вычислитель и lock доступны в истории Git и не входят в сборку; локальный архив старой реализации удалён по отдельному запросу оператора. Издатель состояния показывает Index-Translate 9B; изменение описания требует большей `UI_DESCRIPTION_REVISION` без сброса UUID и журнала.

Отдельный эксперимент MADLAD / Index-Translate 2B / Index-Translate 9B принадлежит этому сервису: [сценарий, методика и команды](test/model_comparison/README.md). Он не переключает действующую модель, не обращается к рабочим Kafka/БД и не изменяет `translator.lock.json`; исходные переводы и измерения сохраняются рядом с тестом. Сборка отдельного CPU-движка для кандидатов сохраняет Python 3.13.7 и Debian Bookworm, не входит в обычную поставку.

[Завершённая локальная оценка](test/model_comparison/result.md) содержит по 40 переводов всех трёх моделей, измерения ресурсов и смысловые ошибки, включая случаи, которые не обнаруживают проверки чисел и идентификаторов. Для 9B по разрешению оператора временно останавливались только собственные model/worker, затем восстановлены те же контейнеры; такой режим явно выбирается в методике, не происходит автоматически при нехватке памяти. После оценки оператор отдельно разрешил замену MADLAD по ADR-0112; исторический отчёт не является проверкой новой установленной поставки.

Рабочие веса сейчас не обновляются автоматически. `translator.lock.json` закрепляет ревизию поставщика, размер и SHA-256 каждого файла, Dockerfile получает те же неизменяемые артефакты, а offline runtime проверяет их перед загрузкой. Пересборка сама по себе не означает получение свежей модели. Автоматического отслеживания выпусков поставщика и периодической смысловой переоценки пока нет.

Обновление требует отдельного кандидата и отчёта на неизменном корпусе, проверки лицензии, языков, смысла, ресурсов, совместимости и восстановления. После отдельного решения обновляются согласованные модельный lock и рецепт сборки, выпускается новый неизменяемый образ с новым `translator_ref`, затем проверяется переход через настоящие Kafka и собственную БД. По умолчанию результаты прежнего выпуска сохраняются без переписывания идентификаторов; удаление или отказ от локального образа для отката требуют отдельного разрешения, как в данном переходе. Смена архитектуры требует своей реализации и проверки; просто подставить GGUF Index вместо T5-весов MADLAD нельзя.

Для повторения живого перевода добавьте `--translate` к команде локального Swagger ниже; без флага проверка остаётся только читающей. Тест использует настроенного оператора и рабочую модель, поэтому учебные задания сохраняются по штатной политике. Текущий отчёт отдельно оценивает работоспособность пути и смысловую точность результата.

```sh
docker build --build-context translator_tests=./test --target test -t aelev/translator-service:test .
docker run --rm --network none aelev/translator-service:test
docker run --rm --network none aelev/translator-service:test poetry run ruff check src test alembic
docker run --rm --network none aelev/translator-service:test poetry run pyright src test
python3 test/test_configuration.py
```

Проверки Swagger используют работающие API и оболочку; по умолчанию выполняют только чтение и не создают переводческих заданий или Docker-ресурсов. Явный `--translate` дополнительно выполняет настоящий POST в каждой очереди и проверяет собственную БД: 100/0, `SUCCEEDED`, outbox `PUBLISHED`. Два учебных задания и их результаты сохраняются по штатной политике, рабочие Kafka-журналы ради очистки не удаляются. В операторском окружении требуются Playwright 1.56.0 и установленный Chromium; пароль существующего оператора передаётся только файлом. Для явно выбранного локального HTTP/OIDC выполните из каталога сервиса:

```sh
python3 test/swagger_local.py \
  --chromium <путь-к-установленному-Chromium> \
  --ui-url https://<адрес-оболочки>:<порт> \
  --viewer-password-file <файл-пароля>
```

Только для проверенной локальной PKI IdP/оболочки на loopback разрешён тестовый флаг `--allow-local-idp-certificate`: он относится к браузеру теста, не настройкам компьютера, не проверке TLS API→IdP и не удалённому HTTPS. Swagger не получает клиентский сертификат. Проверяются настоящий вход PKCE, пять ответов `401` до входа/`200` после входа, `Execute`, отсутствие сохранённого токена и настоящая ссылка оболочки. [Результат браузерной проверки](test/swagger-local-result.md), [снимок](test/swagger-local.png) и [сводка проверок](test/local-http-validation-result.md).

Для прежнего HTTPS/mTLS-режима:

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

[`test/lifecycle.py`](test/lifecycle.py) проверяет канонические поставки: Kafka из `../kafka/compose.yml`, переводчик из `compose.remote.yml` с собственной PostgreSQL и выбранной моделью из lock. Используются рабочие `.env`, секреты и имена проектов; отдельные тестовые broker, БД, модели или конфигурации не создаются. Исторический полный прогон с MADLAD проверил оба инициализатора, приоритетную и обычную очереди, повтор без вычисления, сохранность после полного перезапуска, неготовность при отказе Kafka и доставку outbox после восстановления; его отчёт не подтверждает установленную Index-Translate 9B.

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

Итоговый отчёт — [`test/validation-result.md`](test/validation-result.md): полный жизненный цикл на реальных компонентах пройден, но обнаружена смысловая добавка в переводе MADLAD, поэтому качество перевода не считается подтверждённым. Читаемый отчёт базового набора — [`test/pytest-result.md`](test/pytest-result.md), регрессии повторного provisioning — [`test/provisioner-regression.md`](test/provisioner-regression.md). Конфигурационные проверки выполняются на хосте, поскольку test-образ не содержит Docker CLI. Изолированные SQL-тесты в CI требуют `AELEV_TRANSLATOR_TEST_DATABASE_URL` и одноразовой базы `translator_test` с миграциями; без неё pytest явно отмечает пропуск. Их нельзя направлять на рабочую БД: порядок подготовки закреплён в [сервисном CI](../../../.github/workflows/translator-service-validation.yml). Для собственной локальной PostgreSQL добавлен `test/sql_operator.py`: он проверяет режим, создаёт новую уникальную базу, применяет миграции, выполняет SQL-тесты и в `finally` удаляет только созданную базу с проверкой удаления. [SQL-результат](test/sql-operator-result.md) отделён от [операторского перевода](test/operator-translation-result.md). Такие проверки не заменяют полный жизненный цикл, а текущий локальный прогон не подтверждает удалённые TLS/mTLS, физически разнесённые узлы или нагрузочные пределы.

Локальный SQL-запуск после сборки test-образа и при уже работающей собственной БД; сеть в примере соответствует шаблону `.env`, при изменении `DATABASE_NETWORK` укажите своё значение:

```sh
docker run --rm --network aelev-infrastructure-translator-data --env-file .env \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --mount type=bind,src="$(pwd)/secrets/postgres-password",dst=/run/secrets/translator-database-password,readonly \
  --mount type=bind,src="$(pwd)/test",dst=/opt/aelev/test \
  aelev/translator-service:test python test/sql_operator.py
```

`contracts/translation-v1.json` генерируется из общего канонического каталога. Исторические рецепты удалены из текущего дерева; действующая сборка содержит только выбранную реализацию.

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

Транспорт издателя читает `UI_SECRET_ROOT/{shell-ca.crt,identity-ca.crt,publisher.crt,publisher.key,client-secret}`. Для одноразового provision нужны отдельные `UI_ADMIN_ROOT/{admin-user,admin-password}`; чтобы они действительно не были видны рабочим ролям через общий SECRET_ROOT, задайте UI_ADMIN_ROOT вне него, например `./runtime/status-admin`. Текущий вложенный путь шаблона и ограничения mounts описаны в [разделе секретов](#секреты-получение-и-подготовка). Закрытые CA не доставляются в runtime. Используйте утверждённые цепочки CA, SAN/EKU и ротацию; локальная генерация не заменяет production PKI/SVID. HTTPS-адреса могут находиться в разных странах; общей Docker-сети с UI/IdP нет. `host.docker.internal` и `keycloak:host-gateway` — только локальные alias: для удалённой установки задайте реальные FQDN/порты и доступность сети. Проверка сертификатов не отключается.

| Переменная | Назначение |
|---|---|
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_URL` | HTTPS-адрес платформенного технического API. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_IDENTITY_URL` | HTTPS-адрес IdP; должен совпадать с SAN сертификата. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_REALM` | Realm собственной машинной identity. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_CLIENT_ID` | Client ID только собственной роли публикации. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_AUDIENCE` | Аудитория JWT платформенного API. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_MODULE_ID` | Постоянный UUID собственного описания. |
| `AELEV_INFRASTRUCTURE_TRANSLATOR_UI_DESCRIPTION_REVISION` | Положительная ревизия описания; текущий шаблон Index 9B использует 5. При изменении публичного адреса/состава увеличьте её относительно всех ранее принятых ревизий, сохранив UUID и журнал; исходники для переноса endpoint менять не требуется. |
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
