from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HistoryStore:
    """Histórico local, limitado e salvo de forma atômica."""

    def __init__(self, path: Path, max_items: int = 200) -> None:
        self.path = Path(path)
        self.max_items = max(20, int(max_items))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)][: self.max_items]

    def add(self, entry: dict[str, Any]) -> None:
        cleaned = {
            str(key): value
            for key, value in entry.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
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
        temp.replace(self.path)
