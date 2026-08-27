from pathlib import Path

from src.history import HistoryStore


def test_history_roundtrip(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.json")
    store.add({"title": "Teste", "status": "concluído", "format": "MP3"})

    items = store.list()
    assert len(items) == 1
    assert items[0]["title"] == "Teste"
    assert items[0]["status"] == "concluído"


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
