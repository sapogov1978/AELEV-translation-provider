# Translator Service

Вспомогательный сервис перевода текстов локальной моделью Index-Translate 9B. Запросы и результаты передаются через Kafka; сервис не знает предметной области заказчика.

## Основные возможности

- Обычная и приоритетная очереди.
- Сохранение попыток и исходного порядка заданий при повторах.
- Устойчивая публикация результатов.
- Диагностика и управление через операторский API.
- Собственные метрики, журналы и трассы.

## Запуск

После подготовки по [руководству](USER_MANUAL.md), из этого каталога:

```sh
docker compose --env-file .env config --quiet
docker compose --env-file .env up --build -d --wait --wait-timeout 600
```

Для удалённого Kafka используется `compose.remote.yml`. Не запускайте самостоятельный проект поверх томов общего инфраструктурного проекта.

## Навигация

- [src/](src/), [alembic/](alembic/) — реализация и миграции.
- [translator.lock.json](translator.lock.json) — выбранная модель.
- [USER_MANUAL.md](USER_MANUAL.md), [SPEC.md](SPEC.md), [ENDPOINTS.md](ENDPOINTS.md) — эксплуатация, поведение и API.
- [test/](test/), [secrets/](secrets/README.md) — проверки и описание секретов.
- [index.md](index.md), [TASKS.md](TASKS.md), [CHANGELOG.md](CHANGELOG.md) — карта, готовность и история.
