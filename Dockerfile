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
COPY contracts ./contracts
COPY provider.lock.json download-model.py Dockerfile ./
CMD ["poetry", "run", "pytest", "-q"]

FROM python-bookworm AS model-assets
COPY provider.lock.json download-model.py /supply/
RUN --mount=type=cache,id=aelev-provider-index-weights,target=/var/cache/aelev-provider \
    python /supply/download-model.py --lock /supply/provider.lock.json \
    --destination /model --cache /var/cache/aelev-provider

FROM python-bookworm AS runtime-builder
RUN apt-get update \
    && apt-get install --yes --no-install-recommends cmake g++ make \
    && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:6b58785f0a82898f4c3442417ff962e2d4b231b1bee5d033902ad90b27901e14 https://codeload.github.com/ggml-org/llama.cpp/tar.gz/d81235049384534c167caea52b85a694f6103d14 /source.tar.gz
RUN mkdir /source \
    && tar -xzf /source.tar.gz --strip-components=1 -C /source \
    && cmake -S /source -B /source/build \
       -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF \
       -DLLAMA_BUILD_IS_DEV=OFF -DLLAMA_BUILD_NUMBER=0 \
       -DLLAMA_BUILD_COMMIT=d81235049384534c167caea52b85a694f6103d14 \
       -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
       -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_COMMON=ON \
       -DLLAMA_BUILD_TOOLS=ON -DLLAMA_BUILD_APP=OFF \
       -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF \
    && cmake --build /source/build --parallel 2 --target llama-server

FROM scratch AS license-assets
ADD --checksum=sha256:cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30 https://www.apache.org/licenses/LICENSE-2.0.txt /licenses/Index-Translate-Apache-2.0.txt
ADD --checksum=sha256:94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d https://raw.githubusercontent.com/ggml-org/llama.cpp/d81235049384534c167caea52b85a694f6103d14/LICENSE /licenses/llama.cpp-MIT.txt

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
    AELEV_TRANSLATION_PROVIDER_MODEL_ROOT=/opt/aelev/model \
    AELEV_TRANSLATION_PROVIDER_LOCK_PATH=/opt/aelev/provider.lock.json \
    AELEV_TRANSLATION_PROVIDER_SOCKET_PATH=/run/aelev-translator/translator.sock \
    AELEV_TRANSLATION_PROVIDER_RUNTIME_PATH=/opt/llama/llama-server \
    LD_LIBRARY_PATH=/opt/llama
RUN groupadd --system --gid 10001 aelev \
    && useradd --system --uid 10001 --gid aelev --home-dir /nonexistent aelev \
    && install -d --owner=10001 --group=10001 /run/aelev-translator /opt/aelev/model
WORKDIR /opt/aelev
COPY --from=dependencies /opt/aelev/.venv ./.venv
RUN python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip/_bundled
COPY --from=runtime-builder /source/build/bin/ /opt/llama/
COPY --from=license-assets /licenses /licenses
COPY --from=model-assets --chown=10001:10001 --chmod=0444 /model/Index-Translate-9B.Q4_K_M.gguf /opt/aelev/model/Index-Translate-9B.Q4_K_M.gguf
COPY --chown=10001:10001 --chmod=0444 provider.lock.json ./provider.lock.json
COPY --chown=10001:10001 src ./src
COPY --chown=10001:10001 --chmod=0444 THIRD_PARTY_NOTICES.md ./THIRD_PARTY_NOTICES.md
USER 10001:10001
RUN python -m aelev_translation_provider verify-model
HEALTHCHECK --interval=10s --timeout=5s --retries=30 \
    CMD ["python", "-S", "/opt/aelev/src/aelev_translation_provider/healthcheck.py"]
ENTRYPOINT ["python", "-m", "aelev_translation_provider"]
CMD ["serve"]
