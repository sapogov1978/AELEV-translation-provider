# Задачи AELEV Translation Provider

Исходный продукт и opaque contract готовы; общий production admission ещё не
выдан.

- [x] Сохранить Git-историю provider-specific реализации при выделении.
- [x] Отделить Kafka, очередь, БД, operator API и consumer resources.
- [x] Закрепить веса, runtime, profile, downloader и image healthcheck.
- [x] Проверить source/type/lint, реальный UDS round-trip, Docker test target и
  exact native runtime build локально и в независимом CI.
- [x] Добавить SBOM/provenance/keyless-signature release pipeline и license
  notices встроенных третьих компонентов.
- [ ] Выполнить release workflow на GitHub-hosted Linux x86_64 runner и получить
  подписанный `name@sha256` artifact; self-hosted fallback вводить только при
  доказанной нехватке hosted-ресурсов.
- [ ] Выполнить bounded real-model quality smoke для release digest и сохранить
  evidence без пользовательских данных.
- [ ] Пройти совместный clean-room gate Platform Infrastructure с точным
  Translator worker digest.

До закрытия последних трёх пунктов статус продукта: `IN_PROGRESS / BLOCKED`,
не `PRODUCTION_READY`.
