# 00-PROVIDER-20261113-0003 — Независимый сетевой транспорт перевода

- **Статус:** Принят по подтверждению владельца от 2026-11-13
- **Дата:** 2026-11-13
- **Частично заменяет:** ADR-0001 только в обязательности UDS и запрете сетевого listener; ADR-0002, opaque v1 и владение реализацией сохраняются

## Контекст

Translator worker и provider могут находиться на разных физических компьютерах; это также относится к replicas. Общий Unix socket или Docker volume не является межмашинным интерфейсом. Полный локальный запуск должен проверять тот же сетевой контракт, что распределённый.

## Решение

- Provider поддерживает явно настроенный HTTPS/mTLS listener. Generic read-only `transport.json` и `identity.json` не содержат model ID, prompt, API credential, job identity или очередей. Request/response opaque v1 сохраняются побайтно по прежней схеме.
- TLS 1.2+, строгая CA-проверка и ровно одна разрешённая SPIFFE URI клиента обязательны до dispatch. Клиент проверяет hostname, цепочку и точную provider workload identity до отправки текста. Сертификат доверенной CA с чужой URI не даёт права вызова.
- Policy закрепляет workload identities; разные replicas разрешённой роли имеют отдельные ключи и самостоятельно доставленные leaf certificates. SVID volume, ключ или Docker daemon другого узла не требуется.
- `spire-file-v1` обязателен в production. Текущие сертификаты, bundle и freshness проверяются при новых соединениях; существующее соединение не обходит недоступную/отозванную собственную identity. Устаревшая доставка закрывает запрос, без последнего успешного сертификата или HTTP fallback.
- UDS сохраняется для совместимости существующих выпусков. Сетевой режим выбирается только явным `transport.json`; неполная или неверная конфигурация не включает UDS. Новая полная локальная и распределённая приёмка использует mTLS.
- mTLS healthcheck читает свежий локальный сигнал serving loop с проверкой identity/config; он не получает client private key и не вызывает upstream. Это не доказывает quota, качество или фактический результат перевода.

TLS identity/protocol реализация основана на проверенной владельческой реализации Advance provider commit `1ca48561669be23915f692d2b6015f3383ff4fbb`. В этом репозитории находится самостоятельная копия и её TLS tests; соседний checkout не требуется для build/runtime.

## Проверка и выпуск

Нужны реальные TLS-проверки exact/foreign/anonymous peers, CA, hostname, expiry, renewal, withdrawal, opaque round-trip и отсутствие dispatch у неавторизованного клиента. Перенос текста по сети не считается проверкой модельного качества. Новый runtime требует собственного security review, signed digest обеих native-архитектур, SBOM/provenance, bounded live quality и exact worker integration; security/quality receipts v0.1.1 остаются историческими.

Испытание на одном компьютере не закрывает приёмку на разных физических узлах. Допуск provider не допускает инфраструктуру, не меняет Translator DB и не выдаёт `RESUME`.

## Откат

Выбирается предыдущий совместимый image и явно сохранённая transport configuration после владельческого handoff. Очередь, checkpoints, результаты, keys и история остаются у соответствующих владельцев; автоматическое переключение транспорта при ошибке запрещено.

## Официальные основания

- [Python 3.13 ssl](https://docs.python.org/3.13/library/ssl.html) — certificate validation, hostname, client authentication и обновляемые SSL contexts.
- [Uvicorn](https://www.uvicorn.org/settings/) — ASGI listener и HTTP protocol configuration.
- [HTTPX SSL](https://www.python-httpx.org/advanced/ssl/) — явные CA/client certificate contexts без отключения проверки.
