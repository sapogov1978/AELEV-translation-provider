# 00-PROVIDER-20261106-0001 — Непрозрачное исполнение перевода

- **Статус:** Принят
- **Дата:** 2026-11-06

## Контекст

Translator должен устойчиво принимать и диспетчеризовать задания, но не должен
знать, реализован ли перевод моделью, словарём, внешним API или человеком.
Если конкретная модель, её версия и runtime находятся в Translator, очередь и
публичный контракт монолитятся с реализацией вычисления.

## Ключевые решения

- Этот продукт является единственным владельцем модели, весов, runtime,
  prompt, cache, language inventory, quality evidence и image healthcheck.
- Translator передаёт только текст и языки через HTTP v1 поверх private Unix
  socket и получает только перевод с ограниченными warnings или error code.
- Model/runtime identity, версия, profile, prompt и execution reference никогда
  не пересекают этот порт.
- Kafka topics, задания, idempotency, priority, retry journal, operator API и
  сохранённые результаты никогда не входят в provider.
- Provider image является самодостаточным: exact weights и runtime встроены и
  проверены; при запуске сеть для загрузки не требуется.
- Выпуск допускается только по exact image digest с SBOM, provenance,
  signature, contract tests и quality evidence.

## Последствия

Provider можно заменить без изменения Translator и его сохранённой очереди,
если контракт v1 совместим. Новый перевод после замены может отличаться;
исторический результат остаётся обязанностью Translator. Отказ provider
становится bounded technical failure и не уничтожает задание.

## Проверка и откат

CI запрещает дополнительные поля в request/response, проверяет lock и digest
артефактов, UDS round-trip, отсутствие сетевого listener и независимую сборку
образа. Откат выбирает ранее допущенный compatible image digest без удаления
Kafka, БД, UDS volume или запуска остановленного worker.

## Официальные основания

- [IndexTeam pinned model card](https://huggingface.co/IndexTeam/Index-Translate-9B-GGUF/blob/645939fbab839a656f1bc39975a872bc8ad749f8/README.md) описывает официальный GGUF, 150 языков и Apache-2.0.
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) описывает локальный inference server и его API.
- [Uvicorn settings](https://www.uvicorn.org/settings/) определяют запуск ASGI через Unix domain socket.
- [FastAPI container guide](https://fastapi.tiangolo.com/deployment/docker/) описывает самостоятельный container image приложения.
- [Docker build attestations](https://docs.docker.com/build/metadata/attestations/) определяют SBOM и provenance выпуска.
- [Sigstore container signing](https://docs.sigstore.dev/cosign/signing/signing_with_containers/) описывает подпись exact container digest.
