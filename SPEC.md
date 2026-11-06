# Нормативная спецификация AELEV Translation Provider

## Ответственность

Provider является единственным владельцем конкретной реализации перевода:
выбора модели, версии весов, prompt, нативного runtime, локального cache,
проверки целостности и Docker healthcheck. Он не владеет Kafka topics,
заданиями Translator, consumer identity, приоритетом, retry journal,
checkpoints, operator API или пользовательским применением результата.

## Непрозрачный порт

Единственный внешний transport — HTTP/1.1 поверх Unix socket
`/run/aelev-translator/translator.sock`. Порт не публикуется по TCP и доступен
только паре provider/worker через отдельный runtime volume.

`POST /v1/translate` принимает ровно:

```json
{
  "schema_version": "1.0.0",
  "source_language": "en",
  "target_language": "de",
  "text": "Hello"
}
```

Ответ 200 содержит ровно `schema_version`, непустой `translated_text` и
`warnings`. Запрещены model name, model version, engine, execution reference,
prompt, cache key, request/job identity и любые provider-specific поля.
Формальная схема находится в [contracts](contracts/opaque-translation-v1.json).

Невалидный запрос и безопасно классифицируемый семантический отказ дают 422 с
ограниченным кодом. Неготовность, deadline, смерть runtime и невалидный ответ
дают 503 с ограниченным кодом. Произвольный текст исключения, fragment output
и внутренний ответ `llama-server` через границу не проходят.

`GET /healthz` возвращает 200 только когда Python provider и его нативный
runtime живы, модель загружена и runtime подтвердил readiness. Docker
`HEALTHCHECK` принадлежит образу provider и обращается к тому же UDS.

## Артефакты и исполнение

`provider.lock.json` закрепляет ровно один GGUF по имени, размеру и SHA-256,
точную ревизию исходников `llama.cpp` с SHA-256 архива и весь inference
profile. `execution_ref` является хешем веса и profile, проверяется при старте,
но никогда не раскрывается Translator.

Веса скачиваются только на build stage с двух официальных mirrors, частями с
Range validation, после чего размер и итоговый SHA-256 проверяются до
публикации. Runtime image не выполняет сетевую загрузку, запускается не от
root, содержит read-only lock/weights и слушает только UDS; дочерний
`llama-server` слушает loopback внутри того же контейнера.

Одновременно исполняется один запрос. FIFO-ожидание ограничено общим deadline.
Cache ограничен 2 048 ключами и является недолговечным ускорением, а не
источником истины. Перезапуск может потерять cache без потери принятого
задания: durable retry остаётся обязанностью Translator.

## Качество и совместимость

Поддерживаемый language inventory закреплён кодом provider. Ответ всегда
помечается `MACHINE_TRANSLATION_UNVERIFIED`; дословно неизменившийся результат
дополнительно получает `UNCHANGED_OUTPUT`. Транспортный успех не является
утверждением смысловой точности.

Замена модели, runtime или profile требует нового provider release, полного
quality evidence и нового image digest. Она не должна требовать изменения
opaque contract или Translator. Несовместимое изменение порта требует новой
major schema version и совместного migration plan.

## Release admission

Releasable image строится только CI из чистого commit, получает SBOM,
provenance и keyless signature. В production допускается exact digest после:

1. unit/type/lint и Docker test target;
2. успешной полной runtime build с проверкой весов;
3. contract round-trip с Translator worker;
4. bounded quality smoke на утверждённом corpus;
5. проверки подписи и attestations;
6. clean-room функционального gate Platform Infrastructure.

Tag, успешная локальная сборка или healthcheck сами по себе admission не дают.
Image digest является platform-specific, пока release явно не собрал и не
проверил multi-platform manifest. Архитектура release runner должна совпадать
с целевой площадкой; неподтверждённая архитектура не считается поддерживаемой.
