import os
import re
from typing import Any

import requests
from fastapi import FastAPI
from pydantic import BaseModel, Field


SNOMED_BASE_URL = os.getenv("SNOMED_BASE_URL", "http://localhost:8080").rstrip("/")
SNOMED_BRANCH = os.getenv("SNOMED_BRANCH", "MAIN")
SNOMED_SEARCH_LIMIT = int(os.getenv("SNOMED_SEARCH_LIMIT", "5"))
SNOMED_TIMEOUT = int(os.getenv("SNOMED_TIMEOUT", "20"))

app = FastAPI(title="Medical Translation And SNOMED Mapping Backend")


class TranslationRequest(BaseModel):
    text: str
    source_language: str = "vi"
    target_language: str = "en-med"
    domain: str = "medical"
    instruction: str | None = None


class SnomedMapping(BaseModel):
    matched_text_vi: str
    translated_term_en: str
    concept_id: str | None = None
    preferred_term: str | None = None
    fully_specified_name: str | None = None
    semantic_tag: str | None = None
    module_id: str | None = None
    found: bool = False
    raw_result_count: int = 0


class TranslationResponse(BaseModel):
    translation: str
    extracted_terms: list[str] = Field(default_factory=list)
    mappings: list[SnomedMapping] = Field(default_factory=list)
    snomed_ready: bool = True
    snomed_message: str | None = None


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
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


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


def build_mapping(matched_text_vi: str, translated_term_en: str) -> SnomedMapping:
    data = search_snomed_descriptions(translated_term_en)
    items = data.get("items") or []
    mapping = SnomedMapping(
        matched_text_vi=matched_text_vi,
        translated_term_en=translated_term_en,
        raw_result_count=len(items),
    )

    if not items:
        return mapping

    first = items[0]
    concept_id = (
        get_nested_str(first, ("conceptId",), ("concept", "conceptId"), ("concept", "id"))
        or get_nested_str(first, ("referencedComponentId",))
    )
    if not concept_id:
        return mapping

    concept = fetch_concept(concept_id) or {}
    mapping.concept_id = concept_id
    mapping.preferred_term = get_nested_str(
        concept,
        ("pt", "term"),
        ("preferredTerm",),
        ("fsn", "term"),
    ) or get_nested_str(first, ("term",))
    mapping.fully_specified_name = get_nested_str(concept, ("fsn", "term"))
    mapping.semantic_tag = get_nested_str(concept, ("fsn", "semanticTag"))
    mapping.module_id = get_nested_str(concept, ("moduleId",))
    mapping.found = True
    return mapping


def map_terms_to_snomed(candidates: list[tuple[str, str]]) -> tuple[list[SnomedMapping], bool, str | None]:
    mappings: list[SnomedMapping] = []
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
                SnomedMapping(
                    matched_text_vi=vi_term,
                    translated_term_en=en_term,
                    found=False,
                )
            )
        except requests.RequestException as exc:
            snomed_ready = False
            snomed_message = f"SNOMED backend unavailable: {exc}"
            mappings.append(
                SnomedMapping(
                    matched_text_vi=vi_term,
                    translated_term_en=en_term,
                    found=False,
                )
            )

    return mappings, snomed_ready, snomed_message


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/translate", response_model=TranslationResponse)
def translate(request: TranslationRequest) -> TranslationResponse:
    translation = simple_medical_translation(request.text)
    candidates = extract_candidates(request.text)
    mappings, snomed_ready, snomed_message = map_terms_to_snomed(candidates)

    return TranslationResponse(
        translation=translation,
        extracted_terms=[item[0] for item in candidates],
        mappings=mappings,
        snomed_ready=snomed_ready,
        snomed_message=snomed_message,
    )
