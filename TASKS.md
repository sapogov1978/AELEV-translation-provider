# translator-service: работа и ворота поставки

Архитектурная истина — [SPEC](SPEC.md), а не этот список.

Актуальный результат изолированных проверок сохранён в [test/production-readiness-result.md](test/production-readiness-result.md).

- [x] Собственные исходники выбранного вычислителя, модельный/Poetry lock, Dockerfile, `compose.yml` и `.env.example`; корневой инфраструктурный Compose только оркестрирует ту же поставку. Прежний MADLAD/Cargo архивирован по ADR-0112.
- [x] Независимая поставка по ADR-0096 с собственной PostgreSQL, живым `.env`, вычислительными ячейками и без списка клиентов.
- [x] Явная Kafka-зависимость по ADR-0097: обычный Compose поднимает каноническую Kafka, распределённый Compose не создаёт локальный broker, а provisioning и readiness проверяют реальный endpoint.
- [x] Один `TranslationRequested v1` из `shared/contracts` для обычного и приоритетного topics, совместимое добавление `TRANSLATE_TEXT` и отдельный topic provisioner владельца.
- [x] Собственная миграция, идемпотентный вход, ограждённый lease, транзакционный результат/outbox и повтор без вычисления.
- [x] Kafka v2 по ADR-0124 без выбора или раскрытия исполнителя клиенту; внутренняя запись исполнения каждой попытки, возможность изменившегося перевода после обновления, совместимый приём v1 на период миграции.
- [x] Упрощённая поставка с двумя Compose-файлами; 40 конфигурационных и модульных/SQL-проверок без пропусков, Ruff и Pyright. [Фактический отчёт](test/validation-result.md) и [отчёт базовых проверок](test/pytest-result.md) сохранены в сервисном `test`.
- [x] Историческая поставка MADLAD: полный runtime и [тест жизненного цикла](test/lifecycle.py) на реальных поставках Kafka/переводчика прошли 110 этапов, включая оба инициализатора, обе очереди, повтор без вычисления, полный перезапуск, восстановление outbox и очистку; [читаемый результат](test/lifecycle-result.md) и обе описи сохранены. Этот прогон не подтверждает новую модель.
- [x] Index-Translate 9B установлена по ADR-0112: полные проверенные веса, закреплённый нативный вычислитель, 192 модульные проверки, отдельные Compose/SQL-проверки, [живой Kafka-прогон](test/index-model-result.md) и [Swagger/OIDC](test/index-swagger-result.md). Собственные тестовые сообщения/строки и старые runtime-образы удалены; [сводка](test/index-validation-result.md).
- [x] Безопасность очистки: восемь модульных проверок, отказ поверх существующих данных, удаление только созданных контейнеров, сетей, именованных и анонимных volumes с подтверждённым владением, сверка всех исходных ресурсов; [очистка после намеренной ошибки](test/lifecycle-failure-cleanup-result.md) также прошла. [Остатки старых прогонов](test/legacy-cleanup-result.md) удалены адресно.
- [x] Регрессия повторного provisioning существующих topics: пустой список не передаётся в `AdminClient.create_topics`, но параметры всех topics по-прежнему проверяются; [отчёт](test/provisioner-regression.md).
- [x] Длинный текст детерминированно делится на ограниченные сегменты; точный источник/digest, execution и готовый результат каждого сегмента сохраняются в PostgreSQL. Повтор после timeout/lease продолжает с совместимых checkpoints, а смена исполнения закрыто очищает несовместимые промежуточные результаты.
- [x] Собственные OTLP logs и transport/process/publish traces сохраняют `traceparent` и поступают через mTLS telemetry sender с постоянным журналом; production без endpoint и identity закрыто не запускается.
- [x] Runtime Kafka, deployment Kafka, database, telemetry и status-admin credentials имеют разные mounts; рабочие роли не видят Kafka-admin или OIDC-admin файлы.
- [x] Внешняя PostgreSQL доступна через явно не-internal data network и только с `sslmode=verify-full`, CA, client certificate и key; local по умолчанию сохраняет internal network и собственную БД.
- [ ] Продолжать проверку смысловой точности общего перевода как эксплуатационный benchmark, не как обещание безошибочности модели: прежний MADLAD добавлял отсутствующую страну к `central bank`; оператор выбрал Index-Translate 9B после [сравнения](test/model_comparison/result.md) по ADR-0112, где также зафиксированы отдельные смысловые добавки 9B.
- [x] Собственные PAUSE/RESUME/RESET и read-only проверка восстановленного состояния.
- [x] Измеренная рабочая проверка выделения и сохранения локализаций, с отдельной фиксацией незавершённых длинных переводов в [историческом отчёте](https://github.com/sapogov1978/aelev/blob/d724c563053717ec84ef6fdb842fe873623c956c/services/infrastructure/translator-service/obsolete/LOCAL_VALIDATION.md).
- [ ] На целевой платформе проверить SPIFFE/mTLS/ACL, защищённые подписи образа, реальную доставку alert и независимые failure-domain backup/restore; это допуск развёртывания, не отсутствующая функция продукта.
- [ ] На целевой платформе измерить несколько вычислительных ячеек на разных hosts без размножения активного outbox и без межузлового Unix socket.
