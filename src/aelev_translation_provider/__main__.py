"""Provider image entry point."""

from __future__ import annotations

import argparse
import os
import stat

import uvicorn

from aelev_translation_provider.app import create_app
from aelev_translation_provider.engine import (
    Settings,
    TranslationEngine,
    verify_model_artifacts,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("serve", "verify-model"), nargs="?", default="serve"
    )
    args = parser.parse_args()
    settings = Settings.from_environment()
    if args.command == "verify-model":
        verify_model_artifacts(settings)
        return
    settings.socket_path.parent.mkdir(parents=True, exist_ok=True)
    if settings.socket_path.exists():
        if not stat.S_ISSOCK(settings.socket_path.stat().st_mode):
            raise RuntimeError("PROVIDER_SOCKET_PATH_INVALID")
        settings.socket_path.unlink()
    engine = TranslationEngine(settings)
    try:
        uvicorn.run(
            create_app(engine),
            uds=os.fspath(settings.socket_path),
            access_log=False,
        )
    finally:
        engine.close()


if __name__ == "__main__":
    main()
