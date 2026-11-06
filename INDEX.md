# Карта репозитория для агента

Эта таблица дополняет граф и нормативные документы; она не заменяет
`AGENTS.md`, `README.md`, `SPEC.md` или `USER_MANUAL.md`.

| Вопрос | Где искать |
|---|---|
| Что является продуктом | `README.md`, `SPEC.md` |
| Как собирать, выпускать и откатывать | `USER_MANUAL.md` |
| Как устроена граница с Translator | `contracts/opaque-translation-v1.json`, `src/aelev_translation_provider/contract.py`, `app.py` |
| Где реализация перевода | `src/aelev_translation_provider/engine.py`, `languages.py` |
| Где закреплены веса и runtime | `provider.lock.json`, `download-model.py`, `Dockerfile` |
| Где readiness и запуск | `src/aelev_translation_provider/__main__.py`, `healthcheck.py` |
| Где ключевые решения | `docs/adr/INDEX.md` |
| Где официальные основания | `docs/references/official-sources.md` |
| Какие admission gates открыты | `TASKS.md` |
| Какие третьи компоненты входят в image | `THIRD_PARTY_NOTICES.md`, `/licenses` image |
| Откуда пришла история | `PROVENANCE.md`, `docs/audit/model-selection/` |
| Где автоматические проверки | `test/`, `.github/workflows/` |
