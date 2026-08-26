from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

EXCLUDE_RE = re.compile(
    r"(^|/)(\.git|node_modules|\.next|\.venv|venv|dist|build|htmlcov)(/|$)"
    r"|(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock)$"
    r"|\.(svg|png|jpe?g|gif|webp|ico|pdf|zip)$",
    re.IGNORECASE,
)

SENSITIVE_PATH_RE = re.compile(
    r"(^|/)(\.env($|\.)|.*\.session($|\.)|id_rsa($|\.)|id_ed25519($|\.)|credentials?($|\.)|secrets?($|\.))"
    r"|\.(pem|p12|pfx|key)$",
    re.IGNORECASE,
)


def run(*args: str) -> str:
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def detect(path: str | None = None, *, all_files: bool = False) -> dict:
    cmd = ["detect-secrets", "scan"]
    if all_files:
        cmd.append("--all-files")
        cmd += ["--exclude-files", EXCLUDE_RE.pattern]
    elif path:
        cmd.append(path)
    output = subprocess.run(cmd, check=True, text=True, capture_output=True).stdout
    return json.loads(output)


def findings(data: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for filename, items in data.get("results", {}).items():
        for item in items:
            out.append((filename, item))
    return out


def scan_current_tree() -> list[str]:
    problems: list[str] = []
    for filename, item in findings(detect(all_files=True)):
        problems.append(
            f"árvore atual: {filename}:{item.get('line_number', '?')} — {item.get('type', 'possível segredo')}"
        )
    return problems


def scan_history_paths() -> list[str]:
    problems: list[str] = []
    names = run("git", "log", "--all", "--format=", "--name-only")
    for raw in sorted(set(names.splitlines())):
        path = raw.strip()
        if not path or path == ".env.example":
            continue
        if SENSITIVE_PATH_RE.search(path):
            problems.append(f"histórico: nome de arquivo sensível alcançável: {path}")
    return problems


def scan_history_content() -> list[str]:
    patch = run("git", "log", "--all", "-p", "--no-color", "--format=")
    current_path = ""
    collected: list[str] = []

    for line in patch.splitlines():
        if line.startswith("diff --git a/"):
            match = re.match(r"diff --git a/(.*?) b/(.*)", line)
            current_path = match.group(2) if match else ""
            continue
        if not current_path or EXCLUDE_RE.search(current_path):
            continue
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            value = line[1:]
            if re.fullmatch(r"\s*[0-9a-f]{40,64}\s*", value, re.IGNORECASE):
                continue
            collected.append(value)

    if not collected:
        return []

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt") as handle:
        handle.write("\n".join(collected))
        temp_path = handle.name

    try:
        data = detect(temp_path)
    finally:
        Path(temp_path).unlink(missing_ok=True)

    return [
        f"histórico: possível segredo em conteúdo alcançável — {item.get('type', 'detector desconhecido')}"
        for _, item in findings(data)
    ]


def main() -> int:
    problems = scan_current_tree() + scan_history_paths() + scan_history_content()
    if problems:
        print("Falha na auditoria dedicada de segredos:\n")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print("detect-secrets: árvore atual e histórico alcançável sem achados pelos detectores habilitados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
