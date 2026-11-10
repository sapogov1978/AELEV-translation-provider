# Задачи AELEV Translation Provider

- [ ] Закрыть допуск уязвимостей точного образа после удаления сборочных
  инструментов: [рассмотренный профиль](docs/audit/runtime-security-20261111.md)
  отделяет устранённые находки, проверенную неприменимость и открытые CVE.
- [x] Сохранить opaque UDS v1 без model/provider identity.
- [x] Удалить standalone-веса, downloader и `llama.cpp` из активной сборки.
- [x] Закрепить `gpt-6.1-sol`, Responses API, prompt digest и HTTPS profile.
- [x] Добавить domain-preserving request и strict structured response.
- [x] Добавить offline unit/type/lint, UDS round-trip и Docker test target.
- [x] В PlatformInfrastructure подготовить исходящую сеть provider и generic
  read-only secret mount без раскрытия model/API identity.
- [x] Вручную записать действующий OpenAI API key в локальный secret file.
- [x] Проверить project access/quota и bounded live translation без `RESUME`.
- [x] Выпустить exact multi-platform image digest с SBOM, provenance и signature.
- [x] Пройти bounded provider quality smoke и отдельно проверить смысл переводов.
- [ ] Пройти совместный clean-room gate с exact Translator worker digest.

20-case provider quality smoke и проверка смысла прошли для точного OpenAI
image 2026-11-10; доказательства —
[provider-release-v0.1.0-20261110.md](docs/audit/provider-release-v0.1.0-20261110.md).
Совместный clean-room остаётся отдельным инфраструктурным gate.

Текущий статус: `PROVIDER_QUALITY_PASS / IMAGE_SECURITY_BLOCKED / PLATFORM_CLEAN_ROOM_PENDING`.
