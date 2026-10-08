"""Historical base-screening benchmark; retained only for reproducibility."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import cast

from base_screening.document_text import detect_search_text_language
from base_screening.translation import (
    SubjectProfileTranslator,
    load_subject_profile_translator,
)


def benchmark_translations(
    *,
    manifest_path: Path,
    references_path: Path,
    translator: SubjectProfileTranslator,
) -> dict[str, object]:
    manifest = _object(manifest_path)
    references = _object(references_path)
    if manifest.get("schema_version") != "2.3.0":
        raise ValueError("real-page manifest version is invalid")
    if references.get("schema_version") != "1.0.0":
        raise ValueError("translation reference version is invalid")
    raw_cases = manifest.get("cases")
    raw_references = references.get("cases")
    if not isinstance(raw_cases, list) or not isinstance(raw_references, dict):
        raise ValueError("translation benchmark inputs are invalid")
    cases: dict[str, dict[str, object]] = {}
    for raw in cast(list[object], raw_cases):
        if not isinstance(raw, dict):
            raise ValueError("real-page case is invalid")
        case = cast(dict[str, object], raw)
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or case_id in cases:
            raise ValueError("real-page case identifier is invalid")
        cases[case_id] = case

    results: list[dict[str, object]] = []
    started_all = time.perf_counter()
    for case_id, raw_reference in sorted(
        cast(dict[str, object], raw_references).items()
    ):
        case = cases.get(case_id)
        if case is None or not isinstance(raw_reference, dict):
            raise ValueError(f"translation reference {case_id} is invalid")
        reference = cast(dict[str, object], raw_reference)
        languages = case.get("expected_languages")
        language_items = (
            cast(list[object], languages) if isinstance(languages, list) else []
        )
        if (
            not isinstance(languages, list)
            or len(language_items) != 1
            or not isinstance(language_items[0], str)
            or language_items[0] == "en"
        ):
            raise ValueError(f"translation target for {case_id} is invalid")
        target_language = language_items[0]
        profile = {
            field: case[field]
            for field in (
                "subject_area",
                "positive_terms",
                "excluded_terms",
                "excluded_topics",
            )
        }
        started = time.perf_counter()
        localized = translator.localize(
            profile,
            source_language="en",
            target_language=target_language,
        )
        duration = round((time.perf_counter() - started) * 1000, 3)
        field_matches = {
            field: localized.localized_profile.get(field) == expected
            for field, expected in reference.items()
        }
        detected_languages, language_confidence = detect_search_text_language(
            _profile_text(localized.localized_profile)
        )
        results.append(
            {
                "case_id": case_id,
                "target_language": target_language,
                "duration_milliseconds": duration,
                "source_profile": profile,
                "reference_profile": reference,
                "localized_profile": localized.localized_profile,
                "field_exact_matches": field_matches,
                "detected_languages": list(detected_languages),
                "language_confidence": language_confidence,
                "target_language_detected": target_language in detected_languages,
                "request": localized.request_payload,
                "response": localized.response_payload,
                "localization_ref": localized.localization_ref,
            }
        )
    durations = [cast(float, item["duration_milliseconds"]) for item in results]
    exact_fields = sum(
        bool(value)
        for result in results
        for value in cast(dict[str, object], result["field_exact_matches"]).values()
    )
    total_fields = sum(
        len(cast(dict[str, object], result["field_exact_matches"]))
        for result in results
    )
    detected_targets = sum(
        cast(bool, result["target_language_detected"]) for result in results
    )
    return {
        "schema_version": "1.0.0",
        "translator": translator.summary(),
        "manifest_sha256": _sha256(manifest_path),
        "references_sha256": _sha256(references_path),
        "case_count": len(results),
        "wall_milliseconds": round((time.perf_counter() - started_all) * 1000, 3),
        "timing": {
            "mean_milliseconds": round(statistics.fmean(durations), 3),
            "minimum_milliseconds": min(durations),
            "maximum_milliseconds": max(durations),
        },
        "exact_reference_fields": exact_fields,
        "reference_field_count": total_fields,
        "target_language_detected_cases": detected_targets,
        "results": results,
    }


def _profile_text(profile: dict[str, object]) -> str:
    values = [cast(str, profile["subject_area"])]
    for field in ("positive_terms", "excluded_terms", "excluded_topics"):
        values.extend(cast(list[str], profile[field]))
    return " ".join(values)


def _object(path: Path) -> dict[str, object]:
    value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: document must be an object")
    return cast(dict[str, object], value)


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("references", type=Path)
    parser.add_argument("--translator-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = benchmark_translations(
        manifest_path=arguments.manifest,
        references_path=arguments.references,
        translator=load_subject_profile_translator(
            str(arguments.translator_config), validate_response_language=False
        ),
    )
    _write_report(arguments.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
