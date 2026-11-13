"""Provider image entry point."""

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

import uvicorn

from aelev_translation_provider.app import create_app
from aelev_translation_provider.engine import (
    Settings,
    TranslationEngine,
    verify_provider_configuration,
)
from aelev_translation_provider.healthcheck import clear_readiness
from aelev_translation_provider.tls_identity import Identity
from aelev_translation_provider.tls_server import configured_server
from aelev_translation_provider.transport import Transport


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("serve", "verify-config"), nargs="?", default="serve"
    )
    args = parser.parse_args()
    if args.command == "verify-config":
        verify_provider_configuration(
            Path(os.environ["AELEV_TRANSLATION_PROVIDER_LOCK_PATH"]),
            Path(os.environ["AELEV_TRANSLATION_PROVIDER_PROMPT_ROOT"]),
        )
        return
    settings = Settings.from_environment()
    transport = Transport.environment()
    clear_readiness()
    if transport.mode == "uds":
        settings.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if settings.socket_path.exists():
            if not stat.S_ISSOCK(settings.socket_path.stat().st_mode):
                raise RuntimeError("PROVIDER_SOCKET_PATH_INVALID")
            settings.socket_path.unlink()
    engine = TranslationEngine(settings)
    try:
        if transport.mode == "mtls":
            identity = Identity(transport.root, "translator-service")
            configured_server(
                create_app(engine, identity.available),
                identity,
                transport.host,
                transport.port,
            ).run()
        else:
            uvicorn.run(
                create_app(engine),
                uds=os.fspath(settings.socket_path),
                access_log=False,
                proxy_headers=False,
                ws="none",
            )
    finally:
        clear_readiness()
        engine.close()


if __name__ == "__main__":
    main()
