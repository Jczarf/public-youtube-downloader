from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
ALLOWED_KEYS = {"title", "status", "format", "destination", "message", "finished_at"}


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _redact_text(value: str) -> str:
    text = URL_RE.sub("<url>", value)
    home = str(Path.home())
    if home and home != "/":
        text = text.replace(home, "~")
    return text


class HistoryStore:
    """Histórico local mínimo, privado, limitado e salvo de forma atômica."""

    def __init__(self, path: Path, max_items: int = 200) -> None:
        self.path = Path(path)
        self.max_items = max(20, int(max_items))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _chmod(self.path.parent, 0o700)
        if self.path.exists():
            _chmod(self.path, 0o600)
            self._migrate_existing()

    def _read_raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)][: self.max_items]

    def _normalize(self, entry: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key in ALLOWED_KEYS:
            value = entry.get(key)
            if not (isinstance(value, (str, int, float, bool)) or value is None):
                continue
            if isinstance(value, str) and key in {"title", "message"}:
                value = _redact_text(value)
            normalized[key] = value
        return normalized

    def _migrate_existing(self) -> None:
        raw = self._read_raw()
        normalized = [self._normalize(item) for item in raw]
        if normalized != raw:
            self._write(normalized)

    def list(self) -> list[dict[str, Any]]:
        return [self._normalize(item) for item in self._read_raw()]

    def add(self, entry: dict[str, Any]) -> None:
        cleaned = self._normalize(entry)
        entries = [cleaned, *self.list()][: self.max_items]
        self._write(entries)

    def clear(self) -> None:
        self._write([])

    def _write(self, entries: list[dict[str, Any]]) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _chmod(temp, 0o600)
        temp.replace(self.path)
        _chmod(self.path, 0o600)
