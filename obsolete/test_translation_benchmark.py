"""Historical benchmark fixture; excluded from active service tests."""

import json
from pathlib import Path

from base_screening.translation import EvidenceTranslation, ProfileLocalization
from base_screening.translation_benchmark import benchmark_translations


class _Translator:
    def summary(self) -> dict[str, object]:
        return {"status": "CONFIGURED", "translator_ref": "test@sha256"}

    def localize(
        self,
        profile: dict[str, object],
        *,
        source_language: str,
        target_language: str,
    ) -> ProfileLocalization:
        assert source_language == "en"
        assert target_language == "es"
        localized: dict[str, object] = {
            "subject_area": "finanzas",
            "positive_terms": ["banco central"],
            "excluded_terms": ["pornografía"],
            "excluded_topics": ["juegos de azar"],
        }
        return ProfileLocalization(
            translator_ref="test@sha256",
            localized_profile=localized,
            localization_ref="sha256:" + "a" * 64,
            request_payload={"profile": profile},
            response_payload={"profile": localized},
        )

    def translate_evidence(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> EvidenceTranslation:
        del text, source_language, target_language
        raise AssertionError("benchmark must not translate operator evidence")


def test_benchmark_preserves_raw_exchange_and_reference_result(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    references = tmp_path / "references.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "2.3.0",
                "cases": [
                    {
                        "case_id": "finance-es",
                        "expected_languages": ["es"],
                        "subject_area": "finance",
                        "positive_terms": ["central bank"],
                        "excluded_terms": ["porn"],
                        "excluded_topics": ["gambling"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    references.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "cases": {
                    "finance-es": {
                        "subject_area": "finanzas",
                        "positive_terms": ["banco central"],
                        "excluded_topics": ["juegos de azar"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    report = benchmark_translations(
        manifest_path=manifest,
        references_path=references,
        translator=_Translator(),
    )

    assert report["case_count"] == 1
    assert report["exact_reference_fields"] == 3
    assert report["target_language_detected_cases"] in {0, 1}
    result = report["results"][0]  # type: ignore[index]
    assert result["request"] == {
        "profile": {  # type: ignore[index]
            "subject_area": "finance",
            "positive_terms": ["central bank"],
            "excluded_terms": ["porn"],
            "excluded_topics": ["gambling"],
        }
    }
