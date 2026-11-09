# Задачи AELEV Translation Provider

- [x] Сохранить opaque UDS v1 без model/provider identity.
- [x] Удалить standalone-веса, downloader и `llama.cpp` из активной сборки.
- [x] Закрепить `gpt-6.1-sol`, Responses API, prompt digest и HTTPS profile.
- [x] Добавить domain-preserving request и strict structured response.
- [x] Добавить offline unit/type/lint, UDS round-trip и Docker test target.
- [x] В PlatformInfrastructure подготовить исходящую сеть provider и generic
  read-only secret mount без раскрытия model/API identity.
- [ ] Вручную записать действующий OpenAI API key в локальный secret file.
- [ ] Проверить project access/quota и bounded live translation без `RESUME`.
- [ ] Выпустить новый exact image digest с SBOM, provenance и signature.
- [ ] Пройти quality smoke и clean-room gate с exact Translator worker digest.

Текущий статус: `IN_PROGRESS / BLOCKED`, не `PRODUCTION_READY`.
