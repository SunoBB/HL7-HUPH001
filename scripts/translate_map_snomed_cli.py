import argparse
import json
import os
import re
import sys
from typing import Any

import requests


SNOMED_BASE_URL = os.getenv("SNOMED_BASE_URL", "http://localhost:8080").rstrip("/")
SNOMED_BRANCH = os.getenv("SNOMED_BRANCH", "MAIN")
SNOMED_SEARCH_LIMIT = int(os.getenv("SNOMED_SEARCH_LIMIT", "5"))
SNOMED_TIMEOUT = int(os.getenv("SNOMED_TIMEOUT", "20"))

GLOSSARY: dict[str, str] = {
    "bệnh nhân": "patient",
    "đau ngực": "chest pain",
    "khó thở": "shortness of breath",
    "sốt": "fever",
    "ho": "cough",
    "ho khạc đờm": "productive cough",
    "đờm vàng": "yellow sputum",
    "tăng huyết áp": "hypertension",
    "đái tháo đường": "diabetes mellitus",
    "đái tháo đường type 2": "type 2 diabetes mellitus",
    "tiền sử": "history of",
    "viêm phổi": "pneumonia",
    "nhập viện": "hospitalized",
    "đau bụng": "abdominal pain",
    "buồn nôn": "nausea",
    "nôn": "vomiting",
    "mệt mỏi": "fatigue",
    "nhịp tim nhanh": "tachycardia",
    "suy tim": "heart failure",
    "đột quỵ": "stroke",
    "hen phế quản": "asthma",
    "bệnh phổi tắc nghẽn mạn tính": "chronic obstructive pulmonary disease",
    "copd": "chronic obstructive pulmonary disease",
}

STOP_TERMS = {
    "bệnh nhân",
    "patient",
    "history of",
    "hospitalized",
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def sentence_case(text: str) -> str:
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    if text and text[-1] not in ".!?":
        text += "."
    return text


def simple_medical_translation(text: str) -> str:
    translated = text.strip()
    for vi, en in sorted(GLOSSARY.items(), key=lambda item: len(item[0]), reverse=True):
        translated = re.sub(re.escape(vi), en, translated, flags=re.IGNORECASE)
    return sentence_case(translated)


def extract_candidates(text: str) -> list[tuple[str, str]]:
    normalized = normalize_text(text)
    found: list[tuple[str, str]] = []

    for vi, en in sorted(GLOSSARY.items(), key=lambda item: len(item[0]), reverse=True):
        if vi in normalized and vi not in STOP_TERMS:
            found.append((vi, en))

    if not found:
        fallback = simple_medical_translation(text).rstrip(".").strip()
        if fallback:
            found.append((text.strip(), fallback))

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in found:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def get_nested_str(data: dict[str, Any], *paths: tuple[str, ...]) -> str | None:
    for path in paths:
        current: Any = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        if isinstance(current, str) and current.strip():
            return current
    return None


def search_snomed_descriptions(term: str) -> dict[str, Any]:
    response = requests.get(
        f"{SNOMED_BASE_URL}/browser/{SNOMED_BRANCH}/descriptions",
        params={
            "term": term,
            "limit": SNOMED_SEARCH_LIMIT,
            "active": "true",
            "conceptActive": "true",
            "lang": "english",
        },
        timeout=SNOMED_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def fetch_concept(concept_id: str) -> dict[str, Any] | None:
    response = requests.get(
        f"{SNOMED_BASE_URL}/browser/{SNOMED_BRANCH}/concepts/{concept_id}",
        timeout=SNOMED_TIMEOUT,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def build_mapping(matched_text_vi: str, translated_term_en: str) -> dict[str, Any]:
    result = {
        "matched_text_vi": matched_text_vi,
        "translated_term_en": translated_term_en,
        "concept_id": None,
        "preferred_term": None,
        "fully_specified_name": None,
        "semantic_tag": None,
        "module_id": None,
        "found": False,
        "raw_result_count": 0,
    }

    data = search_snomed_descriptions(translated_term_en)
    items = data.get("items") or []
    result["raw_result_count"] = len(items)
    if not items:
        return result

    first = items[0]
    concept_id = (
        get_nested_str(first, ("conceptId",), ("concept", "conceptId"), ("concept", "id"))
        or get_nested_str(first, ("referencedComponentId",))
    )
    if not concept_id:
        return result

    concept = fetch_concept(concept_id) or {}
    result["concept_id"] = concept_id
    result["preferred_term"] = get_nested_str(
        concept,
        ("pt", "term"),
        ("preferredTerm",),
        ("fsn", "term"),
    ) or get_nested_str(first, ("term",))
    result["fully_specified_name"] = get_nested_str(concept, ("fsn", "term"))
    result["semantic_tag"] = get_nested_str(concept, ("fsn", "semanticTag"))
    result["module_id"] = get_nested_str(concept, ("moduleId",))
    result["found"] = True
    return result


def map_terms_to_snomed(candidates: list[tuple[str, str]]) -> tuple[list[dict[str, Any]], bool, str | None]:
    mappings: list[dict[str, Any]] = []
    snomed_ready = True
    snomed_message = None

    for vi_term, en_term in candidates:
        try:
            mappings.append(build_mapping(vi_term, en_term))
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            snomed_ready = False
            snomed_message = f"SNOMED search failed with HTTP {status_code}."
            mappings.append(
                {
                    "matched_text_vi": vi_term,
                    "translated_term_en": en_term,
                    "found": False,
                    "error": snomed_message,
                }
            )
        except requests.RequestException as exc:
            snomed_ready = False
            snomed_message = f"SNOMED backend unavailable: {exc}"
            mappings.append(
                {
                    "matched_text_vi": vi_term,
                    "translated_term_en": en_term,
                    "found": False,
                    "error": snomed_message,
                }
            )

    return mappings, snomed_ready, snomed_message


def read_input(args: argparse.Namespace) -> str:
    if args.text:
        return args.text.strip()
    if args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise ValueError("Provide --text, --file, or pipe input via stdin.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate Vietnamese medical text and map extracted terms to SNOMED CT."
    )
    parser.add_argument("--text", help="Vietnamese clinical text.")
    parser.add_argument("--file", help="Path to a UTF-8 text file.")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        source_text = read_input(args)
        if not source_text:
            raise ValueError("Input text is empty.")
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    translation = simple_medical_translation(source_text)
    candidates = extract_candidates(source_text)
    mappings, snomed_ready, snomed_message = map_terms_to_snomed(candidates)

    payload = {
        "source_text": source_text,
        "translation": translation,
        "extracted_terms": [item[0] for item in candidates],
        "mappings": mappings,
        "snomed_ready": snomed_ready,
        "snomed_message": snomed_message,
        "snomed_base_url": SNOMED_BASE_URL,
        "snomed_branch": SNOMED_BRANCH,
    }

    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
