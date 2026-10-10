FROM python:3.13.7-slim-bookworm AS python-bookworm

# Keep the accepted Python 3.13 / Debian 12 stack while applying the security
# updates published for Bookworm after the immutable upstream image was built.
RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/*

FROM python-bookworm AS poetry-base
ENV POETRY_VERSION=2.2.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1
WORKDIR /opt/aelev
RUN --mount=type=cache,id=aelev-translator-pip,target=/root/.cache/pip \
    pip install "poetry==${POETRY_VERSION}"
COPY pyproject.toml poetry.lock ./
COPY vendor ./vendor


FROM poetry-base AS dependencies
RUN --mount=type=cache,id=aelev-translator-poetry,target=/root/.cache/pypoetry \
    poetry install --only main --no-root --no-ansi

FROM dependencies AS test
RUN apt-get update \
    && apt-get install --yes --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,id=aelev-translator-poetry,target=/root/.cache/pypoetry \
    poetry install --only main,dev --no-root --no-ansi
ENV PYTHONPATH=/opt/aelev/src AELEV_TRANSLATION_CONTRACT_ROOT=/opt/aelev/contracts \
    VIRTUAL_ENV=/opt/aelev/.venv PATH=/opt/aelev/.venv/bin:$PATH
COPY src ./src
COPY --from=translator_tests . ./test
COPY typings ./typings
COPY contracts ./contracts
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY translator.lock.json ./translator.lock.json
CMD ["poetry", "run", "pytest", "-q"]

FROM rust:1.90.0-slim-bookworm AS madlad-runtime-builder
RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/aelev/madlad-runtime
COPY madlad-runtime/Cargo.toml ./Cargo.toml
COPY madlad-runtime/Cargo.lock ./Cargo.lock
COPY madlad-runtime/src ./src
RUN --mount=type=cache,id=aelev-translator-cargo-registry,target=/usr/local/cargo/registry \
    --mount=type=cache,id=aelev-translator-cargo-git,target=/usr/local/cargo/git \
    cargo build --locked --release --jobs 2

FROM python-bookworm AS madlad-translator-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/aelev/src \
    VIRTUAL_ENV=/opt/aelev/.venv \
    PATH=/opt/aelev/.venv/bin:$PATH \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    AELEV_TRANSLATOR_MODEL_ROOT=/opt/aelev/model \
    AELEV_TRANSLATOR_LOCK_PATH=/opt/aelev/translator.lock.json \
    AELEV_TRANSLATOR_SOCKET_PATH=/run/aelev-translator/translator.sock \
    AELEV_TRANSLATOR_RUNTIME_PATH=/usr/local/bin/aelev-madlad-runtime
RUN groupadd --system --gid 10001 aelev \
    && useradd --system --uid 10001 --gid aelev --home-dir /nonexistent aelev \
    && install -d --owner=10001 --group=10001 /opt/aelev/model /run/aelev-translator /var/lib/aelev-status
WORKDIR /opt/aelev
COPY --from=dependencies /opt/aelev/.venv ./.venv
RUN python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip/_bundled
COPY --from=madlad-runtime-builder /opt/aelev/madlad-runtime/target/release/aelev-madlad-runtime /usr/local/bin/aelev-madlad-runtime

FROM madlad-translator-base AS translator-runtime
ADD --chown=10001:10001 --checksum=sha256:d914176fd50bd7f565700006a31aa97b79d3ad17cee20c8e5ff2061d5cb74817 https://huggingface.co/google/madlad400-3b-mt/resolve/fa184c675da0b5c9e1c8694fccd4e12e2d422094/added_tokens.json /opt/aelev/model/added_tokens.json
ADD --chown=10001:10001 --checksum=sha256:cad399cab799b99409a6ec2d90d72552257c2bb752861261d2016691e0643e7c https://huggingface.co/google/madlad400-3b-mt/resolve/fa184c675da0b5c9e1c8694fccd4e12e2d422094/config.json /opt/aelev/model/config.json
ADD --chown=10001:10001 --checksum=sha256:0849b38987568ccfe4ebefc22bbda1cec4bee01c345e93bfab207d4692b0a1d5 https://huggingface.co/google/madlad400-3b-mt/resolve/fa184c675da0b5c9e1c8694fccd4e12e2d422094/generation_config.json /opt/aelev/model/generation_config.json
ADD --chown=10001:10001 --checksum=sha256:ea6e5531a3e95213c7f0635988d119e078a655c09306e47851e15d4c0c3f9c37 https://huggingface.co/google/madlad400-3b-mt/resolve/fa184c675da0b5c9e1c8694fccd4e12e2d422094/model-q4k.gguf /opt/aelev/model/model-q4k.gguf
ADD --chown=10001:10001 --checksum=sha256:7f79f1d5063d56c4b980eec0692f3c7429bdef335071d34e566bd00fd4b5e3e0 https://huggingface.co/google/madlad400-3b-mt/resolve/fa184c675da0b5c9e1c8694fccd4e12e2d422094/special_tokens_map.json /opt/aelev/model/special_tokens_map.json
ADD --chown=10001:10001 --checksum=sha256:ef11ac9a22c7503492f56d48dce53be20e339b63605983e9f27d2cd0e0f3922c https://huggingface.co/google/madlad400-3b-mt/resolve/fa184c675da0b5c9e1c8694fccd4e12e2d422094/spiece.model /opt/aelev/model/spiece.model
ADD --chown=10001:10001 --checksum=sha256:a2799ccc696b752ba00c34f58726bfe253a04921ceb6cfc620400f560474790b https://huggingface.co/google/madlad400-3b-mt/resolve/fa184c675da0b5c9e1c8694fccd4e12e2d422094/tokenizer.json /opt/aelev/model/tokenizer.json
ADD --chown=10001:10001 --checksum=sha256:641fc660745306dfb935f666a68f8bc10a44c39241cfb357be518fda8c09662d https://huggingface.co/google/madlad400-3b-mt/resolve/fa184c675da0b5c9e1c8694fccd4e12e2d422094/tokenizer_config.json /opt/aelev/model/tokenizer_config.json
COPY translator.lock.json ./translator.lock.json
COPY src ./src
COPY contracts ./contracts
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN python -m translator_service.madlad_translation_provider verify-model
USER 10001:10001
CMD ["python", "-m", "translator_service.madlad_translation_provider", "serve"]
