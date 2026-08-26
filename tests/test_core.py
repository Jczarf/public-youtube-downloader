from pathlib import Path

import pytest

from src.config import Config
from src.downloader import DownloadSpec, build_options, parse_time, validate_clip
from src.resolver import LinkType, classificar_link


def test_classifica_link_direto():
    kind, value = classificar_link("https://www.youtube.com/watch?v=abc123")
    assert kind == LinkType.DIRETO
    assert value.startswith("https://")


def test_rejeita_url_externa():
    kind, _ = classificar_link("https://example.com/video")
    assert kind == LinkType.INVALIDO


def test_classifica_texto_como_pesquisa():
    kind, value = classificar_link("synthwave mix")
    assert kind == LinkType.PESQUISA_TEXTO
    assert value == "synthwave mix"


def test_parse_time():
    assert parse_time("2:30") == 150
    assert parse_time("1:02:03") == 3723


def test_clip_invalido():
    with pytest.raises(ValueError):
        validate_clip("2:00", "1:00")


def test_config_roundtrip(tmp_path: Path):
    cfg = Config(tmp_path / "config.json")
    cfg.set("max_downloads_simultaneos", 4)
    assert Config(tmp_path / "config.json").get("max_downloads_simultaneos") == 4


def test_options_nao_desabilitam_tls(tmp_path: Path):
    spec = DownloadSpec("https://youtu.be/abc", "mp3", tmp_path)
    opts = build_options(spec, lambda _: None)
    assert "nocheckcertificate" not in opts
    assert opts["ignoreerrors"] is False
