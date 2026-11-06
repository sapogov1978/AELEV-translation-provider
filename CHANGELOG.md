# Changelog

## 2026-11-06

- Provider выделен из исторического дерева `translator-service` в отдельный
  продукт с сохранением Git-истории provider-specific реализации.
- Kafka, PostgreSQL, operator API, очередь, publisher и consumer-specific код
  удалены из provider; граница сведена к opaque HTTP v1 поверх Unix socket.
- Веса Index Translate 9B, `llama.cpp`, prompt, cache, lock, downloader и
  healthcheck закреплены за provider image и не раскрываются Translator.
- Добавлены нормативная спецификация, операторский manual, ADR, contract
  schema, provenance и официальные ссылки производителей.
- Добавлены CI и подписываемый GHCR release с SBOM/provenance; production
  admission по mutable tag запрещён.
- Runtime image содержит официальные Apache-2.0 и llama.cpp MIT license texts;
  неподтверждённая CPU-архитектура явно не считается поддерживаемой.
