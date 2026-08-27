from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .app import YouTubeDownloaderWindow as BaseYouTubeDownloaderWindow
from .resolver import LinkType, classificar_link, detectar_contexto_playlist
from .ui import choose_video_playlist_scope


class YouTubeDownloaderWindow(BaseYouTubeDownloaderWindow):
    """Janela final da aplicação com decisões de entrada orientadas ao usuário."""

    def _resolve_input(self) -> None:
        if self.resolve_busy or self._closing:
            return

        original = self.input.text().strip()
        if not original:
            self.input.setFocus()
            return

        context = detectar_contexto_playlist(original)
        if context is not None:
            choice = choose_video_playlist_scope(self)
            if choice is None:
                self.input.setFocus()
                return
            self.input.setText(
                context.playlist_url if choice == "playlist" else context.video_url
            )

        super()._resolve_input()

    def _poll_clipboard(self) -> None:
        """Preserva `list=` até a escolha do usuário em vez de canonicalizar cedo demais."""
        if self.resolve_busy or self._closing:
            return

        value = QApplication.clipboard().text().strip()
        if not value or value == self.last_clipboard:
            return

        kind, normalized = classificar_link(value)
        if kind not in {LinkType.DIRETO, LinkType.PLAYLIST}:
            self.last_clipboard = value
            return

        dedupe_key = value if detectar_contexto_playlist(value) is not None else normalized
        if dedupe_key in self.seen_clipboard:
            self.last_clipboard = value
            return

        self.last_clipboard = value
        self.seen_clipboard.add(dedupe_key)
        self.input.setText(value)
        self._resolve_input()


def iniciar_app() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    window = YouTubeDownloaderWindow()
    window.show()
    raise SystemExit(app.exec())
