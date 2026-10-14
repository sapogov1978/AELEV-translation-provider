# translator-service

translator-service — общий вспомогательный инфраструктурный компонент для технического перевода текста. Клиенты публикуют независимые запросы в обычную или приоритетную Kafka-очередь; сервис сам выбирает текущее исполнение, сохраняет попытки в собственной PostgreSQL и публикует результат без знания заказчика или предметной области. Операторский HTTP использует тот же Kafka-путь и не является межсервисным обходом.

**Состояние:** `PRODUCTION_READY` по [реестру готовности](../../../docs/architecture/19-services-readiness.md). Длинные задания продолжаются с устойчивых сегментных checkpoints, transport traces и logs идут через собственный telemetry sender, runtime/deployment identities разделены, а удалённая PostgreSQL поддерживается только с `sslmode=verify-full`; смысловая оценка конкретных переводов остаётся обязанностью владельца локализации.

## Из чего состоит

| Часть | Назначение |
|---|---|
| два `consumer` | Приоритетный и обычный приём `TranslationRequestedV2` |
| `worker` и `translator-model` | Ограждённая попытка и локальное исполнение Index-Translate 9B |
| `outbox` | Публикация `TranslationCompletedV2` |
| `translator-api` | Диагностика, управление процессами и разрешённый операторский перевод |
| `migrator` и `topic-provisioner` | Схема собственной БД и topics контракта |
| `status-publisher` | Публикация собственного состояния в Platform UI |
| `telemetry-sender` | Устойчивый журнал и доставка собственных logs, traces и metrics |

## Быстрый локальный запуск

Из этого каталога подготовьте `.env`, файловый пароль, модель и выбранный TLS/OIDC-режим по [руководству](USER_MANUAL.md), затем выполните:

```sh
docker compose --env-file .env config --quiet
docker compose --env-file .env up --build -d --wait --wait-timeout 600
docker compose --env-file .env ps
```

Обычный локальный рецепт включает каноническую Kafka-поставку; для уже существующего удалённого broker используется `compose.remote.yml`. Не запускайте самостоятельный проект поверх томов, которыми уже владеет корневая инфраструктурная оркестрация.

## Документация

Карта каталога — [index.md](index.md), нормативная граница — [SPEC](SPEC.md), установка и эксплуатация — [USER_MANUAL](USER_MANUAL.md), HTTP — [ENDPOINTS](ENDPOINTS.md), Kafka-контракт — [translation API](../../../docs/api/translation.md), незавершённые работы — [TASKS](TASKS.md), история — [CHANGELOG](CHANGELOG.md).
