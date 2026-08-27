from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


AUDIO_QUALITIES = {"128", "192", "256", "320"}
VIDEO_QUALITIES = {"480p", "720p", "1080p"}
FORMATS = {"mp3", "mp4"}


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def validate_download_path(value: str | Path) -> Path:
    raw = str(value).strip()
    if not raw:
        raise ValueError("Escolha uma pasta de destino.")

    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("A pasta de destino precisa ser um caminho absoluto ou começar com ~.")
    if path == Path(path.anchor):
        raise ValueError("A raiz do sistema não pode ser usada como pasta de download.")
    if path.exists() and not path.is_dir():
        raise ValueError("A pasta de destino informada aponta para um arquivo.")
    return path


class Config:
    """Preferências locais com validação, escrita atômica e permissões privadas."""

    DEFAULTS = {
        "download_path": str(Path.home() / "Downloads" / "YouTube Downloader"),
        "formato_padrao": "mp3",
        "qualidade_audio": "192",
        "qualidade_video": "1080p",
        "max_downloads_simultaneos": 2,
    }

    def __init__(self, config_file: Path | None = None) -> None:
        if config_file is None:
            xdg = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
            config_file = xdg / "youtube-downloader" / "config.json"
        self.config_file = Path(config_file)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        _chmod(self.config_file.parent, 0o700)
        existed = self.config_file.exists()
        self.settings = self.load()
        if existed:
            # Regrava somente as chaves conhecidas/validadas. Isso remove opções antigas,
            # como a persistência do clipboard, e normaliza configurações corrompidas.
            self.save()

    def _validated(self, data: dict[str, Any]) -> dict[str, Any]:
        result = self.DEFAULTS.copy()

        raw_path = data.get("download_path")
        if isinstance(raw_path, str):
            try:
                result["download_path"] = str(validate_download_path(raw_path))
            except ValueError:
                pass

        fmt = data.get("formato_padrao")
        if isinstance(fmt, str) and fmt.lower() in FORMATS:
            result["formato_padrao"] = fmt.lower()

        audio = str(data.get("qualidade_audio", ""))
        if audio in AUDIO_QUALITIES:
            result["qualidade_audio"] = audio

        video = str(data.get("qualidade_video", ""))
        if video in VIDEO_QUALITIES:
            result["qualidade_video"] = video

        concurrent = data.get("max_downloads_simultaneos")
        if isinstance(concurrent, int) and not isinstance(concurrent, bool):
            result["max_downloads_simultaneos"] = max(1, min(concurrent, 8))

        return result

    def load(self) -> dict[str, Any]:
        if not self.config_file.exists():
            return self.DEFAULTS.copy()
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("configuração inválida")
            return self._validated(data)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            return self.DEFAULTS.copy()

    def save(self) -> None:
        self.settings = self._validated(self.settings)
        temp = self.config_file.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self.settings, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _chmod(temp, 0o600)
        temp.replace(self.config_file)
        _chmod(self.config_file, 0o600)

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if key not in self.DEFAULTS:
            raise KeyError(f"Preferência desconhecida: {key}")
        self.settings[key] = value
        self.save()

    def update(self, **values: Any) -> None:
        unknown = set(values) - set(self.DEFAULTS)
        if unknown:
            raise KeyError(f"Preferências desconhecidas: {', '.join(sorted(unknown))}")
        self.settings.update(values)
        self.save()
