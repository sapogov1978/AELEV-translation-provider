# Задачи AELEV Translation Provider

- [ ] Допустить exact v0.2.1 по новым 20 исходным/выходным парам после prompt v2.
  [v0.2.0](docs/audit/provider-release-v0.2.0-20261113.json) отклонён по качеству:
  19 смысловых PASS и один FAIL при сохранённых 21 попытке, включая один 503.

Новый mTLS runtime по ADR-0003 требует отдельного допуска; отметки ниже
относятся к неизменяемому историческому v0.1.1. Открыты exact network worker
integration, новый security review/release обеих архитектур, bounded quality
и проверка независимых физических узлов.

До выпуска 0.2.0 выполнена [native arm64-проверка кандидата](docs/audit/provider-network-candidate-20261113.json):
71 provider test, 34 worker transport tests, раздельные network/TLS volumes,
same-CA foreign-client denial, смена доверия и ограниченный security gate.
Это ещё не допуск подписанного выпуска, нового worker release или реального inference.

- [x] Проверить точный v0.1.1 на обеих native-архитектурах по ограниченному
  [рассмотренному профилю](docs/audit/provider-release-v0.1.1-20261111.md), сохранив
  сырой scan и неприменимость каждой HIGH/CRITICAL только в этом профиле.
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
- [x] Пройти изолированную networkless UDS-проверку с exact Translator worker digest.
- [ ] Пройти полный инфраструктурный clean-room и допуск целевой площадки.

20-case provider quality smoke, проверка смысла, ограниченный security-профиль
обеих native-архитектур и отдельная UDS-пара прошли для точного v0.1.1;
доказательства — [provider-release-v0.1.1-20261111.md](docs/audit/provider-release-v0.1.1-20261111.md).
Полный инфраструктурный clean-room остаётся отдельным gate.

Текущий статус: `PROVIDER_QUALITY_PASS / SCOPED_IMAGE_SECURITY_PASS / EXACT_UDS_PAIR_PASS / PLATFORM_CLEAN_ROOM_PENDING`.
