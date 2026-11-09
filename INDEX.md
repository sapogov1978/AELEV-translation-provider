# Карта репозитория для агента

| Вопрос | Где искать |
|---|---|
| Что является продуктом | `README.md`, `SPEC.md` |
| Как собирать, выпускать и откатывать | `USER_MANUAL.md` |
| Граница с Translator | `contracts/opaque-translation-v1.json`, `contract.py`, `app.py` |
| API-исполнение и cache | `src/aelev_translation_provider/engine.py` |
| Модель и execution profile | `provider.lock.json` |
| Domain-preserving instructions | `prompts/domain-preserving-translation-v1.txt` |
| Readiness и запуск | `__main__.py`, `healthcheck.py`, `Dockerfile` |
| Ключевые решения | `docs/adr/INDEX.md` |
| Открытые admission gates | `TASKS.md` |
| История standalone-выбора | `PROVENANCE.md`, `docs/audit/model-selection/` |
| Автоматические проверки | `test/`, `.github/workflows/` |
