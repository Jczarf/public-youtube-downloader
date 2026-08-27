from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.app import YouTubeDownloaderWindow


def test_sidebar_navega_exclusivamente(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = YouTubeDownloaderWindow()

    assert window.pages.count() == 4
    assert window.pages.currentIndex() == 0
    assert sum(button.isChecked() for button in window.nav_buttons) == 1

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

    window.nav_buttons[3].click()
    app.processEvents()
    assert window.pages.currentIndex() == 3
    assert window.page_title.text() == "Configurações"
    assert sum(button.isChecked() for button in window.nav_buttons) == 1

    window.close()


def test_controles_principais_sao_exclusivos(monkeypatch, tmp_path):
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
    assert window.quality.currentText() in {"128", "192", "256", "320"}

    window.close()
