# 00-PROVIDER-20261109-0002 — Удалённый domain-preserving перевод

- **Статус:** Принят
- **Дата:** 2026-11-09
- **Заменяет:** standalone runtime-часть ADR-0001; opaque port сохраняется

## Контекст

Встроенная model/runtime пара усложняет release, ограничивает качество и
связывает смену модели с пересборкой нативных артефактов. Передача
отдельных слов без контекста также теряет предметную семантику.

## Ключевые решения

- Standalone model, weights, downloader и native runtime удаляются из активной
  поставки.
- Provider использует OpenAI Responses API; текущий lock выбирает
  `gpt-6.1-sol`. Код позволяет заменить model ID через новый lock/release.
- В модель передаётся весь opaque-сегмент с языковыми metadata и exact
  provider-owned prompt. Модель молча выводит предметную область текущего
  сегмента и сохраняет её терминологию и смысл.
- Межзапросная model conversation запрещена: opaque v1 не передаёт job/domain
  identity, а смешивание текстов разных заданий недопустимо.
- API request идёт напрямую по HTTPS к закреплённому OpenAI endpoint с
  системной проверкой TLS и bounded timeout.
- API key принадлежит provider, передаётся как runtime secret и не входит в
  image, lock, log или opaque response.
- Responses не сохраняются provider'ом (`store=false`) и принимаются
  только по strict JSON schema.

## Последствия

Image становится меньше, а смена модели не меняет opaque contract. При
этом доступность зависит от сети, API quota и внешнего сервиса.
Image digest больше не доказывает байтовую идентичность весов удалённой
модели; поэтому bounded live quality gate обязателен для каждого выпуска и
смены model ID/prompt.

## Проверка и откат

CI доказывает prompt/lock digest, точную форму прямого API request,
`store=false`, strict output, отсутствие implementation identity на UDS и сборку
без key. Production admission дополнительно требует model access/quota и bounded
live smoke. Откат меняет только provider digest и не восстанавливает отозванный
credential.

## Официальные основания

- [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) закрепляет
  model ID, Responses support, reasoning efforts и structured outputs.
- [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
  описывает `model`, `instructions`, `input`, `reasoning`, `store` и output format.
