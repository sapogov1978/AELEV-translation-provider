FROM python:3.13.7-slim-bookworm AS python-bookworm

RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/*

FROM python-bookworm AS poetry-base
ENV POETRY_VERSION=2.2.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1
WORKDIR /opt/aelev
RUN --mount=type=cache,id=aelev-provider-pip,target=/root/.cache/pip \
    pip install "poetry==${POETRY_VERSION}"
COPY pyproject.toml poetry.lock ./

FROM poetry-base AS dependencies
RUN --mount=type=cache,id=aelev-provider-poetry,target=/root/.cache/pypoetry \
    poetry install --only main --no-root --no-ansi

FROM dependencies AS test
RUN --mount=type=cache,id=aelev-provider-poetry,target=/root/.cache/pypoetry \
    poetry install --only main,dev --no-root --no-ansi
ENV PYTHONPATH=/opt/aelev/src \
    VIRTUAL_ENV=/opt/aelev/.venv \
    PATH=/opt/aelev/.venv/bin:$PATH
COPY src ./src
COPY test ./test
COPY tools ./tools
COPY contracts ./contracts
COPY prompts ./prompts
COPY provider.lock.json Dockerfile ./
CMD ["poetry", "run", "pytest", "-q"]

FROM python-bookworm AS runtime
LABEL org.opencontainers.image.source="https://github.com/sapogov1978/AELEV-translation-provider" \
      io.aelev.translation-provider.contract="opaque-v1"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/aelev/src \
    VIRTUAL_ENV=/opt/aelev/.venv \
    PATH=/opt/aelev/.venv/bin:$PATH \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    AELEV_TRANSLATION_PROVIDER_LOCK_PATH=/opt/aelev/provider.lock.json \
    AELEV_TRANSLATION_PROVIDER_PROMPT_ROOT=/opt/aelev/prompts \
    AELEV_TRANSLATION_PROVIDER_SOCKET_PATH=/run/aelev-translator/translator.sock \
    OPENAI_API_KEY_FILE=/run/secrets/provider/credential.env
RUN apt-get purge --yes libsqlite3-0 \
    && groupadd --system --gid 10001 aelev \
    && useradd --system --uid 10001 --gid aelev --home-dir /nonexistent aelev \
    && install -d --owner=10001 --group=10001 /run/aelev-translator \
    && install -d --owner=10001 --group=10001 --mode=0700 /run/secrets/compute-provider
WORKDIR /opt/aelev
COPY --from=dependencies /opt/aelev/.venv ./.venv
RUN /usr/local/bin/python -m pip uninstall --yes pip setuptools \
    && /opt/aelev/.venv/bin/python -m pip uninstall --yes pip setuptools \
    && rm -rf /usr/local/lib/python3.13/ensurepip/_bundled \
    && /usr/local/bin/python -c 'import importlib.util as u; assert all(u.find_spec(n) is None for n in ("poetry", "dulwich", "pip", "setuptools"))' \
    && python -c 'import importlib.util as u; assert all(u.find_spec(n) is None for n in ("poetry", "dulwich", "pip", "setuptools"))'
COPY --chown=10001:10001 --chmod=0444 provider.lock.json ./provider.lock.json
COPY --chown=10001:10001 prompts ./prompts
COPY --chown=10001:10001 src ./src
COPY --chown=10001:10001 --chmod=0444 THIRD_PARTY_NOTICES.md ./THIRD_PARTY_NOTICES.md
RUN chmod 0555 ./prompts && chmod 0444 ./prompts/*.txt
USER 10001:10001
RUN python -m aelev_translation_provider verify-config
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD ["python", "-S", "/opt/aelev/src/aelev_translation_provider/healthcheck.py"]
ENTRYPOINT ["python", "-m", "aelev_translation_provider"]
CMD ["serve"]
