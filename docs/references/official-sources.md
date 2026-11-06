# Официальные источники

Проверено 2026-11-06. Pinned ссылки используются для воспроизводимости;
страницы `master` — только как руководства поставщика, не как источник версии.

| Решение или операция | Официальный источник | Применение |
|---|---|---|
| Модель и лицензия | [IndexTeam model card at pinned revision](https://huggingface.co/IndexTeam/Index-Translate-9B-GGUF/blob/645939fbab839a656f1bc39975a872bc8ad749f8/README.md) | Семейство, 150 языков, Apache-2.0, llama.cpp usage |
| Exact Q4_K_M weights | [Pinned Hugging Face artifact](https://huggingface.co/IndexTeam/Index-Translate-9B-GGUF/blob/645939fbab839a656f1bc39975a872bc8ad749f8/Index-Translate-9B.Q4_K_M.gguf) | Primary build source; local lock additionally verifies size/SHA-256 |
| Официальный mirror | [IndexTeam ModelScope model](https://modelscope.cn/models/IndexTeam/Index-Translate-9B-GGUF) | Alternate source той же закреплённой модели |
| Native inference | [llama.cpp repository](https://github.com/ggml-org/llama.cpp) и [server guide](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | Runtime собирается из exact commit; guide описывает server API |
| Native build | [llama.cpp build guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md) | CMake build официального runtime |
| ASGI application | [FastAPI containers](https://fastapi.tiangolo.com/deployment/docker/) | Самостоятельный image приложения |
| Unix socket | [Uvicorn settings](https://www.uvicorn.org/settings/) | `--uds`/UDS transport без TCP publication |
| Container recipe | [Dockerfile reference](https://docs.docker.com/reference/dockerfile/) | Multi-stage, non-root, healthcheck и immutable filesystem inputs |
| Build cache | [Docker cache optimization](https://docs.docker.com/build/cache/optimize/) | Cache mount для повторной verified загрузки больших весов |
| SBOM/provenance | [Docker attestations in GitHub Actions](https://docs.docker.com/build/ci/github-actions/attestations/) | `sbom: true`, `provenance: mode=max` |
| GHCR publication | [GitHub publishing Docker images](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images) | Registry login, build and digest publication |
| GHCR access | [GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) | Private package permissions and digest pulls |
| Release runner | [Adding self-hosted runners](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners) и [runner labels](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow) | Регистрация isolated runner целевой архитектуры с label `aelev-provider-release` |
| Image signature | [Sigstore Cosign container signing](https://docs.sigstore.dev/cosign/signing/signing_with_containers/) | Keyless GitHub OIDC signature of exact digest |
