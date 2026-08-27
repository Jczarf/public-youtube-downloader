from __future__ import annotations

from pathlib import Path


MAX_TXT_BYTES = 2 * 1024 * 1024
MAX_TXT_ITEMS = 500
MAX_LINE_CHARS = 4096


def read_txt_entries(
    path: str | Path,
    *,
    max_bytes: int = MAX_TXT_BYTES,
    max_items: int = MAX_TXT_ITEMS,
    max_line_chars: int = MAX_LINE_CHARS,
) -> list[str]:
    file_path = Path(path)
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise ValueError(f"Não foi possível acessar o arquivo: {exc}") from exc

    if size > max_bytes:
        raise ValueError(
            f"O arquivo TXT é grande demais ({size / 1024 / 1024:.1f} MB). "
            f"O limite é {max_bytes / 1024 / 1024:.0f} MB."
        )

    entries: list[str] = []
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                value = raw_line.strip()
                if not value:
                    continue
                if len(value) > max_line_chars:
                    raise ValueError(
                        f"Uma linha excede o limite de {max_line_chars} caracteres."
                    )
                entries.append(value)
                if len(entries) >= max_items:
                    break
    except UnicodeError as exc:
        raise ValueError("O arquivo precisa estar em UTF-8.") from exc
    except OSError as exc:
        raise ValueError(f"Não foi possível ler o arquivo: {exc}") from exc

    return entries
