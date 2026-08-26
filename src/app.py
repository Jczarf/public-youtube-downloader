from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yt_dlp
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .downloader import DownloadSpec, Downloader, Progress, validate_clip
from .resolver import LinkType, classificar_link, resolver_entrada


C = {
    "bg": "#07090d",
    "sidebar": "#0b0e14",
    "panel": "#10141c",
    "panel2": "#141a24",
    "border": "#232b38",
    "text": "#f2f5f8",
    "muted": "#8c98a8",
    "accent": "#ff5c63",
    "accent_hover": "#ff7379",
    "green": "#55d88b",
    "amber": "#f2c46d",
    "blue": "#68a7ff",
}


def human_bytes(value: float) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class ResolveSignals(QObject):
    resolved = Signal(object)
    failed = Signal(str)


class ResolveRunnable(QRunnable):
    def __init__(self, value: str) -> None:
        super().__init__()
        self.value = value
        self.signals = ResolveSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.resolved.emit(resolver_entrada(self.value))
        except Exception as exc:  # boundary with network/provider
            self.signals.failed.emit(str(exc))


class DownloadSignals(QObject):
    progress = Signal(object)
    title = Signal(str)
    completed = Signal()
    cancelled = Signal()
    failed = Signal(str)


class DownloadRunnable(QRunnable):
    def __init__(self, spec: DownloadSpec) -> None:
        super().__init__()
        self.spec = spec
        self.signals = DownloadSignals()
        self.downloader: Downloader | None = None

    def cancel(self) -> None:
        if self.downloader:
            self.downloader.cancelar()

    @Slot()
    def run(self) -> None:
        try:
            self.downloader = Downloader(self.spec)
            ok = self.downloader.baixar(
                progress_callback=lambda p: self.signals.progress.emit(p),
                info_callback=lambda info: self.signals.title.emit(str(info.get("title") or "Mídia")),
            )
            if ok:
                self.signals.completed.emit()
            else:
                self.signals.cancelled.emit()
        except Exception as exc:  # boundary with yt-dlp/ffmpeg/network
            self.signals.failed.emit(str(exc))


class QueueCard(QFrame):
    cancel_requested = Signal()

    def __init__(self, label: str, formato: str, detail: str) -> None:
        super().__init__()
        self.setObjectName("queueCard")
        self.speed = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(9)

        top = QHBoxLayout()
        self.icon = QLabel("♫" if formato == "mp3" else "▶")
        self.icon.setObjectName("mediaIcon")
        self.icon.setFixedSize(42, 42)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.icon)

        info = QVBoxLayout()
        self.title_label = QLabel(label)
        self.title_label.setObjectName("queueTitle")
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("muted")
        info.addWidget(self.title_label)
        info.addWidget(self.detail_label)
        top.addLayout(info, 1)

        self.status = QLabel("Na fila")
        self.status.setObjectName("statusWaiting")
        top.addWidget(self.status)
        self.cancel_button = QPushButton("×")
        self.cancel_button.setObjectName("iconButton")
        self.cancel_button.setFixedSize(34, 34)
        self.cancel_button.clicked.connect(self.cancel_requested)
        top.addWidget(self.cancel_button)
        root.addLayout(top)

        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        bottom.addWidget(self.progress, 1)
        self.stats = QLabel("aguardando")
        self.stats.setObjectName("muted")
        self.stats.setMinimumWidth(130)
        self.stats.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self.stats)
        root.addLayout(bottom)

    def set_title(self, value: str) -> None:
        self.title_label.setText(value[:92])

    def set_progress(self, p: Progress) -> None:
        self.speed = p.speed
        self.progress.setValue(int(p.percent * 1000))
        self.status.setText(f"{p.percent * 100:.0f}%")
        self.status.setObjectName("statusActive")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.stats.setText(f"{human_bytes(p.speed)}/s" if p.speed else "baixando")

    def mark_completed(self) -> None:
        self.progress.setValue(1000)
        self.status.setText("Concluído")
        self.status.setObjectName("statusDone")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.stats.setText("concluído")
        self.cancel_button.setEnabled(False)
        self.speed = 0.0

    def mark_cancelled(self) -> None:
        self.status.setText("Cancelado")
        self.stats.setText("cancelado")
        self.cancel_button.setEnabled(False)
        self.speed = 0.0

    def mark_failed(self, message: str) -> None:
        self.status.setText("Erro")
        self.status.setObjectName("statusError")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.stats.setText(message[:35])
        self.cancel_button.setEnabled(False)
        self.speed = 0.0


class YouTubeDownloaderWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = Config()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(int(self.config.get("max_downloads_simultaneos", 3)))
        self.cards: list[QueueCard] = []
        self.workers: dict[QueueCard, DownloadRunnable] = {}
        self.seen_clipboard: set[str] = set()
        self.last_clipboard = ""
        self.completed_count = 0

        self.setWindowTitle("YouTube Downloader")
        self.resize(1540, 920)
        self.setMinimumSize(1180, 760)
        self._theme()
        self._build()

        self.clip_timer = QTimer(self)
        self.clip_timer.setInterval(1100)
        self.clip_timer.timeout.connect(self._poll_clipboard)
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(700)
        self.stats_timer.timeout.connect(self._refresh_stats)
        self.stats_timer.start()

    def _theme(self) -> None:
        self.setFont(QFont("Inter", 10))
        self.setStyleSheet(f"""
            QMainWindow, QWidget#root {{ background:{C['bg']}; color:{C['text']}; }}
            QFrame#sidebar {{ background:{C['sidebar']}; border-right:1px solid {C['border']}; }}
            QFrame#panel, QFrame#queueCard {{ background:{C['panel']}; border:1px solid {C['border']}; border-radius:14px; }}
            QFrame#queueCard {{ background:{C['panel2']}; }}
            QLabel {{ color:{C['text']}; background:transparent; }}
            QLabel#muted {{ color:{C['muted']}; font-size:12px; }}
            QLabel#queueTitle {{ font-size:15px; font-weight:700; }}
            QLabel#mediaIcon {{ background:#24151a; color:{C['accent']}; border-radius:10px; font-size:18px; font-weight:800; }}
            QLabel#statusWaiting {{ color:{C['amber']}; background:#292312; border-radius:10px; padding:5px 10px; font-weight:700; }}
            QLabel#statusActive {{ color:{C['blue']}; background:#152033; border-radius:10px; padding:5px 10px; font-weight:700; }}
            QLabel#statusDone {{ color:{C['green']}; background:#102319; border-radius:10px; padding:5px 10px; font-weight:700; }}
            QLabel#statusError {{ color:{C['accent']}; background:#28151a; border-radius:10px; padding:5px 10px; font-weight:700; }}
            QPushButton {{ background:#161e29; color:{C['text']}; border:1px solid #2b3645; border-radius:10px; padding:10px 14px; font-weight:650; }}
            QPushButton:hover {{ border-color:#465569; }}
            QPushButton#primary {{ background:{C['accent']}; color:#16090b; border:none; font-weight:800; }}
            QPushButton#primary:hover {{ background:{C['accent_hover']}; }}
            QPushButton#nav {{ background:transparent; border:none; color:{C['muted']}; text-align:left; padding:12px 14px; }}
            QPushButton#nav:checked {{ background:#29171c; color:{C['text']}; border:1px solid #51262d; }}
            QPushButton#iconButton {{ padding:0; background:transparent; color:{C['muted']}; border:none; font-size:21px; }}
            QLineEdit {{ background:#0a0f16; color:{C['text']}; border:1px solid #2a3442; border-radius:11px; padding:12px 14px; }}
            QLineEdit:focus {{ border-color:{C['accent']}; }}
            QProgressBar {{ background:#080c12; border:none; border-radius:4px; min-height:8px; max-height:8px; }}
            QProgressBar::chunk {{ background:{C['accent']}; border-radius:4px; }}
            QScrollArea {{ background:transparent; border:none; }}
            QScrollBar:vertical {{ background:transparent; width:8px; }}
            QScrollBar::handle:vertical {{ background:#2a3543; border-radius:4px; min-height:30px; }}
        """)

    def _panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        return frame

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        shell.addWidget(sidebar)
        self._build_sidebar(sidebar)

        main = QWidget()
        body = QVBoxLayout(main)
        body.setContentsMargins(28, 22, 28, 22)
        body.setSpacing(18)
        shell.addWidget(main, 1)

        header = QHBoxLayout()
        htext = QVBoxLayout()
        title = QLabel("Downloader de mídia")
        title.setStyleSheet("font-size:28px;font-weight:800;")
        subtitle = QLabel("Links, pesquisa, filas e recortes em uma experiência única.")
        subtitle.setObjectName("muted")
        htext.addWidget(title)
        htext.addWidget(subtitle)
        header.addLayout(htext)
        header.addStretch()
        ffmpeg = QLabel("FFmpeg ✓" if shutil.which("ffmpeg") else "FFmpeg ausente")
        ffmpeg.setStyleSheet(f"color:{C['green'] if shutil.which('ffmpeg') else C['amber']};font-weight:700;")
        header.addWidget(ffmpeg)
        ytdlp = QLabel(f"yt-dlp {yt_dlp.version.__version__}")
        ytdlp.setStyleSheet(f"color:{C['blue']};font-weight:700;")
        header.addWidget(ytdlp)
        body.addLayout(header)

        add_row = QHBoxLayout()
        add_panel = self._panel()
        add_layout = QVBoxLayout(add_panel)
        add_layout.setContentsMargins(20, 16, 20, 16)
        add_layout.addWidget(self._heading("Adicionar conteúdo", "Cole um link, uma pesquisa ou importe uma lista TXT."))
        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Link do YouTube ou nome da música...")
        self.input.returnPressed.connect(self._resolve_input)
        input_row.addWidget(self.input, 1)
        txt = QPushButton("TXT")
        txt.clicked.connect(self._import_txt)
        input_row.addWidget(txt)
        add = QPushButton("+")
        add.setObjectName("primary")
        add.setFixedWidth(66)
        add.clicked.connect(self._resolve_input)
        input_row.addWidget(add)
        add_layout.addLayout(input_row)
        add_row.addWidget(add_panel, 1)

        clip_panel = self._panel()
        clip_panel.setFixedWidth(300)
        clip_layout = QVBoxLayout(clip_panel)
        clip_layout.setContentsMargins(20, 16, 20, 16)
        clip_layout.addWidget(self._heading("Monitor de clipboard", "Só lê links após ativação explícita."))
        self.clip_button = QPushButton("●  Desligado — Ativar")
        self.clip_button.setCheckable(True)
        self.clip_button.toggled.connect(self._toggle_clipboard)
        clip_layout.addWidget(self.clip_button)
        add_row.addWidget(clip_panel)
        body.addLayout(add_row)

        content = QHBoxLayout()
        queue_panel = self._panel()
        qlayout = QVBoxLayout(queue_panel)
        qlayout.setContentsMargins(20, 18, 20, 18)
        qhead = QHBoxLayout()
        qtitle = QLabel("Fila de downloads")
        qtitle.setStyleSheet("font-size:20px;font-weight:800;")
        qhead.addWidget(qtitle)
        self.queue_badge = QLabel("0 itens")
        self.queue_badge.setStyleSheet(f"color:{C['green']};font-weight:700;")
        qhead.addWidget(self.queue_badge)
        qhead.addStretch()
        self.speed_label = QLabel("0 B/s")
        self.speed_label.setObjectName("muted")
        qhead.addWidget(self.speed_label)
        qlayout.addLayout(qhead)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_body = QWidget()
        self.queue_layout = QVBoxLayout(scroll_body)
        self.queue_layout.setContentsMargins(0, 8, 4, 0)
        self.queue_layout.setSpacing(10)
        self.queue_layout.addStretch()
        scroll.setWidget(scroll_body)
        qlayout.addWidget(scroll, 1)
        content.addWidget(queue_panel, 1)

        settings = self._panel()
        settings.setFixedWidth(350)
        sl = QVBoxLayout(settings)
        sl.setContentsMargins(20, 18, 20, 18)
        s_title = QLabel("Configuração rápida")
        s_title.setStyleSheet("font-size:20px;font-weight:800;")
        sl.addWidget(s_title)
        sl.addWidget(self._small_label("Formato"))
        fmtrow = QHBoxLayout()
        self.mp3 = QPushButton("MP3")
        self.mp4 = QPushButton("MP4")
        for b in (self.mp3, self.mp4):
            b.setCheckable(True)
        self.mp3.setChecked(self.config.get("formato_padrao") == "mp3")
        self.mp4.setChecked(not self.mp3.isChecked())
        self.mp3.clicked.connect(lambda: self._set_format("mp3"))
        self.mp4.clicked.connect(lambda: self._set_format("mp4"))
        fmtrow.addWidget(self.mp3); fmtrow.addWidget(self.mp4)
        sl.addLayout(fmtrow)
        sl.addWidget(self._small_label("Qualidade"))
        self.quality = QLineEdit(str(self.config.get("qualidade_audio", "192")))
        self.quality.setPlaceholderText("192 ou 1080p")
        sl.addWidget(self.quality)
        sl.addWidget(self._small_label("Recorte"))
        cut = QHBoxLayout()
        self.start_time = QLineEdit(); self.start_time.setPlaceholderText("De  00:03")
        self.end_time = QLineEdit(); self.end_time.setPlaceholderText("Até  02:30")
        cut.addWidget(self.start_time); cut.addWidget(self.end_time)
        sl.addLayout(cut)
        sl.addWidget(self._small_label("Pasta de destino"))
        self.destination = QLineEdit(str(self.config.get("download_path")))
        sl.addWidget(self.destination)
        choose = QPushButton("Escolher pasta")
        choose.clicked.connect(self._choose_destination)
        sl.addWidget(choose)
        sl.addWidget(self._small_label("Concorrência"))
        self.concurrent = QLineEdit(str(self.pool.maxThreadCount()))
        self.concurrent.setPlaceholderText("3")
        sl.addWidget(self.concurrent)
        save = QPushButton("Salvar como padrão")
        save.clicked.connect(self._save_defaults)
        sl.addWidget(save)
        sl.addStretch()
        legal = QLabel("Uso pessoal. Baixe somente conteúdo que você tem direito de acessar e respeite os termos da plataforma.")
        legal.setWordWrap(True)
        legal.setObjectName("muted")
        sl.addWidget(legal)
        content.addWidget(settings)
        body.addLayout(content, 1)

    def _build_sidebar(self, sidebar: QFrame) -> None:
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(16, 24, 16, 20)
        brand = QLabel("▶  YouTube Downloader")
        brand.setStyleSheet(f"font-size:20px;font-weight:850;color:{C['text']};")
        lay.addWidget(brand)
        sub = QLabel("DOWNLOADER DE MÍDIA")
        sub.setStyleSheet(f"color:{C['muted']};font-size:10px;font-weight:700;")
        lay.addWidget(sub)
        lay.addSpacing(26)
        for i, name in enumerate(("⇩   Fila", "◷   Histórico", "≡   Listas TXT", "⚙   Configurações")):
            b = QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setChecked(i == 0)
            if i > 0:
                b.clicked.connect(lambda _=False, n=name: self._nav_hint(n))
            lay.addWidget(b)
        lay.addStretch()
        privacy = self._panel()
        pv = QVBoxLayout(privacy)
        pv.addWidget(self._small_label("PRIVACIDADE"))
        self.privacy_label = QLabel("Clipboard desligado")
        self.privacy_label.setStyleSheet(f"color:{C['green']};font-weight:750;")
        pv.addWidget(self.privacy_label)
        note = QLabel("Nenhum link é lido até você ativar o monitor.")
        note.setWordWrap(True); note.setObjectName("muted")
        pv.addWidget(note)
        lay.addWidget(privacy)
        local = QLabel("Uso pessoal • local")
        local.setObjectName("muted")
        lay.addWidget(local)

    def _heading(self, title: str, subtitle: str) -> QWidget:
        box = QWidget()
        l = QVBoxLayout(box); l.setContentsMargins(0,0,0,6); l.setSpacing(2)
        a = QLabel(title); a.setStyleSheet("font-size:16px;font-weight:750;")
        b = QLabel(subtitle); b.setObjectName("muted")
        l.addWidget(a); l.addWidget(b)
        return box

    def _small_label(self, value: str) -> QLabel:
        label = QLabel(value)
        label.setStyleSheet(f"color:{C['muted']};font-size:11px;font-weight:750;margin-top:8px;")
        return label

    def _set_format(self, fmt: str) -> None:
        self.mp3.setChecked(fmt == "mp3")
        self.mp4.setChecked(fmt == "mp4")
        self.quality.setText(
            str(self.config.get("qualidade_audio", "192")) if fmt == "mp3"
            else str(self.config.get("qualidade_video", "1080p"))
        )

    def _resolve_input(self) -> None:
        value = self.input.text().strip()
        if not value:
            return
        self.input.setEnabled(False)
        worker = ResolveRunnable(value)
        worker.signals.resolved.connect(self._resolved)
        worker.signals.failed.connect(self._resolution_failed)
        self.pool.start(worker)

    @Slot(object)
    def _resolved(self, result: object) -> None:
        self.input.setEnabled(True)
        original = self.input.text().strip()
        self.input.clear()
        for url in result.urls:
            label = result.label if len(result.urls) == 1 else f"Playlist • {url[-11:]}"
            self._queue_download(url, label)
        self.statusBar().showMessage(f"Adicionado: {result.label}", 3500)

    @Slot(str)
    def _resolution_failed(self, message: str) -> None:
        self.input.setEnabled(True)
        QMessageBox.warning(self, "Não foi possível adicionar", message)

    def _queue_download(self, url: str, label: str) -> None:
        fmt = "mp3" if self.mp3.isChecked() else "mp4"
        quality = self.quality.text().strip() or ("192" if fmt == "mp3" else "1080p")
        start = self.start_time.text().strip() or None
        end = self.end_time.text().strip() or None
        try:
            validate_clip(start, end)
        except ValueError as exc:
            QMessageBox.warning(self, "Recorte inválido", str(exc))
            return

        spec = DownloadSpec(
            url=url,
            formato=fmt,
            destino=Path(self.destination.text()).expanduser(),
            qualidade_audio=quality if fmt == "mp3" else "192",
            qualidade_video=quality if fmt == "mp4" else "1080p",
            tempo_inicio=start,
            tempo_fim=end,
        )
        detail = f"{fmt.upper()} • {quality}"
        if start or end:
            detail += f" • {start or '00:00'}–{end or 'fim'}"
        card = QueueCard(label, fmt, detail)
        self.cards.append(card)
        self.queue_layout.insertWidget(self.queue_layout.count() - 1, card)
        worker = DownloadRunnable(spec)
        self.workers[card] = worker
        worker.signals.title.connect(card.set_title)
        worker.signals.progress.connect(card.set_progress)
        worker.signals.completed.connect(lambda c=card: self._completed(c))
        worker.signals.cancelled.connect(lambda c=card: self._cancelled(c))
        worker.signals.failed.connect(lambda msg, c=card: self._failed(c, msg))
        card.cancel_requested.connect(worker.cancel)
        self.pool.start(worker)
        self._refresh_stats()

    def _completed(self, card: QueueCard) -> None:
        card.mark_completed(); self.completed_count += 1; self.workers.pop(card, None)

    def _cancelled(self, card: QueueCard) -> None:
        card.mark_cancelled(); self.workers.pop(card, None)

    def _failed(self, card: QueueCard, message: str) -> None:
        card.mark_failed(message); self.workers.pop(card, None)

    def _refresh_stats(self) -> None:
        active = len(self.workers)
        total_speed = sum(c.speed for c in self.cards)
        self.queue_badge.setText(f"{active} ativos • {self.completed_count} concluídos")
        self.speed_label.setText(f"Velocidade total: {human_bytes(total_speed)}/s")

    def _toggle_clipboard(self, enabled: bool) -> None:
        self.clip_button.setText("●  Ativo — Desativar" if enabled else "●  Desligado — Ativar")
        self.privacy_label.setText("Clipboard ativo" if enabled else "Clipboard desligado")
        if enabled:
            self.last_clipboard = QApplication.clipboard().text().strip()
            self.clip_timer.start()
        else:
            self.clip_timer.stop()

    def _poll_clipboard(self) -> None:
        value = QApplication.clipboard().text().strip()
        if not value or value == self.last_clipboard:
            return
        self.last_clipboard = value
        kind, _ = classificar_link(value)
        if kind not in {LinkType.DIRETO, LinkType.PLAYLIST} or value in self.seen_clipboard:
            return
        self.seen_clipboard.add(value)
        self.input.setText(value)
        self._resolve_input()

    def _import_txt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar lista", "", "Arquivos de texto (*.txt)")
        if not path:
            return
        try:
            lines = [x.strip() for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao ler arquivo", str(exc)); return
        if not lines:
            return
        for value in lines[:200]:
            kind, normalized = classificar_link(value)
            if kind == LinkType.DIRETO:
                self._queue_download(normalized, "Importado de TXT")
            elif kind in {LinkType.PESQUISA_TEXTO, LinkType.PESQUISA_URL, LinkType.PLAYLIST}:
                worker = ResolveRunnable(value)
                worker.signals.resolved.connect(self._resolved)
                worker.signals.failed.connect(lambda msg: self.statusBar().showMessage(msg, 3000))
                self.pool.start(worker)

    def _choose_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pasta de destino", self.destination.text())
        if path:
            self.destination.setText(path)

    def _save_defaults(self) -> None:
        try:
            concurrent = max(1, min(int(self.concurrent.text()), 8))
        except ValueError:
            QMessageBox.warning(self, "Valor inválido", "Concorrência deve ser um número entre 1 e 8."); return
        fmt = "mp3" if self.mp3.isChecked() else "mp4"
        quality = self.quality.text().strip() or ("192" if fmt == "mp3" else "1080p")
        self.config.update(
            download_path=str(Path(self.destination.text()).expanduser()),
            formato_padrao=fmt,
            qualidade_audio=quality if fmt == "mp3" else self.config.get("qualidade_audio", "192"),
            qualidade_video=quality if fmt == "mp4" else self.config.get("qualidade_video", "1080p"),
            max_downloads_simultaneos=concurrent,
        )
        self.pool.setMaxThreadCount(concurrent)
        QMessageBox.information(self, "Preferências", "Configurações salvas localmente.")

    def _nav_hint(self, name: str) -> None:
        self.statusBar().showMessage(f"{name.strip()} será ampliado em uma próxima etapa; a fila e configurações já são funcionais.", 4000)


def iniciar_app() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = YouTubeDownloaderWindow()
    window.show()
    raise SystemExit(app.exec())
