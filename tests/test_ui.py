from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import src.app as app_module
from src.app import QueueCard, YouTubeDownloaderWindow
from src.downloader import DownloadSpec
from src.ui import AppDialog, display_path, human_datetime


MIXED_URL = (
    "https://www.youtube.com/watch?v=boM3oFAFrXQ"
    "&list=PLp6qYuqZnG5Yw8oz1_K12vcLE6mUtQEPw&index=1"
)


def build_window(monkeypatch, tmp_path) -> tuple[QApplication, YouTubeDownloaderWindow]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = YouTubeDownloaderWindow()
    return app, window


def test_sidebar_navega_exclusivamente(monkeypatch, tmp_path):
    app, window = build_window(monkeypatch, tmp_path)
    assert window.pages.count() == 3
    assert len(window.nav_buttons) == 3
    assert window.pages.currentIndex() == 0
    assert sum(button.isChecked() for button in window.nav_buttons) == 1

    window.nav_buttons[1].click()
    app.processEvents()
    assert window.pages.currentIndex() == 1
    assert window.page_title.text() == "Histórico"

    window.nav_buttons[2].click()
    app.processEvents()
    assert window.pages.currentIndex() == 2
    assert window.page_title.text() == "Listas TXT"

    window.nav_buttons[0].click()
    app.processEvents()
    assert window.pages.currentIndex() == 0
    assert sum(button.isChecked() for button in window.nav_buttons) == 1
    window.close()


def test_configuracao_rapida_controla_formato_qualidade_e_concorrencia(monkeypatch, tmp_path):
    app, window = build_window(monkeypatch, tmp_path)
    window.mp4.click()
    app.processEvents()
    assert window.mp4.isChecked()
    assert window.quality.currentText() in {"480p", "720p", "1080p"}

    window.mp3.click()
    app.processEvents()
    assert window.mp3.isChecked()
    assert window.quality.currentText() in {"128 kbps", "192 kbps", "256 kbps", "320 kbps"}

    window.concurrent_slider.setValue(5)
    app.processEvents()
    assert window.concurrent_value.text() == "5"
    window.close()


def test_clipboard_e_somente_da_sessao(monkeypatch, tmp_path):
    app, window = build_window(monkeypatch, tmp_path)
    window.clip_button.setChecked(True)
    app.processEvents()
    assert window.clip_status_text.text() == "Ativo"
    assert window.clip_button.text() == "Desativar"
    assert "clipboard_monitor" not in window.config.settings
    window.close()

    _, reopened = build_window(monkeypatch, tmp_path)
    assert reopened.clip_button.isChecked() is False
    assert reopened.clip_status_text.text() == "Desligado"
    reopened.close()


def test_fila_vazia_nao_usa_scroll_area_visivel(monkeypatch, tmp_path):
    _, window = build_window(monkeypatch, tmp_path)
    assert window.queue_stack.currentIndex() == 0
    assert window.queue_stack.currentWidget() is window.empty_state
    assert window.queue_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert window.queue_scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert window.clear_finished_button.isEnabled() is False
    window.close()


def test_historico_vazio_tem_estado_proprio_sem_scrollbar_fantasma(monkeypatch, tmp_path):
    _, window = build_window(monkeypatch, tmp_path)
    window._navigate(1)
    assert window.history_stack.currentIndex() == 0
    assert window.history_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert window.history_scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert window.clear_history_button.isEnabled() is False
    window.close()


def test_resolucao_bloqueia_reenvio_duplicado(monkeypatch, tmp_path):
    _, window = build_window(monkeypatch, tmp_path)
    window.input.setText("teste")
    window._set_resolve_busy(True)
    assert window.input.isEnabled() is False
    assert window.add_button.isEnabled() is False
    assert window.add_button.text() == "…"
    window._set_resolve_busy(False)
    assert window.input.isEnabled() is True
    assert window.add_button.isEnabled() is True
    window.close()


def test_ffmpeg_ausente_bloqueia_download(monkeypatch, tmp_path):
    _, window = build_window(monkeypatch, tmp_path)
    messages = []
    monkeypatch.setattr("src.app.shutil.which", lambda _: None)
    monkeypatch.setattr("src.app.show_message", lambda *args, **kwargs: messages.append(args[1]))
    assert window._ensure_ffmpeg() is False
    assert messages == ["FFmpeg necessário"]
    window.close()


def test_titulos_remotos_sao_texto_simples(monkeypatch, tmp_path):
    _, window = build_window(monkeypatch, tmp_path)
    spec = DownloadSpec(
        "https://www.youtube.com/watch?v=abc123",
        "mp3",
        tmp_path,
    )
    card = QueueCard("<b>não renderizar</b>", "mp3", "MP3", spec)
    assert card.title_label.textFormat() == Qt.TextFormat.PlainText
    card.set_title("<img src=x> título")
    assert card.title_label.text() == "<img src=x> título"
    card.deleteLater()
    window.close()


def test_dialogo_tematico_usa_texto_simples(monkeypatch, tmp_path):
    app, window = build_window(monkeypatch, tmp_path)
    dialog = AppDialog(
        window,
        "Limpar histórico",
        "<b>Mensagem</b>",
        kind="question",
        confirm_text="Confirmar",
        cancel_text="Cancelar",
        destructive=True,
    )
    labels = dialog.findChildren(type(window.page_title))
    assert all(label.textFormat() == Qt.TextFormat.PlainText for label in labels)
    dialog.close()
    window.close()
    app.processEvents()


def test_link_misto_permite_escolher_playlist(monkeypatch, tmp_path):
    _, window = build_window(monkeypatch, tmp_path)
    started = []
    monkeypatch.setattr(app_module, "choose_video_playlist_scope", lambda _parent: "playlist")
    monkeypatch.setattr(window, "_ensure_ffmpeg", lambda: True)
    monkeypatch.setattr(window.resolve_pool, "start", lambda worker: started.append(worker.value))

    window.input.setText(MIXED_URL)
    window._resolve_input()

    assert started == [
        "https://www.youtube.com/playlist?list=PLp6qYuqZnG5Yw8oz1_K12vcLE6mUtQEPw"
    ]
    window.close()


def test_link_misto_permite_escolher_video(monkeypatch, tmp_path):
    _, window = build_window(monkeypatch, tmp_path)
    started = []
    monkeypatch.setattr(app_module, "choose_video_playlist_scope", lambda _parent: "video")
    monkeypatch.setattr(window, "_ensure_ffmpeg", lambda: True)
    monkeypatch.setattr(window.resolve_pool, "start", lambda worker: started.append(worker.value))

    window.input.setText(MIXED_URL)
    window._resolve_input()

    assert started == ["https://www.youtube.com/watch?v=boM3oFAFrXQ"]
    window.close()


def test_link_misto_cancelado_nao_inicia_resolucao(monkeypatch, tmp_path):
    _, window = build_window(monkeypatch, tmp_path)
    started = []
    monkeypatch.setattr(app_module, "choose_video_playlist_scope", lambda _parent: None)
    monkeypatch.setattr(window, "_ensure_ffmpeg", lambda: True)
    monkeypatch.setattr(window.resolve_pool, "start", lambda worker: started.append(worker.value))

    window.input.setText(MIXED_URL)
    window._resolve_input()

    assert started == []
    assert window.input.text() == MIXED_URL
    window.close()


def test_helpers_de_apresentacao_encurtam_caminho_e_data(tmp_path):
    home_path = display_path("~/Downloads/YouTube Downloader")
    assert home_path.startswith("~/")
    assert human_datetime("2026-08-27T11:00:42-03:00").startswith("27/08/2026")
