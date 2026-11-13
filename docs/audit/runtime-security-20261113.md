# Ограниченный security-профиль сетевого Translation Provider

Область — новый opaque UDS/mTLS runtime, Python 3.13.7 и Debian Bookworm. Стек, model/prompt lock и контракт текста сохранены. Это отдельный review нового кода; receipt v0.1.1 не допускает его автоматически. Точный native image, raw scan, source hashes и результат gate фиксируются отдельно. Полный platform/site admission этим документом не объявляется.

## Условия профиля

- Штатный opaque entrypoint, UID/GID 10001, read-only root, dropped capabilities и no-new-privileges. OpenAI key доступен только provider; worker получает только собственный TLS key.
- До dispatch проверяются CA, exact workload URI, leaf purpose/срок и текущая доставка; worker дополнительно проверяет hostname до текста. Соединение связано с SSLContext своего handshake: смена trust/identity закрывает старый HTTP допуск.
- До JSON parsing/model body ограничен 256 KiB и 10 секундами, включая поток без правильной Content-Length. Concurrent HTTP connections/tasks ограничены 32; inference последовательно, с отдельным deadline.
- Application process invocation и dynamic native execution APIs отсутствуют. Native imports/symbols, отсутствие MiniZip, systemd-homed, Perl Archive::Tar, сборочных инструментов и SQLite проверяются обоими Python-интерпретаторами exact runtime.
- Произвольный OS CLI/entrypoint, дополнительные capabilities или иной source/dependency set находятся вне допуска.

## Пакетные находки

Native Trivy 0.76.1 с DB `UpdatedAt=2026-11-13T00:58:46Z` сохранил 35 HIGH и 1 CRITICAL в OS packages. Сырые находки не удаляются и не подавляются. Это те же 11 CVE из [прежнего разбора](runtime-security-20261111.md); каждое точное сочетание CVE/package заново проверяется через `tools/provider_security.py` по текущим исходникам и native evidence. Новая HIGH/CRITICAL либо отсутствующее доказательство блокирует допуск.

CRITICAL `CVE-2023-45853` относится к отсутствующему MiniZip, а не ко всем операциям zlib. Другие решения ограничены отсутствующим кодом либо недоступными CLI/native путями и проверенными полномочиями. Blanket-исключения пакета нет.

## Дополнительные CPython TLS advisories

Рассмотрены первичные [исправления 3.13.16](https://www.python.org/downloads/release/python-31316/) и [3.13.18](https://www.python.org/downloads/release/python-31318/). Runtime остаётся 3.13.7: ниже конкретные условия защиты, а не заявление об установленном патче.

| Advisory | Условие этого runtime | Доказательство |
|---|---|---|
| CVE-2026-19445, SNI context use-after-free | Callback-bearing initial context удерживается listening configuration весь срок работы — [upstream mitigation](https://github.com/python/cpython/issues/156293) | `test_callback_context_survives_hrr_gc_and_identity_renewal`: настоящий TLS 1.3 HelloRetryRequest, принудительный GC, renewal, HTTP-ответы и живой context на обеих попытках |
| CVE-2026-19553, wrap_bio argument validation | `verified_self` использует литералы server/client role, без hostname в локальном in-memory handshake и без session. Network server имеет серверную роль; upstream hostname закреплён lock. Opaque text не попадает в TLS arguments | Review `tls_identity.py`, `tls_server.py`, engine lock и отрицательные TLS tests; произвольного hostname в opaque request нет |
| CVE-2026-115557, compromised CA keys | `ca-certificates=20250419~deb12u2`, `certifi=2026.10.23`; известные опасные root paths удалены из обоих действительных bundles. Внутреннее mTLS использует собственный SPIRE bundle | Native probe проверяет четыре DER fingerprints по [первичному списку roots](https://emudhra.we-have-a-problem.com/roots.json); `known_compromised_ca_roots_absent=true` обязателен. [Certifi release](https://github.com/certifi/python-certifi/releases/tag/2026.10.19) и [описание инцидента](https://emudhra.we-have-a-problem.com/) определяют область |

Это не общий допуск всех применений Python 3.13.7 или чужой PKI. Один физический хост не закрывает распределённую приёмку. Каждый новый image/release требует своего scan и проверки тех же условий.

Candidate 0.2.1 reviews the added logging path: only HTTP status, a fixed
allowlist of error codes or the exception class is formatted. No headers,
error messages, keys, source/output text, process invocation or dynamic native
API is added. Native trust/footprint and all existing CVE conditions remain
mandatory. Prompt v2 changes the provider lock and requires fresh quality
admission; the signed v0.2.0 has a recorded semantic rejection.
