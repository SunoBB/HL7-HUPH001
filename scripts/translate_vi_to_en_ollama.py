import argparse
import os
import subprocess
import sys


DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
DEFAULT_SYSTEM_PROMPT = os.getenv(
    "OLLAMA_SYSTEM_PROMPT",
    (
        "You are a medical translation assistant. "
        "Translate Vietnamese clinical text into clear, accurate English. "
        "Preserve diagnoses, symptoms, medications, abbreviations, units, and chronology. "
        "Return only the English translation."
    ),
)


def read_input(args: argparse.Namespace) -> str:
    if args.text:
        return args.text.strip()
    if args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise ValueError("Provide --text, --file, or pipe input via stdin.")


def build_prompt(text: str) -> str:
    return f"{DEFAULT_SYSTEM_PROMPT}\n\nVietnamese input:\n{text}\n\nEnglish translation:"


def translate_with_ollama(text: str, model: str) -> str:
    result = subprocess.run(
        ["ollama", "run", model, build_prompt(text)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip() or "Unknown Ollama error."
        raise RuntimeError(error_text)
    return result.stdout.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate Vietnamese text to English directly with local Ollama."
    )
    parser.add_argument("--text", help="Vietnamese input text.")
    parser.add_argument("--file", help="Path to a UTF-8 text file.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model to use. Default: {DEFAULT_MODEL}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        source_text = read_input(args)
        if not source_text:
            raise ValueError("Input text is empty.")
        translated = translate_with_ollama(source_text, args.model)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(translated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
