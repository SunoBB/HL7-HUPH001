#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/home/suno/Downloads/HL7"
FHIR_URL="http://localhost:8081/fhir/metadata"

if ! command -v gemini >/dev/null 2>&1; then
  echo "gemini CLI was not found in PATH." >&2
  exit 1
fi

if [[ ! -f "$ROOT_DIR/.gemini/settings.json" ]]; then
  echo "Missing Gemini workspace config: $ROOT_DIR/.gemini/settings.json" >&2
  exit 1
fi

if ! curl -fsS "$FHIR_URL" >/dev/null 2>&1; then
  echo "FHIR server is not reachable at $FHIR_URL" >&2
  echo "Start it first with:" >&2
  echo "  cd $ROOT_DIR/HL7_FHIR && docker compose up -d" >&2
  exit 1
fi

cd "$ROOT_DIR"

if [[ $# -eq 0 ]]; then
  exec gemini
fi

exec gemini "$@"
