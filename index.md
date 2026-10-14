# translator-service: карта каталога

| Что искать | Где находится |
|---|---|
| Назначение, состав и быстрый запуск | [README.md](README.md) |
| Нормативные гарантии | [SPEC.md](SPEC.md) |
| Установка, Swagger, управление и восстановление | [USER_MANUAL.md](USER_MANUAL.md) |
| Все HTTP endpoints и права | [ENDPOINTS.md](ENDPOINTS.md) |
| Незавершённые работы | [TASKS.md](TASKS.md) |
| История изменений | [CHANGELOG.md](CHANGELOG.md) |
| Backend и миграции | `src/translator_service/`, `alembic/` |
| Телеметрия владельца | `src/translator_service/observability.py`, `observability/` |
| Локальная и удалённая топологии | `compose.local.yml`, `compose.remote.yml`, `compose.yml` |
| Закреплённая модель | `translator.lock.json`, `download-model.py` |
| Проверки и сравнение моделей | [актуальная проверка готовности](test/production-readiness-result.md), `test/` |

Kafka-контракт находится в [docs/api/translation.md](../../../docs/api/translation.md), инфраструктурная классификация — в [ADR-0087](../../../docs/adr/20261008-0087-infrastructure-translator-service.md).
