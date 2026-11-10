"""Verify the isolated runtime footprint without credentials or upstream calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

PROBE = r"""
import ctypes
import importlib.util
import json
from pathlib import Path
import sys

tools = ("poetry", "dulwich", "pip", "setuptools", "pyminizip")
assert all(importlib.util.find_spec(name) is None for name in tools)
try:
    ctypes.CDLL("libsqlite3.so.0")
except OSError:
    pass
else:
    raise AssertionError("UNEXPECTED_RUNTIME_SQLITE")
assert not list(Path("/usr/lib").glob("**/libminizip.so*"))
assert not Path("/usr/lib/systemd/systemd-homed").exists()
zlib = ctypes.CDLL("libz.so.1")
assert not hasattr(zlib, "zipOpenNewFileInZip4_64")
if sys.executable.startswith("/opt/aelev/.venv/"):
    import fastapi
    import httpx
    import uvicorn
print(json.dumps({
    "python": sys.executable,
    "python_version": sys.version.split()[0],
    "build_tools_absent": True,
    "sqlite_library_absent": True,
    "minizip_library_and_vulnerable_symbol_absent": True,
    "systemd_homed_absent": True
}))
"""


def run(*arguments: str) -> str:
    return subprocess.run(
        arguments, check=True, capture_output=True, text=True, timeout=90
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}", args.image) is None:
        raise ValueError("IMMUTABLE_RUNTIME_IMAGE_REQUIRED")
    if args.output.exists():
        raise ValueError("RUNTIME_EVIDENCE_ALREADY_EXISTS")
    inspected = cast(
        list[dict[str, Any]], json.loads(run("docker", "image", "inspect", args.image))
    )
    image = inspected[0]
    identity = cast(str, image["Id"])
    if re.fullmatch(r"sha256:[0-9a-f]{64}", identity) is None:
        raise ValueError("RUNTIME_IMAGE_ID_INVALID")
    probes: list[object] = []
    for interpreter in ("/usr/local/bin/python", "/opt/aelev/.venv/bin/python"):
        probes.append(
            json.loads(
                run(
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "64",
                    "--memory",
                    "256m",
                    "--cpus",
                    "1",
                    "--entrypoint",
                    interpreter,
                    identity,
                    "-c",
                    PROBE,
                )
            )
        )
    report = {
        "schema_version": 1,
        "status": "RUNTIME_SURFACE_PASS",
        "recorded_at": datetime.now(UTC).isoformat(),
        "image": args.image,
        "image_id": identity,
        "architecture": image["Os"] + "/" + image["Architecture"],
        "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "network": "none",
        "credential_mounts": False,
        "upstream_calls": False,
        "probes": probes,
        "scope": "Runtime footprint only; not a complete vulnerability admission.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
