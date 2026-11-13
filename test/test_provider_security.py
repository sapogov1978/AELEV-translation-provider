"""Security admission rejects unreviewed findings and incomplete evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "sha256:" + "1" * 64
Assess = Callable[[dict[str, Any], str, list[object], Path], dict[str, object]]
spec = importlib.util.spec_from_file_location(
    "provider_security_under_test", ROOT / "tools/provider_security.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assess = cast(Assess, module.assess_scan)


@pytest.fixture
def evidence(tmp_path: Path) -> tuple[Path, dict[str, Any], list[object]]:
    source = tmp_path / "src/demo/__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text('"""Bounded source fixture."""\n')
    (tmp_path / "poetry.lock").write_text("fixture lock\n")
    (tmp_path / "provider.lock.json").write_text("{}\n")
    gate_sources: dict[str, str] = {}
    (tmp_path / "tools").mkdir()
    for name in ("provider_security.py", "runtime_surface_probe.py"):
        data = (ROOT / "tools" / name).read_bytes()
        (tmp_path / "tools" / name).write_bytes(data)
        gate_sources["tools/" + name] = hashlib.sha256(data).hexdigest()
    dependencies = {name: "test" for name in ("fastapi", "httpx", "uvicorn")}
    source_hashes = {
        "src/demo/__init__.py": hashlib.sha256(source.read_bytes()).hexdigest()
    }
    profile = {
        "schema_version": 1,
        "profile": "opaque-python-provider-bookworm-v1",
        "python_version": "3.13.7",
        "runtime_dependencies": dependencies,
        "application_sources_sha256": source_hashes,
        "gate_sources_sha256": gate_sources,
        "dependency_lock_sha256": hashlib.sha256(
            (tmp_path / "poetry.lock").read_bytes()
        ).hexdigest(),
        "provider_lock_sha256": hashlib.sha256(
            (tmp_path / "provider.lock.json").read_bytes()
        ).hexdigest(),
    }
    (tmp_path / "security").mkdir()
    (tmp_path / "security/runtime-profile.json").write_text(json.dumps(profile))
    scan: dict[str, Any] = {
        "SchemaVersion": 2,
        "Metadata": {"ImageID": IMAGE, "OS": {"Family": "debian", "Name": "12.15"}},
        "Results": [
            {
                "Type": "debian",
                "Packages": [{"Name": "gzip", "Version": "1.12"}],
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-2026-41992",
                        "PkgName": "gzip",
                        "InstalledVersion": "1.12",
                        "Severity": "HIGH",
                    }
                ],
            },
            {
                "Type": "python-pkg",
                "Packages": [
                    {"Name": name, "Version": "test"}
                    for name in ("fastapi", "httpx", "uvicorn")
                ],
            },
        ],
    }
    probes: list[object] = []
    for index in range(2):
        probes.append(
            {
                "python_version": "3.13.7",
                "build_tools_absent": True,
                "sqlite_library_absent": True,
                "minizip_library_and_vulnerable_symbol_absent": True,
                "systemd_homed_absent": True,
                "execution": {
                    "profile": "opaque-python-provider-bookworm-v1",
                    "runtime_dependencies": dependencies,
                    "uid": 10001,
                    "capabilities_effective": 0,
                    "forbidden_native_imports": [],
                    "native_files_sha256": {"/fixture/native.so": "0" * 64},
                    "engine_definitions_imported": index == 1,
                    "application_process_and_dynamic_native_apis_absent": True,
                    "acl_and_blk_id_libraries_not_loaded": True,
                    "perl_archive_tar_absent": True,
                    "empty_fstab": True,
                    "known_compromised_ca_roots_absent": True,
                    "no_new_privileges": True,
                    "read_only_root": True,
                    "application_sources_sha256": {
                        "src/demo/__init__.py": hashlib.sha256(
                            source.read_bytes()
                        ).hexdigest()
                    },
                },
            }
        )
    return tmp_path, scan, probes


def test_specific_review_keeps_raw_finding_visible(evidence: Any) -> None:
    root, scan, probes = evidence
    result = assess(scan, IMAGE, probes, root)
    assert result["status"] == "SCOPED_SECURITY_PASS"
    assert result["raw_severity_counts"] == {"HIGH": 1}
    assert result["unresolved_high_critical_package_findings"] == 0


def test_new_cve_blocks_admission(evidence: Any) -> None:
    root, scan, probes = evidence
    scan["Results"][0]["Vulnerabilities"][0]["VulnerabilityID"] = "CVE-2099-99999"
    result = assess(scan, IMAGE, probes, root)
    assert result["status"] == "SECURITY_BLOCKED"
    assert result["unresolved_high_critical_package_findings"] == 1


@pytest.mark.parametrize("present", [False, None])
def test_tls_trust_proof_is_required_for_scoped_admission(
    evidence: Any, present: bool | None
) -> None:
    root, scan, probes = evidence
    if present is None:
        probes[0]["execution"].pop("known_compromised_ca_roots_absent")
    else:
        probes[0]["execution"]["known_compromised_ca_roots_absent"] = present
    with pytest.raises(ValueError, match="SECURITY_EXECUTION_PROOF_INCOMPLETE"):
        assess(scan, IMAGE, probes, root)


def test_debian_review_does_not_cover_a_python_package(evidence: Any) -> None:
    root, scan, probes = evidence
    scan["Results"][1]["Vulnerabilities"] = scan["Results"][0].pop("Vulnerabilities")
    assert assess(scan, IMAGE, probes, root)["status"] == "SECURITY_BLOCKED"


def test_wrong_image_scan_is_rejected(evidence: Any) -> None:
    root, scan, probes = evidence
    scan["Metadata"]["ImageID"] = "sha256:" + "2" * 64
    with pytest.raises(ValueError, match="SECURITY_SCAN_IMAGE_MISMATCH"):
        assess(scan, IMAGE, probes, root)


def test_empty_inventory_is_rejected(evidence: Any) -> None:
    root, scan, probes = evidence
    scan["Results"] = []
    with pytest.raises(ValueError, match="SECURITY_SCAN_INCOMPLETE"):
        assess(scan, IMAGE, probes, root)


def test_missing_python_inventory_is_rejected(evidence: Any) -> None:
    root, scan, probes = evidence
    scan["Results"][1]["Packages"] = []
    with pytest.raises(ValueError, match="SECURITY_PYTHON_INVENTORY_INCOMPLETE"):
        assess(scan, IMAGE, probes, root)


def test_missing_runtime_control_is_rejected(evidence: Any) -> None:
    root, scan, probes = evidence
    probes[1]["execution"]["no_new_privileges"] = False
    with pytest.raises(ValueError, match="SECURITY_EXECUTION_PROOF_INCOMPLETE"):
        assess(scan, IMAGE, probes, root)


def test_source_mismatch_is_rejected(evidence: Any) -> None:
    root, scan, probes = evidence
    (root / "src/demo/__init__.py").write_text("changed = True\n")
    with pytest.raises(ValueError, match="SECURITY_APPLICATION_REVIEW_REQUIRED"):
        assess(scan, IMAGE, probes, root)


def test_image_source_mismatch_is_rejected(evidence: Any) -> None:
    root, scan, probes = evidence
    probes[1]["execution"]["application_sources_sha256"] = {}
    with pytest.raises(ValueError, match="SECURITY_SOURCE_IMAGE_MISMATCH"):
        assess(scan, IMAGE, probes, root)


def test_dependency_change_requires_review(evidence: Any) -> None:
    root, scan, probes = evidence
    (root / "poetry.lock").write_text("different lock\n")
    with pytest.raises(ValueError, match="SECURITY_DEPENDENCY_REVIEW_REQUIRED"):
        assess(scan, IMAGE, probes, root)


def test_gate_change_requires_review(evidence: Any) -> None:
    root, scan, probes = evidence
    (root / "tools/provider_security.py").write_text("changed = True\n")
    with pytest.raises(ValueError, match="SECURITY_GATE_REVIEW_REQUIRED"):
        assess(scan, IMAGE, probes, root)
