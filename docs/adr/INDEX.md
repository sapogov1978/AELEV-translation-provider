# ADR AELEV Translation Provider

ADR — список ключевых решений только этого продукта, а не changelog и не
архив решений исходного монорепозитория.

| ADR | Статус | Решение |
|---|---|---|
| [00-PROVIDER-20261106-0001-opaque-translation-execution](00-PROVIDER-20261106-0001-opaque-translation-execution.md) | Принят частично | Provider владеет реализацией opaque-порта; standalone-часть заменена ADR-0002, обязательность UDS — ADR-0003 |
| [00-PROVIDER-20261109-0002-remote-domain-preserving-translation](00-PROVIDER-20261109-0002-remote-domain-preserving-translation.md) | Принят | OpenAI Responses API по прямому HTTPS, без standalone-модели, с domain-preserving prompt |
| [00-PROVIDER-20261113-0003-independent-mtls-transport](00-PROVIDER-20261113-0003-independent-mtls-transport.md) | Принят | Явный HTTPS/mTLS между независимо размещаемыми worker и provider; UDS остаётся совместимостью |

История standalone model selection хранится отдельно в
`docs/audit/model-selection/` и не является активным runtime-контрактом.
