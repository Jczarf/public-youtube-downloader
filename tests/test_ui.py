from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.app import YouTubeDownloaderWindow


def test_sidebar_navega_exclusivamente(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = YouTubeDownloaderWindow()

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
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = YouTubeDownloaderWindow()

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
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = YouTubeDownloaderWindow()

    window.clip_button.setChecked(True)
    app.processEvents()
    assert window.config.get("clipboard_monitor") is True
    assert "Ativo" in window.clip_button.text()

    window.clip_button.setChecked(False)
    app.processEvents()
    assert window.config.get("clipboard_monitor") is False

    window.close()
