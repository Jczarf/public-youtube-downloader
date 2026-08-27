from PySide6.QtWidgets import QApplication

import src.application as application
from src.app import YouTubeDownloaderWindow as BaseYouTubeDownloaderWindow


MIXED_URL = (
    "https://www.youtube.com/watch?v=boM3oFAFrXQ"
    "&list=PLp6qYuqZnG5Yw8oz1_K12vcLE6mUtQEPw&index=1"
)


def build_window(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    return app, application.YouTubeDownloaderWindow()


def test_escolher_playlist_encaminha_url_da_playlist(monkeypatch, tmp_path):
    app, window = build_window(monkeypatch, tmp_path)
    received = []
    monkeypatch.setattr(application, "choose_video_playlist_scope", lambda _parent: "playlist")
    monkeypatch.setattr(
        BaseYouTubeDownloaderWindow,
        "_resolve_input",
        lambda self: received.append(self.input.text()),
    )

    window.input.setText(MIXED_URL)
    window._resolve_input()
    app.processEvents()

    assert received == [
        "https://www.youtube.com/playlist?list=PLp6qYuqZnG5Yw8oz1_K12vcLE6mUtQEPw"
    ]
    window.close()


def test_escolher_video_encaminha_somente_video(monkeypatch, tmp_path):
    app, window = build_window(monkeypatch, tmp_path)
    received = []
    monkeypatch.setattr(application, "choose_video_playlist_scope", lambda _parent: "video")
    monkeypatch.setattr(
        BaseYouTubeDownloaderWindow,
        "_resolve_input",
        lambda self: received.append(self.input.text()),
    )

    window.input.setText(MIXED_URL)
    window._resolve_input()
    app.processEvents()

    assert received == ["https://www.youtube.com/watch?v=boM3oFAFrXQ"]
    window.close()


def test_cancelar_escolha_nao_inicia_resolucao(monkeypatch, tmp_path):
    app, window = build_window(monkeypatch, tmp_path)
    received = []
    monkeypatch.setattr(application, "choose_video_playlist_scope", lambda _parent: None)
    monkeypatch.setattr(
        BaseYouTubeDownloaderWindow,
        "_resolve_input",
        lambda self: received.append(self.input.text()),
    )

    window.input.setText(MIXED_URL)
    window._resolve_input()
    app.processEvents()

    assert received == []
    assert window.input.text() == MIXED_URL
    window.close()
