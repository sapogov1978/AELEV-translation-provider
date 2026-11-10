"""Image-local evidence for the provider's restricted Python execution profile."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, cast

EXECUTION_PROBE = r"""
import ast
import hashlib
import importlib
import importlib.metadata
import os
import re
import struct
import zlib as python_zlib

source_root = Path("/opt/aelev/src")
packages = [
    p for p in source_root.iterdir() if p.is_dir() and p.name.startswith("aelev_")
]
assert len(packages) == 1, "PROVIDER_SOURCE_LAYOUT_CHANGED"
package = packages[0]
source_files = {}
for path in sorted(package.rglob("*.py")):
    raw = path.read_bytes()
    source_files[str(Path("src") / path.relative_to(source_root))] = hashlib.sha256(
        raw
    ).hexdigest()
    tree = ast.parse(raw, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            names = []
        assert not set(names) & {
            "ctypes",
            "_ctypes",
            "subprocess",
            "_posixsubprocess",
            "pty",
            "pexpect",
            "importlib",
            "builtins",
            "posix",
        }, "APPLICATION_EXECUTION_PATH_REQUIRES_REVIEW"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "compile", "__import__"}, (
                    "APPLICATION_DYNAMIC_EXECUTION_REQUIRES_REVIEW"
                )
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {
                    "system",
                    "popen",
                    "fork",
                    "forkpty",
                    "posix_spawn",
                    "posix_spawnp",
                    "execv",
                    "execve",
                    "execvp",
                    "execvpe",
                    "execl",
                    "execle",
                    "execlp",
                    "execlpe",
                    "spawnl",
                    "spawnle",
                    "spawnlp",
                    "spawnlpe",
                    "spawnv",
                    "spawnve",
                    "spawnvp",
                    "spawnvpe",
                }, "APPLICATION_PROCESS_EXECUTION_REQUIRES_REVIEW"
assert source_files
# Import definitions, never construct settings, initialize a key or call inference.
if sys.executable.startswith("/opt/aelev/.venv/"):
    importlib.import_module(package.name + ".engine")

status = dict(
    line.split(":", 1)
    for line in Path("/proc/self/status").read_text().splitlines()
    if ":" in line
)
assert os.geteuid() == 10001 and os.getuid() == 10001
assert int(status["CapEff"].strip(), 16) == 0
assert status["NoNewPrivs"].strip() == "1"
assert os.statvfs("/").f_flag & os.ST_RDONLY
assert not [
    line
    for line in Path("/etc/fstab").read_text().splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]
os_release = dict(
    line.split("=", 1)
    for line in Path("/etc/os-release").read_text().splitlines()
    if "=" in line
)
assert (
    os_release["ID"].strip('"') == "debian"
    and os_release["VERSION_ID"].strip('"') == "12"
)
assert not list(Path("/usr").glob("**/Archive/Tar.pm"))
assert not list(Path("/usr/local/lib").glob("**/libminizip.so*"))
loaded = {
    line.split()[-1]
    for line in Path("/proc/self/maps").read_text().splitlines()
    if len(line.split()) >= 6 and line.split()[-1].startswith("/")
}
assert not any("libacl.so" in name or "libblkid.so" in name for name in loaded)
native = {
    p.resolve() for p in Path("/usr/local/lib/python3.13/lib-dynload").glob("*.so")
}
native.update(p.resolve() for p in Path("/opt/aelev/.venv").rglob("*.so"))
native.update(p.resolve() for p in Path("/usr/local/lib").glob("libpython3.13.so*"))
native.update(Path(name).resolve() for name in loaded if ".so" in name)
assert 1 <= len(native) <= 512
undefined = set()
native_hashes = {}
for path in sorted(native):
    data = path.read_bytes()
    assert len(data) <= 67108864 and data[:6] == bytes([127, 69, 76, 70, 2, 1]), (
        "NATIVE_FORMAT_REQUIRES_REVIEW"
    )
    native_hashes[str(path)] = hashlib.sha256(data).hexdigest()
    table_offset = struct.unpack_from("<Q", data, 40)[0]
    entry_size, count = struct.unpack_from("<HH", data, 58)
    assert entry_size == 64 and 0 < count <= 4096
    sections = [
        struct.unpack_from("<IIQQQQIIQQ", data, table_offset + i * entry_size)
        for i in range(count)
    ]
    for section in sections:
        if section[1] != 11:
            continue
        offset, size, link, symbol_size = section[4], section[5], section[6], section[9]
        assert symbol_size == 24 and size % symbol_size == 0 and link < len(sections)
        strings = sections[link]
        names = data[strings[4] : strings[4] + strings[5]]
        for at in range(offset, offset + size, symbol_size):
            name_offset, _, _, index, _, _ = struct.unpack_from("<IBBHQQ", data, at)
            if index == 0 and name_offset:
                end = names.find(bytes([0]), name_offset)
                assert end >= name_offset
                undefined.add(names[name_offset:end].decode("ascii"))
forbidden = sorted(
    name
    for name in undefined
    if name.startswith(
        (
            "blkid_",
            "acl_get_file",
            "acl_set_file",
            "acl_extended_file",
            "acl_delete_def_file",
            "gz",
        )
    )
)
assert not forbidden, "NATIVE_EXECUTION_PATH_REQUIRES_REVIEW"
execution_evidence = {
    "profile": "opaque-python-provider-bookworm-v1",
    "package": package.name,
    "application_sources_sha256": source_files,
    "application_process_and_dynamic_native_apis_absent": True,
    "native_files_sha256": native_hashes,
    "forbidden_native_imports": forbidden,
    "native_symbols_sha256": hashlib.sha256(
        json.dumps(sorted(undefined)).encode()
    ).hexdigest(),
    "acl_and_blk_id_libraries_not_loaded": True,
    "perl_archive_tar_absent": True,
    "empty_fstab": True,
    "uid": os.getuid(),
    "capabilities_effective": 0,
    "no_new_privileges": True,
    "read_only_root": True,
    "distribution": "debian-12",
    "zlib_runtime_version": python_zlib.ZLIB_RUNTIME_VERSION,
    "engine_definitions_imported": sys.executable.startswith("/opt/aelev/.venv/"),
    "runtime_dependencies": {
        d.metadata["Name"].lower().replace("_", "-").replace(".", "-"): d.version
        for d in importlib.metadata.distributions(
            path=["/opt/aelev/.venv/lib/python3.13/site-packages"]
        )
    },
}
"""

_UTIL = {
    "bsdutils",
    "libblkid1",
    "libmount1",
    "libsmartcols1",
    "libuuid1",
    "mount",
    "util-linux",
    "util-linux-extra",
}
_RULES: dict[str, tuple[set[str], str, str]] = {
    "CVE-2023-45853": (
        {"zlib1g"},
        "vulnerable_code_not_present",
        "MiniZip, pyminizip and the vulnerable MiniZip export are absent.",
    ),
    "CVE-2026-16742": (
        {"libsystemd0", "libudev1"},
        "vulnerable_code_not_present",
        "The affected systemd-homed executable is absent.",
    ),
    "CVE-2026-9538": (
        {"perl-base"},
        "vulnerable_code_not_present",
        "The affected Perl Archive::Tar module is absent from the image.",
    ),
    "CVE-2026-53613": (
        _UTIL,
        "protected_by_mitigating_control",
        "No fstab mount entries; UID 10001, zero effective capabilities, "
        "no-new-privileges, read-only root and no application child-process APIs.",
    ),
    "CVE-2026-78410": (
        _UTIL,
        "protected_by_mitigating_control",
        "No fstab bind-mount entries or privileged mount path "
        "under the verified profile.",
    ),
    "CVE-2026-53615": (
        _UTIL,
        "vulnerable_code_not_in_execute_path",
        "Provider processes no block-device metadata; libblkid is not loaded, "
        "application/native imports contain no blkid path "
        "or dynamic native/process APIs.",
    ),
    "CVE-2026-41992": (
        {"gzip"},
        "vulnerable_code_not_in_execute_path",
        "The affected GNU gzip LZW/LZH CLI is never executed by this provider. "
        "Application source is reviewed and excludes process invocation.",
    ),
    "CVE-2025-69720": (
        {"ncurses-base", "ncurses-bin", "libncursesw6", "libtinfo6"},
        "vulnerable_code_not_in_execute_path",
        "The affected infocmp CLI analyze_string path "
        "is never executed by the provider.",
    ),
    "CVE-2026-54369": (
        {"libacl1"},
        "vulnerable_code_not_in_execute_path",
        "No privileged ACL caller; libacl is not loaded and application/native "
        "imports contain no affected ACL or dynamic native/process APIs.",
    ),
    "CVE-2026-76844": (
        {"zlib1g"},
        "vulnerable_code_not_in_execute_path",
        "The provider does not call the affected gz* file-write API. Reviewed "
        "application sources exclude dynamic native/process APIs and native imports "
        "contain no gzopen/gzdopen/gzwrite/gzprintf/gzvprintf/gzclearerr.",
    ),
    "CVE-2026-85091": (
        {"zlib1g"},
        "vulnerable_code_not_in_execute_path",
        "The affected gz* file-write API has no provider execution path, regardless "
        "of the upstream/table affected-version discrepancy.",
    ),
}


def validate_review(probes: list[object], root: Path) -> str:
    """Require the exact manually reviewed source, dependency and gate manifests."""
    path = root / "security/runtime-profile.json"
    profile = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    if (
        profile.get("schema_version") != 1
        or profile.get("profile") != "opaque-python-provider-bookworm-v1"
        or set(profile.get("gate_sources_sha256", {}))
        != {"tools/provider_security.py", "tools/runtime_surface_probe.py"}
    ):
        raise ValueError("SECURITY_REVIEW_PROFILE_MISMATCH")
    for name, expected in cast(dict[str, str], profile["gate_sources_sha256"]).items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError("SECURITY_GATE_REVIEW_REQUIRED")
    for name, key in (
        ("poetry.lock", "dependency_lock_sha256"),
        ("provider.lock.json", "provider_lock_sha256"),
    ):
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != profile[key]:
            raise ValueError("SECURITY_DEPENDENCY_REVIEW_REQUIRED")
    expected_sources = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (root / "src").rglob("*.py")
    }
    if (
        not expected_sources
        or expected_sources != profile["application_sources_sha256"]
    ):
        raise ValueError("SECURITY_APPLICATION_REVIEW_REQUIRED")
    if len(probes) != 2:
        raise ValueError("SECURITY_EXECUTION_PROOF_INCOMPLETE")
    for raw in probes:
        proof = cast(dict[str, Any], raw)
        execution = proof["execution"]
        if (
            execution["application_sources_sha256"] != expected_sources
            or proof["python_version"] != profile["python_version"]
            or execution["runtime_dependencies"] != profile["runtime_dependencies"]
        ):
            raise ValueError("SECURITY_SOURCE_IMAGE_MISMATCH")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assess_scan(
    scan: dict[str, Any], image_id: str, probes: list[object], root: Path
) -> dict[str, object]:
    """Apply reviewed CVE-specific scope only to a complete matching image scan."""
    validate_review(probes, root)
    if scan.get("Metadata", {}).get("ImageID") != image_id:
        raise ValueError("SECURITY_SCAN_IMAGE_MISMATCH")
    operating_system = scan.get("Metadata", {}).get("OS", {})
    if (
        scan.get("SchemaVersion") != 2
        or operating_system.get("Family") != "debian"
        or not str(operating_system.get("Name", "")).startswith("12.")
    ):
        raise ValueError("SECURITY_SCAN_PROFILE_MISMATCH")
    raw_results = scan.get("Results")
    if not isinstance(raw_results, list) or not raw_results:
        raise ValueError("SECURITY_SCAN_INCOMPLETE")
    results = cast(list[dict[str, Any]], raw_results)
    if not any(r.get("Type") == "debian" and r.get("Packages") for r in results):
        raise ValueError("SECURITY_SCAN_INCOMPLETE")
    python_packages: set[str] = set()
    for result in results:
        if result.get("Type") == "python-pkg":
            for p in cast(list[dict[str, Any]], result.get("Packages", [])):
                python_packages.add(str(p.get("Name", "")))
    if not {"fastapi", "httpx", "uvicorn"} <= python_packages:
        raise ValueError("SECURITY_PYTHON_INVENTORY_INCOMPLETE")
    if len(probes) != 2:
        raise ValueError("SECURITY_EXECUTION_PROOF_INCOMPLETE")
    for index, raw in enumerate(probes):
        proof = cast(dict[str, Any], raw)
        execution = proof.get("execution", {})
        if (
            execution.get("profile") != "opaque-python-provider-bookworm-v1"
            or execution.get("uid") != 10001
            or execution.get("capabilities_effective") != 0
            or execution.get("forbidden_native_imports") != []
            or not execution.get("native_files_sha256")
            or execution.get("engine_definitions_imported") is not (index == 1)
            or not all(
                execution.get(k) is True
                for k in (
                    "application_process_and_dynamic_native_apis_absent",
                    "acl_and_blk_id_libraries_not_loaded",
                    "perl_archive_tar_absent",
                    "empty_fstab",
                    "no_new_privileges",
                    "read_only_root",
                )
            )
            or not all(
                proof.get(k) is True
                for k in (
                    "build_tools_absent",
                    "sqlite_library_absent",
                    "minizip_library_and_vulnerable_symbol_absent",
                    "systemd_homed_absent",
                )
            )
        ):
            raise ValueError("SECURITY_EXECUTION_PROOF_INCOMPLETE")
        files = cast(dict[str, str], execution.get("application_sources_sha256", {}))
        expected = {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root / "src").rglob("*.py")
        }
        if not expected or files != expected:
            raise ValueError("SECURITY_SOURCE_IMAGE_MISMATCH")
    counts: Counter[str] = Counter()
    findings: list[dict[str, object]] = []
    unresolved = 0
    for result in results:
        for v in cast(list[dict[str, Any]], result.get("Vulnerabilities", [])):
            severity = str(v["Severity"])
            counts[severity] += 1
            if severity not in {"HIGH", "CRITICAL"}:
                continue
            identifier, package = str(v["VulnerabilityID"]), str(v["PkgName"])
            rule = _RULES.get(identifier)
            approved = (
                result.get("Type") == "debian"
                and rule is not None
                and package in rule[0]
            )
            if not approved:
                unresolved += 1
            findings.append(
                {
                    "id": identifier,
                    "package": package,
                    "installed_version": v["InstalledVersion"],
                    "severity": severity,
                    "status": "NOT_AFFECTED_IN_PROFILE" if approved else "OPEN",
                    "justification": rule[1] if approved and rule else None,
                    "reason": rule[2]
                    if approved and rule
                    else "New finding requires review or a fix.",
                    "primary_source": "https://security-tracker.debian.org/tracker/"
                    + identifier
                    if identifier.startswith("CVE-")
                    else v.get("PrimaryURL"),
                }
            )
    return {
        "status": "SCOPED_SECURITY_PASS" if unresolved == 0 else "SECURITY_BLOCKED",
        "raw_severity_counts": dict(sorted(counts.items())),
        "unresolved_high_critical_package_findings": unresolved,
        "findings": findings,
        "scope": "Only the default opaque Python provider entrypoint under the "
        "verified non-root/read-only/no-capabilities/no-new-privileges profile; "
        "not arbitrary OS CLI use.",
        "scan_sha256": hashlib.sha256(
            json.dumps(scan, sort_keys=True).encode()
        ).hexdigest(),
    }
