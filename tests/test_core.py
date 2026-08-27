import json
import os
import stat
from pathlib import Path

import pytest

from src.config import Config, validate_download_path
from src.downloader import DownloadSpec, Downloader, build_options, parse_time, validate_clip
from src.resolver import LinkType, classificar_link
from src.text_import import read_txt_entries


def test_classifica_link_direto_e_canonicaliza_https():
    kind, value = classificar_link("http://youtu.be/abc123")
    assert kind == LinkType.DIRETO
    assert value == "https://www.youtube.com/watch?v=abc123"


def test_rejeita_url_externa_e_rotas_nao_video():
    assert classificar_link("https://example.com/video")[0] == LinkType.INVALIDO
    assert classificar_link("https://youtube.com/redirect?q=https://example.com")[0] == LinkType.INVALIDO
    assert classificar_link("https://youtube.com/channel/abc123")[0] == LinkType.INVALIDO


def test_classifica_playlist_e_pesquisa_url():
    kind, value = classificar_link("https://youtube.com/playlist?list=PL12345678")
    assert kind == LinkType.PLAYLIST
    assert value == "https://www.youtube.com/playlist?list=PL12345678"

    kind, value = classificar_link("https://youtube.com/results?search_query=synthwave+mix")
    assert kind == LinkType.PESQUISA_URL
    assert value == "synthwave mix"


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


def test_config_roundtrip_e_validacao(tmp_path: Path):
    cfg = Config(tmp_path / "private" / "config.json")
    cfg.update(max_downloads_simultaneos=4, formato_padrao="mp4")
    loaded = Config(cfg.config_file)
    assert loaded.get("max_downloads_simultaneos") == 4
    assert loaded.get("formato_padrao") == "mp4"

    cfg.config_file.write_text(
        json.dumps({
            "max_downloads_simultaneos": "muito",
            "formato_padrao": "exe",
            "qualidade_audio": "999",
        }),
        encoding="utf-8",
    )
    recovered = Config(cfg.config_file)
    assert recovered.get("max_downloads_simultaneos") == 3
    assert recovered.get("formato_padrao") == "mp3"
    assert recovered.get("qualidade_audio") == "192"


def test_config_usa_permissao_privada_quando_suportado(tmp_path: Path):
    cfg = Config(tmp_path / "private" / "config.json")
    cfg.save()
    if os.name == "posix":
        assert stat.S_IMODE(cfg.config_file.stat().st_mode) == 0o600


def test_destination_path_rejeita_vazio_relativo_e_raiz(tmp_path: Path):
    with pytest.raises(ValueError):
        validate_download_path("")
    with pytest.raises(ValueError):
        validate_download_path("Downloads")
    with pytest.raises(ValueError):
        validate_download_path("/")
    assert validate_download_path(tmp_path / "downloads").is_absolute()


def test_options_nao_desabilitam_tls_e_priorizam_mp4(tmp_path: Path):
    mp3 = DownloadSpec("https://www.youtube.com/watch?v=abc123", "mp3", tmp_path)
    opts = build_options(mp3, lambda _: None)
    assert "nocheckcertificate" not in opts
    assert opts["ignoreerrors"] is False

    mp4 = DownloadSpec(
        "https://www.youtube.com/watch?v=abc123",
        "mp4",
        tmp_path,
        qualidade_video="1080p",
    )
    mp4_opts = build_options(mp4, lambda _: None)
    assert "bestvideo[ext=mp4]" in mp4_opts["format"]
    assert "bestaudio[ext=m4a]" in mp4_opts["format"]


def test_downloader_faz_uma_unica_extracao_com_download(monkeypatch, tmp_path: Path):
    calls = []

    class FakeYDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download):
            calls.append((url, download))
            self.options["progress_hooks"][0](
                {
                    "status": "downloading",
                    "downloaded_bytes": 50,
                    "total_bytes": 100,
                    "speed": 10,
                    "info_dict": {"title": "Teste"},
                }
            )
            return {"title": "Teste"}

    monkeypatch.setattr("src.downloader.yt_dlp.YoutubeDL", FakeYDL)
    titles = []
    spec = DownloadSpec("https://www.youtube.com/watch?v=abc123", "mp3", tmp_path)
    assert Downloader(spec).baixar(info_callback=lambda info: titles.append(info["title"])) is True
    assert calls == [(spec.url, True)]
    assert titles == ["Teste"]


def test_txt_import_limita_tamanho_itens_e_linhas(tmp_path: Path):
    file_path = tmp_path / "lista.txt"
    file_path.write_text("\n".join(f"item {i}" for i in range(600)), encoding="utf-8")
    assert len(read_txt_entries(file_path)) == 500

    oversized = tmp_path / "grande.txt"
    oversized.write_bytes(b"x" * 100)
    with pytest.raises(ValueError):
        read_txt_entries(oversized, max_bytes=50)

    long_line = tmp_path / "linha.txt"
    long_line.write_text("x" * 20, encoding="utf-8")
    with pytest.raises(ValueError):
        read_txt_entries(long_line, max_line_chars=10)
