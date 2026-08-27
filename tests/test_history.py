import json
import os
import stat
from pathlib import Path

from src.history import HistoryStore


def test_history_roundtrip(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.json")
    store.add({"title": "Teste", "status": "concluído", "format": "MP3"})

    items = store.list()
    assert len(items) == 1
    assert items[0]["title"] == "Teste"
    assert items[0]["status"] == "concluído"


def test_history_remove_url_e_redige_mensagem(tmp_path: Path):
    path = tmp_path / "history.json"
    store = HistoryStore(path)
    store.add(
        {
            "title": "Teste",
            "url": "https://www.youtube.com/watch?v=abc123",
            "status": "erro",
            "message": "falhou em https://www.youtube.com/watch?v=abc123",
        }
    )
    item = store.list()[0]
    assert "url" not in item
    assert "https://" not in item["message"]
    assert "<url>" in item["message"]


def test_history_migra_entrada_antiga_com_url(tmp_path: Path):
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            [
                {
                    "title": "Antigo",
                    "url": "https://youtu.be/abc123",
                    "status": "concluído",
                    "message": "ok",
                }
            ]
        ),
        encoding="utf-8",
    )
    store = HistoryStore(path)
    assert "url" not in store.list()[0]
    assert "url" not in json.loads(path.read_text(encoding="utf-8"))[0]


def test_history_clear(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.json")
    store.add({"title": "Teste", "status": "erro"})
    store.clear()
    assert store.list() == []


def test_history_limit(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.json", max_items=20)
    for index in range(30):
        store.add({"title": str(index), "status": "concluído"})
    assert len(store.list()) == 20
    assert store.list()[0]["title"] == "29"


def test_history_usa_permissao_privada_quando_suportado(tmp_path: Path):
    store = HistoryStore(tmp_path / "private" / "history.json")
    store.add({"title": "Teste", "status": "concluído"})
    if os.name == "posix":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
