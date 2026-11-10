#!/usr/bin/env python3
"""Run the approved synthetic corpus through one released provider UDS."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import socket
import time
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/audit/model-selection/cases.json"


class UnixHTTPConnection(http.client.HTTPConnection):
    """Minimal standard-library HTTP client for the opaque Unix socket."""

    def __init__(self, path: Path, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(str(self._path))
        self.sock = connection


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def objects(path: Path) -> list[dict[str, Any]]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise RuntimeError("QUALITY_CORPUS_INVALID")
    rows = cast(list[object], value)
    if not all(isinstance(row, dict) for row in rows):
        raise RuntimeError("QUALITY_CORPUS_INVALID")
    return cast(list[dict[str, Any]], rows)


def translate(socket_path: Path, case: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    body = json.dumps(
        {
            "schema_version": "1.0.0",
            "source_language": case["source"],
            "target_language": case["target"],
            "text": case["text"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    client = UnixHTTPConnection(socket_path, timeout=240)
    try:
        client.request(
            "POST",
            "/v1/translate",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        response = client.getresponse()
        raw = response.read()
    finally:
        client.close()
    if response.status != 200:
        raise RuntimeError(f"QUALITY_PROVIDER_HTTP_{response.status}")
    decoded: object = json.loads(raw)
    if not isinstance(decoded, dict):
        raise RuntimeError("QUALITY_PROVIDER_RESPONSE_INVALID")
    value = cast(dict[str, Any], decoded)
    if set(value) != {
        "schema_version",
        "translated_text",
        "warnings",
    }:
        raise RuntimeError("QUALITY_PROVIDER_RESPONSE_INVALID")
    translated = value.get("translated_text")
    warnings = value.get("warnings")
    if (
        value.get("schema_version") != "1.0.0"
        or not isinstance(translated, str)
        or not translated
        or not isinstance(warnings, list)
        or not all(isinstance(item, str) for item in cast(list[object], warnings))
        or "MACHINE_TRANSLATION_UNVERIFIED" not in warnings
    ):
        raise RuntimeError("QUALITY_PROVIDER_RESPONSE_INVALID")
    return translated, tuple(cast(list[str], warnings))


def strings(value: object) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError("QUALITY_CORPUS_INVALID")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise RuntimeError("QUALITY_CORPUS_INVALID")
    return cast(list[str], items)


def literal_failures(case: dict[str, Any], translated: str) -> list[str]:
    raw_checks: object = case.get("checks", {})
    if not isinstance(raw_checks, dict):
        raise RuntimeError("QUALITY_CORPUS_INVALID")
    checks = cast(dict[str, Any], raw_checks)
    failures = [
        f"missing:{value}"
        for value in strings(checks.get("required", []))
        if value not in translated
    ]
    failures.extend(
        f"added:{value}"
        for value in strings(checks.get("forbidden", []))
        if value.casefold() in translated.casefold()
    )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--raw-output",
        type=Path,
        help="Optionally save opaque requests/responses for the repository corpus only",
    )
    args = parser.parse_args()
    if re.fullmatch(r"ghcr\.io/[a-z0-9_./-]+@sha256:[0-9a-f]{64}", args.image) is None:
        raise RuntimeError("QUALITY_IMAGE_DIGEST_REQUIRED")

    cases = objects(CORPUS)
    if len(cases) != 20 or any(not isinstance(case.get("id"), str) for case in cases):
        raise RuntimeError("QUALITY_CORPUS_INVALID")

    results: list[dict[str, Any]] = []
    raw_results: list[dict[str, Any]] = []
    started = time.monotonic()

    def save(status: str) -> None:
        evidence = {
            "schema_version": 3,
            "status": status,
            "image": args.image,
            "corpus_sha256": file_digest(CORPUS),
            "case_count": len(results),
            "expected_case_count": len(cases),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "semantic_review": "REQUIRED_SEPARATELY",
            "results": results,
        }
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if args.raw_output is not None:
            args.raw_output.write_text(
                json.dumps(raw_results, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    save("RUNNING")
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str):
            raise RuntimeError("QUALITY_CORPUS_INVALID")
        case_started = time.monotonic()
        try:
            translated, warnings = translate(args.socket, case)
        except (OSError, RuntimeError, ValueError):
            results.append({"case_id": case_id, "status": "FAILED"})
            save("FAIL")
            raise
        failures = literal_failures(case, translated)
        results.append(
            {
                "case_id": case_id,
                "status": "FAIL" if failures else "PASS",
                "elapsed_seconds": round(time.monotonic() - case_started, 3),
                "output_sha256": hashlib.sha256(translated.encode()).hexdigest(),
                "warnings": list(warnings),
                "failures": failures,
            }
        )
        raw_results.append(
            {
                "case_id": case_id,
                "request": {
                    "schema_version": "1.0.0",
                    "source_language": case["source"],
                    "target_language": case["target"],
                    "text": case["text"],
                },
                "response": {
                    "schema_version": "1.0.0",
                    "translated_text": translated,
                    "warnings": list(warnings),
                },
                "expected_meaning": case.get("meaning"),
            }
        )
        save("FAIL" if failures else "RUNNING")
        if failures:
            details = ",".join(failures)
            raise RuntimeError(f"QUALITY_LITERAL_FAILURE:{case_id}:{details}")
        print(f"QUALITY_PASS:{case_id}", flush=True)

    save("PASS")
    print("QUALITY_SMOKE_PASS", flush=True)


if __name__ == "__main__":
    main()
