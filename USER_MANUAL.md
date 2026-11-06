# Руководство оператора AELEV Translation Provider

## Назначение

Этот репозиторий собирает и выпускает непрозрачный image provider. Оператор
Platform Infrastructure получает только exact image digest; настройки модели,
веса и команды запуска не переносятся в Compose Translator.

## Локальная проверка исходников

Требуются Python 3.13, Poetry 2.2.1 и Docker с BuildKit:

```sh
poetry install
poetry run ruff check .
poetry run ruff format --check .
poetry run pyright
poetry run pytest -q
docker build --target test .
docker build --target runtime-builder .
```

`runtime-builder` проверяет точную сборку нативного runtime без скачивания
5.78 GB весов. Полную сборку выполняет release workflow: downloader принимает
только закреплённые официальные revisions и завершает build при любом
несовпадении размера, Range или SHA-256.

## Выпуск

Release по умолчанию выполняется на одноразовом GitHub-hosted runner
`ubuntu-24.04` с архитектурой Linux x86_64. GitHub создаёт и удаляет runner
автоматически; отдельный сервер, регистрационный token и постоянный агент не
требуются. Workflow записывает фактическую архитектуру и доступный диск до
сборки, удаляет только предустановленные и не используемые этой сборкой SDK из
одноразовой VM и не экспортирует многогигабайтный release build cache. Это
оставляет место одновременно для verified chunks, итогового файла весов и
runtime layer. Self-hosted runner допускается только как явно документированный
fallback после повторяемой нехватки hosted-ресурсов или для выпуска под другую
целевую архитектуру. Официальное описание окружения:
[GitHub-hosted runners](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners).

1. Измените код, `provider.lock.json` или документацию и добавьте запись в
   `CHANGELOG.md`.
2. Выполните локальные проверки выше.
3. Merge в `main` не создаёт production release автоматически.
4. Создайте подписанный tag `vX.Y.Z`; workflow собирает runtime, публикует
   `ghcr.io/sapogov1978/aelev-translation-provider`, SBOM и provenance, затем
   подписывает точный digest через GitHub OIDC.
5. Возьмите digest из job summary или artifact `release-digest`; tag не
   используйте для admission.
6. Запустите `quality-smoke-provider-release`: он загружает exact digest,
   поднимает его с ограниченными правами и ресурсами и проверяет через opaque
   UDS утверждённый синтетический корпус из 20 примеров против сохранённого
   результата той же модели/runtime. Evidence содержит только case ID, хеши и
   длительности, а не пользовательские данные. Допустимый не-побайтный вариант
   должен быть перечислен в `quality/approved-alternates.json`, связан с exact
   release digest и иметь отдельное смысловое обоснование; wildcard и
   автоматическое принятие drift запрещены.

Release workflow публикует в private GHCR через краткоживущий встроенный
`GITHUB_TOKEN`; отдельный registry credential для публикации не нужен. Для
последующего pull на целевой площадке credential хранится только локально с
правом `read:packages`, не передаётся в чат и не записывается в repository
files. Официальные инструкции:
[GitHub Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
[publishing Docker images](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images),
[Docker SBOM/provenance](https://docs.docker.com/build/ci/github-actions/attestations/)
и [Cosign container signing](https://docs.sigstore.dev/cosign/signing/signing_with_containers/).

## Подключение к Translator

В `AELEV-platform-infrastructure/translator-service/.env` задаётся только:

```dotenv
AELEV_INFRASTRUCTURE_TRANSLATOR_PROVIDER_IMAGE=ghcr.io/sapogov1978/aelev-translation-provider@sha256:<64-hex>
```

Compose обязан сохранить image-owned `ENTRYPOINT`, `CMD`, environment и
`HEALTHCHECK`. Provider и worker совместно получают только отдельный UDS volume;
TCP port, model volume и Docker socket не предоставляются. Запуск, остановка и
rollback выполняются владельческим runbook Platform Infrastructure, чтобы не
затронуть Kafka/БД/историю Translator.

## Диагностика

- `unhealthy` означает, что provider или нативный runtime не готовы; это не
  разрешает удалять очередь или автоматически менять образ.
- `PROVIDER_MODEL_*` и `PROVIDER_LOCK_*` — несоответствие встроенных
  артефактов; image не допускается, пересборка поверх mutable source запрещена.
- `PROVIDER_RUNTIME_*` — ошибка запуска/ответа закреплённого `llama-server`.
- `PROVIDER_DEADLINE_EXCEEDED` — bounded timeout; Translator сохраняет задание
  для собственной retry policy.
- `TRANSLATOR_*` в 422 — безопасный semantic/request код, а не внутренний stack.

Сырые исходные тексты и переводы не пишутся в журнал provider. При разборе
ошибки сохраняйте image digest, timestamp и ограниченный error code; не
копируйте пользовательский текст в issue или CI artifact.

## Откат

Откат — замена только provider digest на ранее допущенный совместимый digest.
Не удаляйте UDS volume, Translator database, Kafka topics или сохранённые
результаты. До замены дождитесь отсутствия активной provider lease по runbook
Translator; rollback не означает `RESUME` и не запускает остановленный worker.

## Официальные руководства поставщиков

- [IndexTeam: pinned model card and Apache-2.0 metadata](https://huggingface.co/IndexTeam/Index-Translate-9B-GGUF/blob/645939fbab839a656f1bc39975a872bc8ad749f8/README.md)
- [IndexTeam: pinned Q4_K_M artifact](https://huggingface.co/IndexTeam/Index-Translate-9B-GGUF/blob/645939fbab839a656f1bc39975a872bc8ad749f8/Index-Translate-9B.Q4_K_M.gguf)
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp build documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)
- [FastAPI container deployment](https://fastapi.tiangolo.com/deployment/docker/)
- [Uvicorn settings, including UDS](https://www.uvicorn.org/settings/)
- [Docker Dockerfile reference](https://docs.docker.com/reference/dockerfile/)
- [Docker Build cache mounts](https://docs.docker.com/build/cache/optimize/)

Полный реестр с привязкой к решениям находится в
[docs/references/official-sources.md](docs/references/official-sources.md).
