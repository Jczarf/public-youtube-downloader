from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "downloads", "dist", "build"}
SENSITIVE_NAMES = {".env", "id_rsa", "id_ed25519"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".session"}
PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("github-token", re.compile(r"gh[opusr]_[0-9A-Za-z]{20,}")),
    ("openai-like-key", re.compile(r"\bsk-[0-9A-Za-z_-]{20,}")),
    ("telegram-bot-token", re.compile(r"\b\d{6,12}:[0-9A-Za-z_-]{20,}\b")),
]
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yml", ".yaml", ".sh", ".ini", ".cfg", ".example"}


def main() -> int:
    problems: list[str] = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts) or not path.is_file():
            continue
        if path.name in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
            problems.append(f"arquivo sensível versionado: {path.relative_to(ROOT)}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Dockerfile", "requirements.txt"}:
            continue
        try:
            data = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in PATTERNS:
            if pattern.search(data):
                problems.append(f"{label}: {path.relative_to(ROOT)}")
    if problems:
        print("Falha na revisão de publicação:")
        for item in problems:
            print(f"- {item}")
        return 1
    print("Revisão automática básica: nenhum segredo óbvio encontrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
