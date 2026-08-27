from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.app import YouTubeDownloaderWindow
from src.ui import AppDialog, display_path, human_datetime


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
    assert all("Configurações" not in button.text() for button in window.nav_buttons)

    window.nav_buttons[1].click()
    app.processEvents()
    assert window.pages.currentIndex() == 1
    assert window.page_title.text() == "Histórico"
    assert sum(button.isChecked() for button in window.nav_buttons) == 1

    window.nav_buttons[2].click()
    app.processEvents()
    assert window.pages.currentIndex() == 2
    assert window.page_title.text() == "Listas TXT"
    assert sum(button.isChecked() for button in window.nav_buttons) == 1

    window.nav_buttons[0].click()
    app.processEvents()
    assert window.pages.currentIndex() == 0
    assert window.page_title.text() == "Downloader de mídia"
    assert sum(button.isChecked() for button in window.nav_buttons) == 1

    window.close()


def test_configuracao_rapida_controla_formato_qualidade_e_concorrencia(monkeypatch, tmp_path):
    app, window = build_window(monkeypatch, tmp_path)

    window.mp4.click()
    app.processEvents()
    assert window.mp4.isChecked()
    assert not window.mp3.isChecked()
    assert window.quality.currentText() in {"480p", "720p", "1080p"}

    window.mp3.click()
    app.processEvents()
    assert window.mp3.isChecked()
    assert not window.mp4.isChecked()
    assert window.quality.currentText() in {
        "128 kbps",
        "192 kbps",
        "256 kbps",
        "320 kbps",
    }

    window.concurrent_slider.setValue(5)
    app.processEvents()
    assert window.concurrent_value.text() == "5"

    window.close()


def test_clipboard_persiste_estado_local(monkeypatch, tmp_path):
    app, window = build_window(monkeypatch, tmp_path)

    window.clip_button.setChecked(True)
    app.processEvents()
    assert window.config.get("clipboard_monitor") is True
    assert window.clip_status_text.text() == "Ativo"
    assert window.clip_button.text() == "Desativar"
    assert window.privacy_label.objectName() == "privacyOn"

    window.clip_button.setChecked(False)
    app.processEvents()
    assert window.config.get("clipboard_monitor") is False
    assert window.clip_status_text.text() == "Desligado"
    assert window.clip_button.text() == "Ativar"
    assert window.privacy_label.objectName() == "privacyOff"

    window.close()


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
    assert window.resolve_busy is True
    assert window.input.isEnabled() is False
    assert window.add_button.isEnabled() is False
    assert window.add_button.text() == "…"

    window._set_resolve_busy(False)
    assert window.input.isEnabled() is True
    assert window.add_button.isEnabled() is True
    assert window.add_button.text() == "+"

    window.close()


def test_dialogo_tematico_nao_depende_de_messagebox_claro(monkeypatch, tmp_path):
    app, window = build_window(monkeypatch, tmp_path)
    dialog = AppDialog(
        window,
        "Limpar histórico",
        "Mensagem de confirmação.",
        kind="question",
        confirm_text="Confirmar",
        cancel_text="Cancelar",
        destructive=True,
    )

    assert dialog.objectName() == "appDialog"
    assert dialog.minimumWidth() >= 470
    assert "#10141c" in dialog.styleSheet()
    dialog.close()
    window.close()
    app.processEvents()


def test_helpers_de_apresentacao_encurtam_caminho_e_data(tmp_path):
    home_path = display_path("~/Downloads/YouTube Downloader")
    assert home_path.startswith("~/")
    assert human_datetime("2026-08-27T11:00:42-03:00").startswith("27/08/2026")
