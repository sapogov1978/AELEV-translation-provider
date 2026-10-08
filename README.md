# translator-service

Общий вспомогательный компонент инфраструктуры для перевода политик и сохранённых страниц для оператора. MADLAD, Rust runtime, веса и техническая очередь не принадлежат base-screening. Компонент не фильтрует сайты и не меняет человеческие решения. [SPEC](SPEC.md) содержит нормативное поведение, [руководство](USER_MANUAL.md) — управление и диагностику; [ADR-0087](../../../docs/adr/20261008-0087-infrastructure-translator-service.md) определяет размещение, а [публичный Kafka-контракт](../../../docs/api/translation.md) — внешнюю границу.

[Рабочая проверка](LOCAL_VALIDATION.md) содержит реальные Kafka-запросы, времена, сохранность данных и выявленные ограничения модели; успешная доставка не является доказательством качества перевода.

## Сборка компонента

Все команды ниже выполняются из каталога `services/infrastructure/translator-service`. Исходники и образы прикладных потребителей не используются. `contracts/translation-v1.json` — автоматически экспортированный закреплённый артефакт публичных схем; источник и процедура переиздания описаны в контракте.

```sh
docker build --target test -t aelev/translator-service:test .
docker run --rm --network none aelev/translator-service:test
docker run --rm --network none aelev/translator-service:test poetry run ruff check src tests alembic
docker run --rm --network none aelev/translator-service:test poetry run pyright src
docker run --rm --network none aelev/translator-service:test poetry run pyright tests
docker build --target translator-runtime -t aelev/translator-service:local .
```

Сборка runtime загружает только точные файлы модели с проверкой SHA-256. Для уже сохранённых артефактов можно исключить повторную загрузку:

```sh
docker build --build-context translator_model=/absolute/path/to/verified/model \
  --target translator-runtime-local-artifacts -t aelev/translator-service:local .
```

Для изменения только собственных исходников после полной проверенной сборки можно использовать `Dockerfile.runtime-patch` с `AELEV_TRANSLATOR_RUNTIME_BASE`, указывающим исключительно на ранее проверенный образ этого же сервиса. Зависимости, ОС и веса сохраняются; этот быстрый рецепт не заменяет независимую первоначальную сборку.

## Запуск

Активная поставка находится в этом каталоге: `compose.yml` определяет только роли переводчика, а `.env.example` перечисляет его собственные настройки. Скопируйте шаблон в закрытый `.env`, задайте полный `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_URL`, Kafka bootstrap servers и TLS-параметры. URL может указывать на отдельный удалённый PostgreSQL; для подключения к уже созданным локальным сетям установите `AELEV_INFRASTRUCTURE_TRANSLATOR_NETWORKS_EXTERNAL=true`, а при удалённых endpoints оставьте `false`, чтобы Compose создал собственные bridge-сети. Общий локальный запуск дополнительно доступен через корневой инфраструктурный агрегатор. Прикладной владелец может сохранять запросы, пока переводчик выключен.

```sh
docker compose --env-file .env up -d --no-build
docker compose --env-file .env run --rm --no-deps translator-consumer \
  python -m translator_service.runtime status
```

Роли: `translator-consumer` сохраняет Kafka-вход, `translator-worker` выполняет одно задание, `translator-model` владеет единственным offline вычислителем, `translator-outbox` публикует результаты, `translator-migrator` применяет собственную миграцию. Тяжёлый вычислитель по умолчанию ограничен 4 ГиБ и 2 CPU. Внутренний socket не является публичным API и не монтируется в прикладные сервисы. Масштабирование лёгких работников не создаёт новых копий модели.

Для production обязательны `AELEV_INFRASTRUCTURE_TRANSLATOR_KAFKA_SECURITY_PROTOCOL=SSL`, точные пути клиентского сертификата, ключа и CA, TLS PostgreSQL, отдельные workload identity и ACL: consumer читает только requests и собственную группу, outbox пишет только results. Локальный запуск не доказывает production admission.

## Пауза и перезапуск

Сначала прочитайте текущую ревизию через `status`. Команды сохраняют актор и причину; повтор с тем же телом идемпотентен. Вместо PAUSE можно передать RESUME или RESET. RESET выполняется после завершения активных единиц, сохраняет готовые результаты и всю историю.

```sh
docker compose --env-file .env run --rm --no-deps translator-consumer \
  python -m translator_service.runtime control --action PAUSE \
  --command-id translation-maintenance-1 --actor operator \
  --expected-revision 1 --rationale planned-maintenance
```

## PostgreSQL-проверки и восстановление

В пустой изолированной PostgreSQL-базе примените `alembic upgrade head` с внутренней runtime-переменной `AELEV_TRANSLATOR_DATABASE_URL`, затем выполните тесты с `AELEV_TRANSLATOR_TEST_DATABASE_URL` того же изолированного экземпляра. Compose получает первое значение из `AELEV_INFRASTRUCTURE_TRANSLATOR_DATABASE_URL`; прямые runtime-переменные не являются интерфейсом `.env.example`. Тесты используют только собственные таблицы и очищают только тестовые данные; рабочий URL для них запрещён.

```sh
poetry run alembic upgrade head
poetry run pytest -q
poetry run python -m translator_service.runtime verify-restored-state
```

Снимок собственного хранилища создаётся штатным инфраструктурным `pg_dump` в закрытом канале секретов, восстанавливается в отдельной БД и проверяется без Kafka-доступа. Сохраняются digest схем и модели. Проверяющая команда не исправляет данные и не публикует события. После успешной проверки очередь может продолжить незавершённые задания; повтор исходного запроса вернёт точный готовый результат.

`obsolete/` хранит прежние рецепты Base Screening, монолитную конфигурацию и provisioning для воспроизводимости истории; они не входят в runtime, активную поставку или тестовую матрицу компонента.
