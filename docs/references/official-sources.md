# Официальные источники

Проверено 2026-11-09.

| Решение или операция | Официальный источник | Применение |
|---|---|---|
| API model | [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) | Model ID, Responses support, reasoning efforts, structured output |
| Responses API | [Create a response](https://developers.openai.com/api/reference/resources/responses/methods/create) | `model`, `instructions`, `input`, `reasoning`, `store`, structured text format |
| ASGI application | [FastAPI containers](https://fastapi.tiangolo.com/deployment/docker/) | Самостоятельный image приложения |
| Unix socket | [Uvicorn settings](https://www.uvicorn.org/settings/) | `--uds` transport без TCP publication |
| Container recipe | [Dockerfile reference](https://docs.docker.com/reference/dockerfile/) | Non-root, read-only runtime inputs, image healthcheck |
| SBOM/provenance | [Docker attestations](https://docs.docker.com/build/ci/github-actions/attestations/) | Release attestations |
| GHCR publication | [Publishing Docker images](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images) | Digest publication |
| Image signature | [Sigstore Cosign](https://docs.sigstore.dev/cosign/signing/signing_with_containers/) | Keyless signature exact digest |

Исторические pinned-ссылки standalone-эксперимента сохранены в
`docs/audit/model-selection/` и не являются active runtime guidance.
