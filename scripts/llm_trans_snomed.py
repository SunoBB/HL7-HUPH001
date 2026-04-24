import argparse
import json
import logging
import os
import re
import sys
import time
from typing import Any

import ollama
import requests


OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
SNOWSTORM_BASE_URL = os.getenv("SNOWSTORM_BASE_URL", "http://localhost:8080").rstrip("/")
SNOWSTORM_BRANCH = os.getenv("SNOWSTORM_BRANCH", "MAIN")
SNOWSTORM_SEARCH_LIMIT = int(os.getenv("SNOWSTORM_SEARCH_LIMIT", "5"))
SNOWSTORM_TIMEOUT = int(os.getenv("SNOWSTORM_TIMEOUT", "20"))
SNOWSTORM_MAX_RETRIES = int(os.getenv("SNOWSTORM_MAX_RETRIES", "3"))
SNOWSTORM_BACKOFF_BASE = float(os.getenv("SNOWSTORM_BACKOFF_BASE", "1.0"))

KNOWN_MEDICAL_ACRONYMS = {
    "COPD",
    "HIV",
    "GERD",
    "PTSD",
    "ADHD",
    "ALS",
    "IBD",
    "CKD",
    "AKI",
    "CAD",
    "CHF",
    "UTI",
    "URI",
}

logger = logging.getLogger(__name__)

FEW_SHOT_EXAMPLES = """
Example input: "bệnh nhân bị đau ngực và khó thở"
Example output:
{
  "translated_term": "chest pain and dyspnea",
  "normalized_terms": ["chest pain", "dyspnea"],
  "medical_entities": [
    {"text_vi": "đau ngực", "term_en": "chest pain"},
    {"text_vi": "khó thở", "term_en": "dyspnea"}
  ]
}

Example input: "giả dụ người bệnh vào viện với gãy xương đùi"
Example output:
{
  "translated_term": "femur fracture",
  "normalized_terms": ["femur fracture"],
  "medical_entities": [
    {"text_vi": "gãy xương đùi", "term_en": "femur fracture"}
  ]
}
"""

STRICT_RETRY_SUFFIX = """

Validation rules:
- Every medical_entities.text_vi value must be an exact substring copied from the original Vietnamese input.
- Do not reuse entities from the examples unless they literally appear in the input.
- If you are unsure, return an empty medical_entities array rather than hallucinating.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate Vietnamese medical text with Ollama and map it to SNOMED CT via Snowstorm."
    )
    parser.add_argument("--text", help="Vietnamese medical text to process.")
    parser.add_argument("--file", help="Path to a UTF-8 text file containing Vietnamese medical text.")
    parser.add_argument("--model", default=OLLAMA_MODEL, help=f"Ollama model to use. Default: {OLLAMA_MODEL}")
    parser.add_argument(
        "--limit",
        type=int,
        default=SNOWSTORM_SEARCH_LIMIT,
        help=f"Maximum SNOMED description hits to request. Default: {SNOWSTORM_SEARCH_LIMIT}",
    )
    parser.add_argument("--debug", action="store_true", help="Include raw LLM output and candidate mappings.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def read_input(args: argparse.Namespace) -> str:
    if args.text:
        return args.text.strip()
    if args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise ValueError("Provide --text, --file, or pipe input via stdin.")


def get_medical_translation_llm(text_vi: str, model: str) -> dict[str, Any]:
    prompt = build_llm_prompt(text_vi, strict=False)

    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"num_predict": 512, "temperature": 0},
    )
    content = response["message"]["content"]
    result = parse_llm_response(content, text_vi)

    if should_retry_with_strict_prompt(result, text_vi):
        logger.warning("LLM output failed validation against source text. Retrying with stricter prompt.")
        retry_prompt = build_llm_prompt(text_vi, strict=True)
        retry_response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": retry_prompt}],
            options={"num_predict": 512, "temperature": 0},
        )
        retry_content = retry_response["message"]["content"]
        retry_result = parse_llm_response(retry_content, text_vi)
        retry_result["retry_used"] = True
        return retry_result

    result["retry_used"] = False
    return result


def build_llm_prompt(text_vi: str, strict: bool) -> str:
    return f"""
You are a medical informatics assistant.
Analyze the following Vietnamese clinical text and extract only the medically relevant content.
Return only valid JSON using this schema:
{{
  "translated_term": "concise English clinical translation of the whole input",
  "normalized_terms": ["important medical English term 1", "important medical English term 2"],
  "medical_entities": [
    {{
      "text_vi": "Vietnamese medical phrase from the input",
      "term_en": "English medical term"
    }}
  ]
}}

Rules:
- Keep the full translation concise and clinically accurate.
- Extract only medically relevant entities from the sentence.
- Ignore non-medical filler words such as admission context, conversation words, or administrative language.
- normalized_terms should contain the key English medical terms that are worth mapping to SNOMED CT.
- Do not generate identifiers, codes, placeholders, serial numbers, or fake SNOMED codes.
- normalized_terms must be plain English medical phrases only.
- Infer the correct anatomy and disorder meaning from the Vietnamese source text itself.
- Use standard clinical English, not lay language.
- If the source is a single diagnosis or symptom phrase, translated_term should be that single English clinical phrase.
- If the source is a longer sentence, translated_term should be one concise clinical sentence, while normalized_terms should list the clinically important concepts.
- Do not include markdown or explanation.

{FEW_SHOT_EXAMPLES}
{STRICT_RETRY_SUFFIX if strict else ""}

Input: "{text_vi}"
"""


def parse_llm_response(content: str, source_text_vi: str) -> dict[str, Any]:
    parsed_json = parse_llm_json_content(content)
    if parsed_json is None:
        logger.warning("LLM returned non-JSON or malformed JSON output: %s", content[:300])

    try:
        data = parsed_json if isinstance(parsed_json, dict) else json.loads(content)
        translated_term = str(data.get("translated_term", "")).strip()
        normalized_terms = data.get("normalized_terms", [])
        medical_entities = data.get("medical_entities", [])
        if not isinstance(normalized_terms, list):
            normalized_terms = []
        if not isinstance(medical_entities, list):
            medical_entities = []
        normalized_terms = [
            str(item).strip()
            for item in normalized_terms
            if str(item).strip() and is_valid_medical_term(str(item))
        ]
        cleaned_entities = []
        for entity in medical_entities:
            if not isinstance(entity, dict):
                continue
            text_vi = clean_term(str(entity.get("text_vi", "")))
            term_en = clean_term(str(entity.get("term_en", "")))
            if not text_vi or not is_valid_medical_term(term_en):
                continue
            if not is_entity_from_source(text_vi, source_text_vi):
                continue
            cleaned_entities.append({
                "text_vi": text_vi,
                "term_en": term_en,
            })
            if term_en not in normalized_terms:
                normalized_terms.append(term_en)
        translated_term = clean_term(translated_term)
        if translated_term and translated_term not in normalized_terms:
            normalized_terms.insert(0, translated_term)
        normalized_terms = unique_terms(normalized_terms)
        return {
            "translated_term": translated_term or content.strip(),
            "normalized_terms": normalized_terms,
            "medical_entities": cleaned_entities,
            "raw_llm_output": parsed_json if parsed_json is not None else content,
            "parse_ok": True,
        }
    except Exception:
        fallback = clean_term(content.strip())
        return {
            "translated_term": fallback,
            "normalized_terms": [fallback] if fallback and is_valid_medical_term(fallback) else [],
            "medical_entities": [],
            "raw_llm_output": parsed_json if parsed_json is not None else content,
            "parse_ok": False,
        }


def is_entity_from_source(entity_text_vi: str, source_text_vi: str) -> bool:
    entity_normalized = normalize_vietnamese_text(entity_text_vi)
    source_normalized = normalize_vietnamese_text(source_text_vi)
    return bool(entity_normalized) and entity_normalized in source_normalized


def normalize_vietnamese_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def should_retry_with_strict_prompt(result: dict[str, Any], source_text_vi: str) -> bool:
    if not result.get("parse_ok"):
        return True
    entities = result.get("medical_entities", [])
    if entities:
        return False
    translated = clean_term(str(result.get("translated_term", "")))
    if not translated:
        return True
    source_normalized = normalize_vietnamese_text(source_text_vi)
    obvious_mismatch_markers = ["đau ngực", "khó thở", "chest pain", "dyspnea"]
    return "gãy xương đùi" in source_normalized and translated.lower() in {"chest pain", "dyspnea"}


def search_snomed_descriptions(term: str, limit: int) -> dict[str, Any]:
    last_exc = None
    for attempt in range(1, SNOWSTORM_MAX_RETRIES + 1):
        try:
            response = requests.get(
                f"{SNOWSTORM_BASE_URL}/browser/{SNOWSTORM_BRANCH}/descriptions",
                params={
                    "term": term,
                    "active": "true",
                    "conceptActive": "true",
                    "lang": "english",
                    "limit": limit,
                },
                headers={"Accept-Language": "en"},
                timeout=SNOWSTORM_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= SNOWSTORM_MAX_RETRIES:
                break
            wait_time = SNOWSTORM_BACKOFF_BASE * (2 ** (attempt - 1))
            logger.warning(
                "Snowstorm description lookup failed for '%s' (attempt %s/%s): %s. Retrying in %.1fs",
                term,
                attempt,
                SNOWSTORM_MAX_RETRIES,
                exc,
                wait_time,
            )
            time.sleep(wait_time)
    assert last_exc is not None
    raise last_exc


def fetch_snomed_concept(concept_id: str) -> dict[str, Any] | None:
    last_exc = None
    for attempt in range(1, SNOWSTORM_MAX_RETRIES + 1):
        try:
            response = requests.get(
                f"{SNOWSTORM_BASE_URL}/browser/{SNOWSTORM_BRANCH}/concepts/{concept_id}",
                headers={"Accept-Language": "en"},
                timeout=SNOWSTORM_TIMEOUT,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= SNOWSTORM_MAX_RETRIES:
                break
            wait_time = SNOWSTORM_BACKOFF_BASE * (2 ** (attempt - 1))
            logger.warning(
                "Snowstorm concept lookup failed for '%s' (attempt %s/%s): %s. Retrying in %.1fs",
                concept_id,
                attempt,
                SNOWSTORM_MAX_RETRIES,
                exc,
                wait_time,
            )
            time.sleep(wait_time)
    assert last_exc is not None
    raise last_exc


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


def infer_semantic_tag(fsn: str | None) -> str | None:
    if not fsn:
        return None
    match = re.search(r"\(([^()]+)\)\s*$", fsn)
    if match:
        return match.group(1).strip()
    return None


def map_term_to_snomed(term: str, limit: int) -> dict[str, Any]:
    description_data = search_snomed_descriptions(term, limit)
    items = description_data.get("items") or []

    result: dict[str, Any] = {
        "query_term": term,
        "found": False,
        "raw_result_count": len(items),
        "best_match": None,
    }

    if not items:
        return result

    first = items[0]
    concept_id = (
        get_nested_str(first, ("conceptId",), ("concept", "conceptId"), ("concept", "id"))
        or get_nested_str(first, ("referencedComponentId",))
    )
    if not concept_id:
        return result

    concept = fetch_snomed_concept(concept_id) or {}
    result["found"] = True
    fsn = get_nested_str(concept, ("fsn", "term"))
    result["best_match"] = {
        "concept_id": concept_id,
        "preferred_term": get_nested_str(concept, ("pt", "term"), ("preferredTerm",))
        or get_nested_str(first, ("term",)),
        "fully_specified_name": fsn,
        "semantic_tag": get_nested_str(concept, ("fsn", "semanticTag")) or infer_semantic_tag(fsn),
        "module_id": get_nested_str(concept, ("moduleId",)),
        "definition_status": get_nested_str(concept, ("definitionStatus",)),
    }
    return result


def unique_terms(terms: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            output.append(normalized)
    return output


def clean_term(term: str) -> str:
    term = term.strip().strip('"').strip("'")
    term = " ".join(term.split())
    return term


def parse_llm_json_content(content: str) -> dict[str, Any] | list[Any] | None:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}") + 1
    if start_idx >= 0 and end_idx > start_idx:
        snippet = cleaned[start_idx:end_idx]
        try:
            return json.loads(snippet)
        except Exception:
            return None
    return None


def is_valid_medical_term(term: str) -> bool:
    term = clean_term(term)
    if not term:
        return False
    if term.upper() in KNOWN_MEDICAL_ACRONYMS:
        return True
    if len(term) < 3 or len(term) > 120:
        return False
    upper = term.upper()
    if upper.startswith("SNOMED") or upper.startswith("ICD") or upper.startswith("LOINC"):
        return False
    if any(char.isdigit() for char in term):
        letters = sum(char.isalpha() for char in term)
        digits = sum(char.isdigit() for char in term)
        if digits >= 2 and digits >= letters / 2:
            return False
    if not any(char.isalpha() for char in term):
        return False
    if re.fullmatch(r"[A-Z0-9\-]+", term):
        return False
    return True


def build_entity_pairs(
    medical_entities: list[dict[str, Any]],
    normalized_terms: list[str],
    english_term: str,
) -> list[tuple[str | None, str]]:
    pairs: list[tuple[str | None, str]] = []
    for entity in medical_entities:
        term_en = entity.get("term_en")
        text_vi = entity.get("text_vi")
        if term_en:
            pairs.append((text_vi, term_en))
    if pairs:
        return pairs

    fallback_terms = normalized_terms or ([english_term] if english_term else [])
    return [(None, term) for term in fallback_terms]


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose or args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        input_text = read_input(args)
        if not input_text:
            raise ValueError("Input text is empty.")
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    llm_result = get_medical_translation_llm(input_text, args.model)
    english_term = llm_result["translated_term"]
    normalized_terms = llm_result.get("normalized_terms", [])
    medical_entities = llm_result.get("medical_entities", [])
    if medical_entities:
        english_term = clean_term(medical_entities[0].get("term_en", "") or english_term)
    if english_term and english_term not in normalized_terms and is_valid_medical_term(english_term):
        normalized_terms.insert(0, english_term)
    normalized_terms = unique_terms(normalized_terms)

    mappings: list[dict[str, Any]] = []
    entity_pairs = build_entity_pairs(medical_entities, normalized_terms, english_term)

    for text_vi, term in entity_pairs:
        try:
            mapping = map_term_to_snomed(term, args.limit)
            if text_vi:
                mapping["source_text_vi"] = text_vi
            mappings.append(mapping)
        except requests.RequestException as exc:
            mappings.append(
                {
                    "source_text_vi": text_vi,
                    "query_term": term,
                    "found": False,
                    "raw_result_count": 0,
                    "best_match": None,
                    "error": str(exc),
                }
            )

    best_mapping = next(
        (item for item in mappings if item.get("found") and item.get("best_match")),
        None,
    )

    clean_entities = []
    for entity in medical_entities:
        term_en = clean_term(str(entity.get("term_en", "")))
        text_vi = clean_term(str(entity.get("text_vi", "")))
        if not text_vi or not term_en:
            continue
        clean_entities.append(
            {
                "text": text_vi,
                "type": "clinical_condition",
                "normalized": term_en,
            }
        )

    snomed_block = {
        "query": english_term,
        "match": {
            "found": False,
            "concept_id": None,
            "preferred_term": None,
            "fsn": None,
            "semantic_tag": None,
            "definition_status": None,
        },
        "candidates_found": 0,
    }
    if best_mapping:
        match = best_mapping.get("best_match") or {}
        snomed_block = {
            "query": best_mapping.get("query_term") or english_term,
            "match": {
                "found": True,
                "concept_id": match.get("concept_id"),
                "preferred_term": match.get("preferred_term"),
                "fsn": match.get("fully_specified_name"),
                "semantic_tag": match.get("semantic_tag"),
                "definition_status": match.get("definition_status"),
            },
            "candidates_found": best_mapping.get("raw_result_count", 0),
        }

    payload = {
        "input": input_text,
        "nlp": {
            "translation_en": english_term,
            "normalized_terms": normalized_terms,
            "entities": clean_entities,
        },
        "snomed": snomed_block,
        "meta": {
            "model": args.model,
            "snowstorm": f"{SNOWSTORM_BASE_URL}/{SNOWSTORM_BRANCH}",
            "llm_parse_ok": llm_result.get("parse_ok", True),
        },
    }
    if args.debug:
        payload["candidate_mappings"] = mappings
        payload["meta"]["raw_llm_output"] = llm_result["raw_llm_output"]

    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
