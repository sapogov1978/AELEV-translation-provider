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

from provider_security import EXECUTION_PROBE, assess_scan, validate_review

PROBE = (
    r"""
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
"""
    + EXECUTION_PROBE
    + r"""
print(json.dumps({
    "python": sys.executable,
    "python_version": sys.version.split()[0],
    "build_tools_absent": True,
    "sqlite_library_absent": True,
    "minizip_library_and_vulnerable_symbol_absent": True,
    "systemd_homed_absent": True,
    "execution": execution_evidence
}))
"""
)


def run(*arguments: str) -> str:
    return subprocess.run(
        arguments, check=True, capture_output=True, text=True, timeout=90
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scan", type=Path, help="Matching complete Trivy JSON report")
    args = parser.parse_args()
    if re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}", args.image) is None:
        raise ValueError("IMMUTABLE_RUNTIME_IMAGE_REQUIRED")
    if args.output.exists():
        raise ValueError("RUNTIME_EVIDENCE_ALREADY_EXISTS")
    inspected = cast(
        list[dict[str, Any]], json.loads(run("docker", "image", "inspect", args.image))
    )
    image = inspected[0]
    config = image["Config"]
    if config["User"] != "10001:10001" or config["Cmd"] != ["serve"]:
        raise ValueError("PROVIDER_IMAGE_PROFILE_MISMATCH")
    environment = dict(item.split("=", 1) for item in config["Env"])
    if (
        environment.get("PYTHONPATH") != "/opt/aelev/src"
        or any(
            environment.get(key)
            for key in (
                "LD_PRELOAD",
                "PYTHONINSPECT",
                "PYTHONSTARTUP",
                "PYTHONHOME",
                "AELEV_PROVIDER_INSECURE_HTTP",
            )
        )
        or environment.get("PYTHONOPTIMIZE", "0") != "0"
        or environment.get("WEB_CONCURRENCY", "1") != "1"
    ):
        raise ValueError("PROVIDER_IMAGE_ENVIRONMENT_REQUIRES_REVIEW")
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
        "security_probe_sha256": hashlib.sha256(
            Path(__file__).with_name("provider_security.py").read_bytes()
        ).hexdigest(),
        "network": "none",
        "credential_mounts": False,
        "upstream_calls": False,
        "probes": probes,
        "scope": "Runtime footprint only; not a complete vulnerability admission.",
    }
    package = cast(dict[str, Any], probes[-1])["execution"]["package"]
    if config["Entrypoint"] != ["python", "-m", package]:
        raise ValueError("PROVIDER_IMAGE_ENTRYPOINT_MISMATCH")
    report["reviewed_profile_sha256"] = validate_review(
        probes, Path(__file__).resolve().parents[1]
    )
    if args.scan:
        scan = cast(dict[str, Any], json.loads(args.scan.read_text(encoding="utf-8")))
        report["security"] = assess_scan(
            scan, identity, probes, Path(__file__).resolve().parents[1]
        )
        report["scan_file_sha256"] = hashlib.sha256(args.scan.read_bytes()).hexdigest()
        report["scope"] = report["security"]["scope"]
        report["status"] = report["security"]["status"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "image_id": identity,
                "architecture": report["architecture"],
                "output": str(args.output),
            }
        )
    )
    if report["status"] == "SECURITY_BLOCKED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
