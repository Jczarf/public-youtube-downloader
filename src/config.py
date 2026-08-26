from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class Config:
    """Persistência simples e local das preferências da aplicação."""

    DEFAULTS = {
        "download_path": str(Path.home() / "Downloads" / "YouTube Downloader"),
        "formato_padrao": "mp3",
        "qualidade_audio": "192",
        "qualidade_video": "1080p",
        "max_downloads_simultaneos": 3,
        "clipboard_monitor": False,
    }

    def __init__(self, config_file: Path | None = None) -> None:
        if config_file is None:
            xdg = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
            config_file = xdg / "youtube-downloader" / "config.json"
        self.config_file = Path(config_file)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings = self.load()

    def load(self) -> dict[str, Any]:
        if not self.config_file.exists():
            return self.DEFAULTS.copy()
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("configuração inválida")
            return {**self.DEFAULTS, **data}
        except (OSError, ValueError, json.JSONDecodeError):
            return self.DEFAULTS.copy()

    def save(self) -> None:
        temp = self.config_file.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self.settings, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp.replace(self.config_file)

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self.save()

    def update(self, **values: Any) -> None:
        self.settings.update(values)
        self.save()
