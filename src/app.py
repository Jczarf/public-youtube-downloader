from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

import yt_dlp
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .config import Config, validate_download_path
from .downloader import DownloadSpec, Downloader, Progress, validate_clip
from .history import HistoryStore
from .resolver import (
    LinkType,
    classificar_link,
    detectar_contexto_playlist,
    resolver_entrada,
)
from .text_import import read_txt_entries
from .ui import (
    C,
    StyledComboBox,
    ask_confirmation,
    choose_font_family,
    choose_video_playlist_scope,
    display_path,
    human_datetime,
    make_nav_icon,
    plain_label,
    show_message,
)


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
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class DownloadSignals(QObject):
    started = Signal()
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
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        if self.downloader:
            self.downloader.cancelar()

    @Slot()
    def run(self) -> None:
        if self._cancel_requested:
            self.signals.cancelled.emit()
            return
        self.signals.started.emit()
        try:
            self.downloader = Downloader(self.spec)
            if self._cancel_requested:
                self.downloader.cancelar()
            ok = self.downloader.baixar(
                progress_callback=lambda p: self.signals.progress.emit(p),
                info_callback=lambda info: self.signals.title.emit(
                    str(info.get("title") or "Mídia")
                ),
            )
            if ok:
                self.signals.completed.emit()
            else:
                self.signals.cancelled.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class QueueCard(QFrame):
    cancel_requested = Signal()

    def __init__(self, label: str, formato: str, detail: str, spec: DownloadSpec) -> None:
        super().__init__()
        self.setObjectName("queueCard")
        self.setMinimumHeight(108)
        self.speed = 0.0
        self.spec = spec
        self.state = "queued"

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(9)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.icon = plain_label("♫" if formato == "mp3" else "▶")
        self.icon.setObjectName("mediaIcon")
        self.icon.setFixedSize(42, 42)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.icon)

        info = QVBoxLayout()
        info.setSpacing(3)
        self.title_label = plain_label(label)
        self.title_label.setObjectName("queueTitle")
        self.title_label.setToolTip(label)
        self.detail_label = plain_label(detail)
        self.detail_label.setObjectName("muted")
        info.addWidget(self.title_label)
        info.addWidget(self.detail_label)
        top.addLayout(info, 1)

        self.status = plain_label("Na fila")
        self.status.setObjectName("statusWaiting")
        top.addWidget(self.status)

        self.cancel_button = QPushButton("×")
        self.cancel_button.setObjectName("iconButton")
        self.cancel_button.setFixedSize(34, 34)
        self.cancel_button.setToolTip("Cancelar download")
        self.cancel_button.clicked.connect(self.cancel_requested)
        top.addWidget(self.cancel_button)
        root.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        bottom.addWidget(self.progress, 1)

        self.stats = plain_label("aguardando")
        self.stats.setObjectName("muted")
        self.stats.setMinimumWidth(130)
        self.stats.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(self.stats)
        root.addLayout(bottom)

    @property
    def display_title(self) -> str:
        return self.title_label.text().strip() or "Mídia"

    def _restyle_status(self, object_name: str, text: str) -> None:
        self.status.setText(text)
        self.status.setObjectName(object_name)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def set_title(self, value: str) -> None:
        value = value.strip() or "Mídia"
        self.title_label.setText(value[:92])
        self.title_label.setToolTip(value)

    def mark_running(self) -> None:
        if self.state in {"completed", "cancelled", "failed"}:
            return
        self.state = "running"
        self._restyle_status("statusActive", "Baixando")
        self.stats.setText("iniciando")

    def mark_cancelling(self) -> None:
        if self.state in {"completed", "cancelled", "failed"}:
            return
        self.state = "cancelling"
        self._restyle_status("statusWaiting", "Cancelando")
        self.stats.setText("aguarde…")
        self.cancel_button.setEnabled(False)

    def set_progress(self, p: Progress) -> None:
        self.state = "running"
        self.speed = p.speed
        self.progress.setValue(int(p.percent * 1000))
        self._restyle_status("statusActive", f"{p.percent * 100:.0f}%")
        self.stats.setText(f"{human_bytes(p.speed)}/s" if p.speed else "baixando")

    def mark_completed(self) -> None:
        self.state = "completed"
        self.progress.setValue(1000)
        self._restyle_status("statusDone", "Concluído")
        self.stats.setText("concluído")
        self.cancel_button.setEnabled(False)
        self.speed = 0.0

    def mark_cancelled(self) -> None:
        self.state = "cancelled"
        self._restyle_status("statusWaiting", "Cancelado")
        self.stats.setText("cancelado")
        self.cancel_button.setEnabled(False)
        self.speed = 0.0

    def mark_failed(self, message: str) -> None:
        self.state = "failed"
        self._restyle_status("statusError", "Erro")
        short = message.strip() or "Falha no download"
        self.stats.setText(short[:35])
        self.stats.setToolTip(short)
        self.cancel_button.setEnabled(False)
        self.speed = 0.0


class YouTubeDownloaderWindow(QMainWindow):
    PAGE_META = {
        0: ("Downloader de mídia", "Links, pesquisa, filas e recortes em uma experiência única."),
        1: ("Histórico", "Downloads concluídos, cancelados e falhas registrados somente neste computador."),
        2: ("Listas TXT", "Revise uma lista antes de enviar vários itens para a fila."),
    }

    def __init__(self) -> None:
        super().__init__()
        self.config = Config()
        self.history = HistoryStore(self.config.config_file.parent / "history.json")
        self.resolve_pool = QThreadPool(self)
        self.resolve_pool.setMaxThreadCount(4)
        self.download_pool = QThreadPool(self)
        self.download_pool.setMaxThreadCount(int(self.config.get("max_downloads_simultaneos", 3)))

        self.cards: list[QueueCard] = []
        self.workers: dict[QueueCard, DownloadRunnable] = {}
        self.queued_cards: set[QueueCard] = set()
        self.running_cards: set[QueueCard] = set()
        self.seen_clipboard: set[str] = set()
        self.last_clipboard = ""
        self.txt_items: list[tuple[str, LinkType, str]] = []
        self.resolve_busy = False
        self._toast_generation = 0
        self._closing = False

        self.setWindowTitle("YouTube Downloader")
        self.resize(1600, 960)
        self.setMinimumSize(1080, 700)
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
        self.setFont(QFont(choose_font_family(), 10))
        self.setStyleSheet(
            f"""
            QMainWindow {{ background:{C['window']}; }}
            QWidget#root {{ background:{C['window']}; color:{C['text']}; }}
            QFrame#appShell {{ background:{C['bg']}; border:1px solid #303844; border-radius:24px; }}
            QFrame#sidebar {{ background:{C['sidebar']}; border:none; border-right:1px solid {C['border']}; border-top-left-radius:23px; border-bottom-left-radius:23px; }}
            QWidget#mainShell, QStackedWidget#pages, QStackedWidget#queueStack, QStackedWidget#historyStack {{ background:{C['bg']}; color:{C['text']}; border:none; }}
            QFrame#panel, QFrame#historyCard {{ background:{C['panel']}; border:1px solid {C['border']}; border-radius:16px; }}
            QFrame#queueCard {{ background:{C['panel2']}; border:1px solid #283342; border-radius:15px; }}
            QFrame#emptyState {{ background:#0b1017; border:1px dashed #263241; border-radius:15px; }}
            QFrame#cutCard, QFrame#clipControl {{ background:{C['input']}; border:1px solid #2a3442; border-radius:12px; }}
            QFrame#privacyCard {{ background:#0f141c; border:1px solid {C['border']}; border-radius:14px; }}
            QLabel {{ color:{C['text']}; background:transparent; border:none; }}
            QLabel#muted {{ color:{C['muted']}; font-size:12px; }}
            QLabel#eyebrow {{ color:{C['muted']}; font-size:10px; font-weight:800; }}
            QLabel#queueTitle {{ font-size:15px; font-weight:750; }}
            QLabel#emptyTitle {{ color:{C['text']}; font-size:18px; font-weight:800; }}
            QLabel#emptyHint {{ color:{C['muted']}; font-size:12px; }}
            QLabel#mediaIcon {{ background:#24151a; color:{C['accent']}; border-radius:10px; font-size:18px; font-weight:800; }}
            QLabel#statusWaiting {{ color:{C['amber']}; background:#292312; border-radius:10px; padding:5px 10px; font-weight:700; }}
            QLabel#statusActive {{ color:{C['blue']}; background:#152033; border-radius:10px; padding:5px 10px; font-weight:700; }}
            QLabel#statusDone {{ color:{C['green']}; background:#102319; border-radius:10px; padding:5px 10px; font-weight:700; }}
            QLabel#statusError {{ color:{C['accent']}; background:#28151a; border-radius:10px; padding:5px 10px; font-weight:700; }}
            QLabel#queueBadge {{ color:{C['text']}; background:#161e29; border:1px solid #2b3645; border-radius:11px; padding:5px 10px; font-weight:750; }}
            QLabel#successPill {{ color:{C['green']}; background:#102319; border-radius:11px; padding:5px 10px; font-weight:750; }}
            QLabel#infoPill {{ color:{C['blue']}; background:#152033; border-radius:11px; padding:5px 10px; font-weight:750; }}
            QLabel#valuePill {{ color:{C['text']}; background:#1a2230; border:1px solid #2d3948; border-radius:10px; padding:4px 9px; font-weight:800; }}
            QLabel#clipDotOff {{ color:#657182; font-size:15px; }}
            QLabel#clipDotOn {{ color:{C['green']}; font-size:15px; }}
            QLabel#clipStateOff {{ color:{C['muted']}; font-weight:750; }}
            QLabel#clipStateOn {{ color:{C['green']}; font-weight:750; }}
            QLabel#privacyOff {{ color:{C['muted']}; font-weight:800; }}
            QLabel#privacyOn {{ color:{C['green']}; font-weight:800; }}
            QLabel#toastInfo, QLabel#toastSuccess, QLabel#toastError {{ border-radius:8px; padding:4px 9px; font-size:11px; font-weight:650; }}
            QLabel#toastInfo {{ color:{C['blue']}; background:#101927; }}
            QLabel#toastSuccess {{ color:{C['green']}; background:#0e1d16; }}
            QLabel#toastError {{ color:{C['accent']}; background:#241317; }}
            QPushButton {{ background:#161e29; color:{C['text']}; border:1px solid #2b3645; border-radius:10px; padding:10px 14px; font-weight:650; }}
            QPushButton:hover {{ background:#1a2431; border-color:#465569; }}
            QPushButton:pressed {{ background:#111821; }}
            QPushButton:focus {{ border:1px solid {C['accent']}; }}
            QPushButton:disabled {{ color:#596474; background:#111720; border-color:#202936; }}
            QPushButton#primary {{ background:{C['accent']}; color:#16090b; border:none; font-weight:850; }}
            QPushButton#primary:hover {{ background:{C['accent_hover']}; }}
            QPushButton#danger {{ background:#28151a; color:{C['accent']}; border:1px solid #5d2b34; }}
            QPushButton#nav {{ background:transparent; border:1px solid transparent; color:{C['muted']}; text-align:left; padding:12px 14px; min-height:22px; font-weight:700; }}
            QPushButton#nav:hover {{ background:#14131a; color:{C['text']}; }}
            QPushButton#nav:checked {{ background:#29171c; color:{C['text']}; border:1px solid #51262d; }}
            QPushButton#iconButton {{ padding:0; background:transparent; color:{C['muted']}; border:none; font-size:21px; }}
            QPushButton#folderButton {{ min-width:42px; max-width:42px; padding:9px 0; }}
            QPushButton#formatButton {{ background:#151d28; min-height:22px; }}
            QPushButton#formatButton:checked {{ background:#2b1920; color:{C['text']}; border:1px solid #5d2b34; }}
            QPushButton#clipAction {{ min-width:72px; padding:7px 11px; }}
            QPushButton#clipAction:checked {{ background:#102319; color:{C['green']}; border:1px solid #24573a; }}
            QPushButton#quietAction {{ background:transparent; color:{C['muted']}; border:1px solid transparent; padding:7px 9px; }}
            QPushButton#quietAction:hover {{ color:{C['text']}; background:#151d28; }}
            QLineEdit, StyledComboBox, QPlainTextEdit {{ background:{C['input']}; color:{C['text']}; border:1px solid #2a3442; border-radius:11px; padding:10px 12px; min-height:22px; selection-background-color:{C['accent']}; }}
            QLineEdit:focus, StyledComboBox:focus, QPlainTextEdit:focus {{ border-color:{C['accent']}; }}
            QLineEdit#cutInput {{ background:transparent; border:none; border-radius:0; padding:2px 0; min-height:20px; font-weight:700; }}
            StyledComboBox::drop-down {{ border:none; width:34px; }}
            StyledComboBox::down-arrow {{ image:none; width:0; height:0; }}
            QComboBox QAbstractItemView {{ background:#10141c; color:{C['text']}; border:1px solid #2a3442; selection-background-color:#2b1920; outline:none; }}
            QSlider::groove:horizontal {{ background:#0a0f16; height:8px; border-radius:4px; }}
            QSlider::sub-page:horizontal {{ background:{C['accent']}; border-radius:4px; }}
            QSlider::handle:horizontal {{ background:{C['text']}; border:2px solid {C['accent']}; width:16px; margin:-6px 0; border-radius:9px; }}
            QProgressBar {{ background:#080c12; border:none; border-radius:4px; min-height:8px; max-height:8px; }}
            QProgressBar::chunk {{ background:{C['accent']}; border-radius:4px; }}
            QScrollArea {{ background:transparent; border:none; }}
            QWidget#queueViewport, QWidget#queueBody, QWidget#historyViewport, QWidget#historyBody, QWidget#settingsViewport {{ background:transparent; }}
            QScrollBar:vertical {{ background:transparent; width:8px; margin:2px; }}
            QScrollBar::handle:vertical {{ background:#2a3543; border-radius:4px; min-height:30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QScrollBar:horizontal {{ height:0; background:transparent; }}
            QToolTip {{ background:#151d28; color:{C['text']}; border:1px solid #344154; padding:5px 7px; }}
            """
        )

    def _panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        return frame

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)
        app_shell = QFrame()
        app_shell.setObjectName("appShell")
        outer.addWidget(app_shell)
        shell = QHBoxLayout(app_shell)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(238)
        shell.addWidget(sidebar)
        self._build_sidebar(sidebar)

        main = QWidget()
        main.setObjectName("mainShell")
        body = QVBoxLayout(main)
        body.setContentsMargins(24, 20, 24, 14)
        body.setSpacing(14)
        shell.addWidget(main, 1)

        header = QHBoxLayout()
        htext = QVBoxLayout()
        htext.setSpacing(4)
        self.page_title = plain_label()
        self.page_title.setStyleSheet("font-size:28px;font-weight:850;")
        self.page_subtitle = plain_label()
        self.page_subtitle.setObjectName("muted")
        self.page_subtitle.setWordWrap(True)
        htext.addWidget(self.page_title)
        htext.addWidget(self.page_subtitle)
        header.addLayout(htext)
        header.addStretch()

        ffmpeg_ok = bool(shutil.which("ffmpeg"))
        self.ffmpeg_badge = plain_label("FFmpeg ✓" if ffmpeg_ok else "FFmpeg ausente")
        self.ffmpeg_badge.setObjectName("successPill" if ffmpeg_ok else "valuePill")
        header.addWidget(self.ffmpeg_badge)
        self.ytdlp_badge = plain_label(f"yt-dlp {yt_dlp.version.__version__}")
        self.ytdlp_badge.setObjectName("infoPill")
        header.addWidget(self.ytdlp_badge)
        body.addLayout(header)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        self.pages.addWidget(self._build_queue_page())
        self.pages.addWidget(self._build_history_page())
        self.pages.addWidget(self._build_txt_page())
        body.addWidget(self.pages, 1)

        self.toast_label = plain_label()
        self.toast_label.setObjectName("toastInfo")
        self.toast_label.setFixedHeight(26)
        self.toast_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        body.addWidget(self.toast_label)
        self._navigate(0)

    def _build_sidebar(self, sidebar: QFrame) -> None:
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(18, 24, 18, 20)
        lay.setSpacing(8)
        brand = plain_label("▶  YouTube Downloader")
        brand.setStyleSheet(f"font-size:16px;font-weight:850;color:{C['text']};")
        lay.addWidget(brand)
        sub = plain_label("DOWNLOADER DE MÍDIA")
        sub.setObjectName("eyebrow")
        lay.addWidget(sub)
        lay.addSpacing(24)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for index, (label, icon_kind) in enumerate((("Fila", "queue"), ("Histórico", "history"), ("Listas TXT", "list"))):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setIcon(make_nav_icon(icon_kind, C["muted"]))
            button.toggled.connect(lambda checked, b=button, kind=icon_kind: b.setIcon(make_nav_icon(kind, C["accent"] if checked else C["muted"])))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            lay.addWidget(button)
        self.nav_group.idClicked.connect(self._navigate)
        self.nav_buttons[0].setChecked(True)
        lay.addStretch()

        privacy = QFrame()
        privacy.setObjectName("privacyCard")
        pv = QVBoxLayout(privacy)
        pv.setContentsMargins(14, 14, 14, 14)
        pv.setSpacing(6)
        pv.addWidget(self._small_label("PRIVACIDADE", margin_top=False))
        self.privacy_label = plain_label("Clipboard desligado")
        self.privacy_label.setObjectName("privacyOff")
        pv.addWidget(self.privacy_label)
        note = plain_label("Nenhum link é lido até você ativar o monitor.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        pv.addWidget(note)
        lay.addWidget(privacy)
        local = plain_label("Uso pessoal • local")
        local.setObjectName("muted")
        lay.addWidget(local)

    def _build_queue_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        add_row = QHBoxLayout()
        add_row.setSpacing(16)
        add_panel = self._panel()
        add_layout = QVBoxLayout(add_panel)
        add_layout.setContentsMargins(20, 14, 20, 14)
        add_layout.setSpacing(8)
        add_layout.addWidget(self._heading("Adicionar conteúdo", "Cole um link, uma pesquisa ou importe uma lista TXT."))
        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Link do YouTube ou nome da música...")
        self.input.returnPressed.connect(self._resolve_input)
        input_row.addWidget(self.input, 1)
        txt = QPushButton("TXT")
        txt.setToolTip("Abrir importador de listas TXT")
        txt.clicked.connect(lambda: self._navigate(2))
        input_row.addWidget(txt)
        self.add_button = QPushButton("+")
        self.add_button.setObjectName("primary")
        self.add_button.setFixedWidth(66)
        self.add_button.clicked.connect(self._resolve_input)
        input_row.addWidget(self.add_button)
        add_layout.addLayout(input_row)
        add_row.addWidget(add_panel, 1)

        clip_panel = self._panel()
        clip_panel.setMinimumWidth(245)
        clip_panel.setMaximumWidth(290)
        clip_layout = QVBoxLayout(clip_panel)
        clip_layout.setContentsMargins(18, 14, 18, 14)
        clip_layout.setSpacing(8)
        clip_layout.addWidget(self._heading("Monitor de clipboard", "Só lê links após ativação explícita nesta sessão."))
        clip_control = QFrame()
        clip_control.setObjectName("clipControl")
        clip_row = QHBoxLayout(clip_control)
        clip_row.setContentsMargins(12, 7, 8, 7)
        self.clip_status_dot = plain_label("●")
        self.clip_status_dot.setObjectName("clipDotOff")
        clip_row.addWidget(self.clip_status_dot)
        self.clip_status_text = plain_label("Desligado")
        self.clip_status_text.setObjectName("clipStateOff")
        clip_row.addWidget(self.clip_status_text)
        clip_row.addStretch()
        self.clip_button = QPushButton("Ativar")
        self.clip_button.setObjectName("clipAction")
        self.clip_button.setCheckable(True)
        self.clip_button.toggled.connect(self._toggle_clipboard)
        clip_row.addWidget(self.clip_button)
        clip_layout.addWidget(clip_control)
        add_row.addWidget(clip_panel)
        layout.addLayout(add_row)

        content = QHBoxLayout()
        content.setSpacing(16)
        queue_panel = self._panel()
        qlayout = QVBoxLayout(queue_panel)
        qlayout.setContentsMargins(20, 18, 20, 18)
        qlayout.setSpacing(12)
        qhead = QHBoxLayout()
        qtitle = plain_label("Fila de downloads")
        qtitle.setStyleSheet("font-size:20px;font-weight:850;")
        qhead.addWidget(qtitle)
        self.queue_badge = plain_label("0 baixando • 0 aguardando • 0 concluídos")
        self.queue_badge.setObjectName("queueBadge")
        qhead.addWidget(self.queue_badge)
        qhead.addStretch()
        self.speed_label = plain_label("Velocidade total: 0.0 B/s")
        self.speed_label.setObjectName("muted")
        qhead.addWidget(self.speed_label)
        self.clear_finished_button = QPushButton("Limpar finalizados")
        self.clear_finished_button.setObjectName("quietAction")
        self.clear_finished_button.setEnabled(False)
        self.clear_finished_button.clicked.connect(self._clear_finished_cards)
        qhead.addWidget(self.clear_finished_button)
        qlayout.addLayout(qhead)

        self.queue_stack = QStackedWidget()
        self.queue_stack.setObjectName("queueStack")
        self.empty_state = QFrame()
        self.empty_state.setObjectName("emptyState")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(28, 28, 28, 28)
        empty_layout.addStretch()
        empty_icon = plain_label("⇩")
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setStyleSheet(f"color:{C['accent']};font-size:34px;font-weight:850;")
        empty_title = plain_label("Sua fila está vazia")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = plain_label("Cole um link, pesquise uma mídia ou importe uma lista TXT para começar.")
        empty_hint.setObjectName("emptyHint")
        empty_hint.setWordWrap(True)
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_icon)
        empty_layout.addSpacing(8)
        empty_layout.addWidget(empty_title)
        empty_layout.addSpacing(4)
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch()
        self.queue_stack.addWidget(self.empty_state)

        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.queue_scroll.viewport().setObjectName("queueViewport")
        scroll_body = QWidget()
        scroll_body.setObjectName("queueBody")
        self.queue_layout = QVBoxLayout(scroll_body)
        self.queue_layout.setContentsMargins(0, 2, 2, 2)
        self.queue_layout.setSpacing(10)
        self.queue_layout.addStretch()
        self.queue_scroll.setWidget(scroll_body)
        list_layout.addWidget(self.queue_scroll)
        self.queue_stack.addWidget(list_page)
        qlayout.addWidget(self.queue_stack, 1)
        content.addWidget(queue_panel, 1)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.settings_scroll.setMinimumWidth(300)
        self.settings_scroll.setMaximumWidth(344)
        self.settings_scroll.viewport().setObjectName("settingsViewport")

        settings = self._panel()
        settings.setMinimumWidth(0)
        self.quick_settings_panel = settings
        sl = QVBoxLayout(settings)
        sl.setContentsMargins(18, 14, 18, 14)
        sl.setSpacing(6)
        s_title = plain_label("Configuração rápida")
        s_title.setStyleSheet("font-size:20px;font-weight:850;")
        sl.addWidget(s_title)
        sl.addWidget(self._small_label("Formato", margin_top=False))
        fmtrow = QHBoxLayout()
        self.mp3 = QPushButton("MP3")
        self.mp4 = QPushButton("MP4")
        self.format_group = QButtonGroup(self)
        self.format_group.setExclusive(True)
        for index, button in enumerate((self.mp3, self.mp4)):
            button.setObjectName("formatButton")
            button.setCheckable(True)
            self.format_group.addButton(button, index)
        self.mp3.setChecked(self.config.get("formato_padrao") == "mp3")
        self.mp4.setChecked(not self.mp3.isChecked())
        self.mp3.clicked.connect(lambda: self._set_format("mp3"))
        self.mp4.clicked.connect(lambda: self._set_format("mp4"))
        fmtrow.addWidget(self.mp3)
        fmtrow.addWidget(self.mp4)
        sl.addLayout(fmtrow)
        sl.addWidget(self._small_label("Qualidade", margin_top=False))
        self.quality = StyledComboBox()
        self.quality.setMinimumHeight(44)
        self._populate_quality_combo()
        sl.addWidget(self.quality)

        sl.addWidget(self._small_label("Recorte • somente neste item", margin_top=False))
        cut_card = QFrame()
        cut_card.setObjectName("cutCard")
        cut = QHBoxLayout(cut_card)
        cut.setContentsMargins(14, 8, 14, 8)
        start_box = QVBoxLayout()
        start_box.setSpacing(2)
        start_label = plain_label("De")
        start_label.setObjectName("eyebrow")
        self.start_time = QLineEdit()
        self.start_time.setObjectName("cutInput")
        self.start_time.setPlaceholderText("00:03")
        start_box.addWidget(start_label)
        start_box.addWidget(self.start_time)
        cut.addLayout(start_box, 1)
        separator = plain_label("→")
        separator.setStyleSheet(f"color:{C['muted']};font-weight:800;")
        cut.addWidget(separator)
        end_box = QVBoxLayout()
        end_box.setSpacing(2)
        end_label = plain_label("Até")
        end_label.setObjectName("eyebrow")
        self.end_time = QLineEdit()
        self.end_time.setObjectName("cutInput")
        self.end_time.setPlaceholderText("02:30")
        end_box.addWidget(end_label)
        end_box.addWidget(self.end_time)
        cut.addLayout(end_box, 1)
        sl.addWidget(cut_card)

        sl.addWidget(self._small_label("Pasta de destino", margin_top=False))
        destination_row = QHBoxLayout()
        self.destination = QLineEdit(display_path(str(self.config.get("download_path"))))
        destination_row.addWidget(self.destination, 1)
        choose = QPushButton("…")
        choose.setObjectName("folderButton")
        choose.setToolTip("Escolher pasta")
        choose.clicked.connect(self._choose_destination)
        destination_row.addWidget(choose)
        sl.addLayout(destination_row)

        sl.addWidget(self._small_label("Concorrência", margin_top=False))
        concurrency_row = QHBoxLayout()
        self.concurrent_slider = QSlider(Qt.Orientation.Horizontal)
        self.concurrent_slider.setRange(1, 8)
        self.concurrent_slider.setValue(self.download_pool.maxThreadCount())
        self.concurrent_value = plain_label(str(self.download_pool.maxThreadCount()))
        self.concurrent_value.setObjectName("valuePill")
        self.concurrent_slider.valueChanged.connect(lambda value: self.concurrent_value.setText(str(value)))
        concurrency_row.addWidget(self.concurrent_slider, 1)
        concurrency_row.addWidget(self.concurrent_value)
        sl.addLayout(concurrency_row)
        self.save_preferences_button = QPushButton("Salvar preferências")
        self.save_preferences_button.clicked.connect(self._save_defaults)
        sl.addWidget(self.save_preferences_button)
        sl.addSpacing(2)
        self.settings_legal = plain_label("Uso pessoal. Baixe somente conteúdo que você tem direito de acessar e respeite os termos da plataforma.")
        self.settings_legal.setWordWrap(True)
        self.settings_legal.setObjectName("muted")
        sl.addWidget(self.settings_legal)

        settings.setMinimumHeight(sl.sizeHint().height())
        self.settings_scroll.setWidget(settings)
        content.addWidget(self.settings_scroll)
        layout.addLayout(content, 1)
        return page

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = self._panel()
        root = QVBoxLayout(panel)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)
        toolbar = QHBoxLayout()
        title = plain_label("Atividade recente")
        title.setStyleSheet("font-size:20px;font-weight:850;")
        toolbar.addWidget(title)
        toolbar.addStretch()
        open_folder = QPushButton("Abrir pasta padrão")
        open_folder.clicked.connect(lambda: self._open_folder(Path(str(self.config.get("download_path"))), create=True))
        toolbar.addWidget(open_folder)
        self.clear_history_button = QPushButton("Limpar histórico")
        self.clear_history_button.setObjectName("danger")
        self.clear_history_button.clicked.connect(self._clear_history)
        toolbar.addWidget(self.clear_history_button)
        root.addLayout(toolbar)
        note = plain_label("O histórico é armazenado localmente em JSON, com dados mínimos, e não é enviado ao GitHub.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)
        self.history_summary = plain_label()
        self.history_summary.setObjectName("muted")
        root.addWidget(self.history_summary)

        self.history_stack = QStackedWidget()
        self.history_stack.setObjectName("historyStack")
        history_empty = QFrame()
        history_empty.setObjectName("emptyState")
        empty_box = QVBoxLayout(history_empty)
        empty_box.addStretch()
        empty_title = plain_label("Nenhum download finalizado ainda")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = plain_label("Quando um item terminar, falhar ou for cancelado, ele aparecerá aqui.")
        empty_hint.setObjectName("emptyHint")
        empty_hint.setWordWrap(True)
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_box.addWidget(empty_title)
        empty_box.addWidget(empty_hint)
        empty_box.addStretch()
        self.history_stack.addWidget(history_empty)

        history_list = QWidget()
        history_list_layout = QVBoxLayout(history_list)
        history_list_layout.setContentsMargins(0, 0, 0, 0)
        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.history_scroll.viewport().setObjectName("historyViewport")
        history_body = QWidget()
        history_body.setObjectName("historyBody")
        self.history_layout = QVBoxLayout(history_body)
        self.history_layout.setContentsMargins(0, 4, 2, 2)
        self.history_layout.setSpacing(10)
        self.history_layout.addStretch()
        self.history_scroll.setWidget(history_body)
        history_list_layout.addWidget(self.history_scroll)
        self.history_stack.addWidget(history_list)
        root.addWidget(self.history_stack, 1)
        layout.addWidget(panel, 1)
        self._refresh_history()
        return page

    def _build_txt_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = self._panel()
        root = QVBoxLayout(panel)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)
        top = QHBoxLayout()
        title = plain_label("Importar lista TXT")
        title.setStyleSheet("font-size:20px;font-weight:850;")
        top.addWidget(title)
        top.addStretch()
        choose = QPushButton("Escolher arquivo")
        choose.clicked.connect(self._select_txt_file)
        top.addWidget(choose)
        add = QPushButton("Adicionar válidos à fila")
        add.setObjectName("primary")
        add.clicked.connect(self._enqueue_txt_items)
        top.addWidget(add)
        root.addLayout(top)
        self.txt_path_label = plain_label("Nenhum arquivo selecionado")
        self.txt_path_label.setObjectName("muted")
        self.txt_path_label.setWordWrap(True)
        root.addWidget(self.txt_path_label)
        self.txt_summary = plain_label("0 entradas analisadas")
        self.txt_summary.setObjectName("queueBadge")
        root.addWidget(self.txt_summary, alignment=Qt.AlignmentFlag.AlignLeft)
        self.txt_preview = QPlainTextEdit()
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.txt_preview.setPlaceholderText("Cada linha pode conter um vídeo, playlist, URL de pesquisa ou texto para pesquisa.")
        root.addWidget(self.txt_preview, 1)
        hint = plain_label("A prévia não inicia downloads. Arquivos têm limite de 2 MB, 500 entradas e 4096 caracteres por linha.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        layout.addWidget(panel, 1)
        return page

    def _heading(self, title: str, subtitle: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 6)
        a = plain_label(title)
        a.setStyleSheet("font-size:16px;font-weight:800;")
        b = plain_label(subtitle)
        b.setObjectName("muted")
        b.setWordWrap(True)
        layout.addWidget(a)
        layout.addWidget(b)
        return box

    def _small_label(self, value: str, margin_top: bool = True) -> QLabel:
        label = plain_label(value)
        label.setStyleSheet(f"color:{C['muted']};font-size:11px;font-weight:800;" + ("margin-top:8px;" if margin_top else ""))
        return label

    @Slot(int)
    def _navigate(self, index: int) -> None:
        if not 0 <= index < self.pages.count():
            return
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        title, subtitle = self.PAGE_META[index]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        if index == 1:
            self._refresh_history()

    def _populate_quality_combo(self) -> None:
        fmt = "mp3" if self.mp3.isChecked() else "mp4"
        current = str(self.config.get("qualidade_audio", "192")) if fmt == "mp3" else str(self.config.get("qualidade_video", "1080p"))
        self.quality.clear()
        self.quality.addItems(["128 kbps", "192 kbps", "256 kbps", "320 kbps"] if fmt == "mp3" else ["480p", "720p", "1080p"])
        self.quality.setCurrentText(f"{current} kbps" if fmt == "mp3" else current)

    def _quality_value(self) -> str:
        return self.quality.currentText().strip().replace(" kbps", "")

    def _set_format(self, fmt: str) -> None:
        self.mp3.setChecked(fmt == "mp3")
        self.mp4.setChecked(fmt == "mp4")
        self._populate_quality_combo()

    def _set_resolve_busy(self, busy: bool) -> None:
        self.resolve_busy = busy
        self.input.setEnabled(not busy)
        self.add_button.setEnabled(not busy)
        self.add_button.setText("…" if busy else "+")

    def _ensure_ffmpeg(self) -> bool:
        if shutil.which("ffmpeg"):
            return True
        show_message(self, "FFmpeg necessário", "Instale o FFmpeg antes de iniciar downloads. Ele é usado para áudio, merge de vídeo e recortes.", kind="warning")
        return False

    def _destination_path(self) -> Path | None:
        try:
            return validate_download_path(self.destination.text())
        except ValueError as exc:
            show_message(self, "Pasta de destino inválida", str(exc), kind="warning")
            return None

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

        if not self._ensure_ffmpeg():
            return
        value = self.input.text().strip()
        self._set_resolve_busy(True)
        worker = ResolveRunnable(value)
        worker.signals.resolved.connect(self._resolved_from_input)
        worker.signals.failed.connect(self._resolution_failed)
        self.resolve_pool.start(worker)

    @Slot(object)
    def _resolved_from_input(self, result: object) -> None:
        if self._closing:
            return
        self._set_resolve_busy(False)
        self.input.clear()
        self._queue_resolved_result(result)
        self.input.setFocus()

    @Slot(object)
    def _enqueue_resolved(self, result: object) -> None:
        if not self._closing:
            self._queue_resolved_result(result)

    def _queue_resolved_result(self, result: object) -> None:
        urls = list(getattr(result, "urls", []) or [])
        label = str(getattr(result, "label", "Mídia"))
        if not urls:
            self._show_toast("Nenhum item válido foi encontrado.", kind="error")
            return
        destination = self._destination_path()
        if destination is None:
            return
        for url in urls:
            item_label = label if len(urls) == 1 else f"Playlist • {str(url)[-11:]}"
            self._queue_download(str(url), item_label, destination=destination)
        self._show_toast(f"Adicionado: {label}", kind="success")

    @Slot(str)
    def _resolution_failed(self, message: str) -> None:
        if self._closing:
            return
        self._set_resolve_busy(False)
        self.input.setFocus()
        show_message(self, "Não foi possível adicionar", message, kind="error")

    def _queue_download(self, url: str, label: str, *, destination: Path | None = None) -> None:
        if not self._ensure_ffmpeg():
            return
        destination = destination or self._destination_path()
        if destination is None:
            return
        fmt = "mp3" if self.mp3.isChecked() else "mp4"
        quality = self._quality_value() or ("192" if fmt == "mp3" else "1080p")
        start = self.start_time.text().strip() or None
        end = self.end_time.text().strip() or None
        try:
            validate_clip(start, end)
        except ValueError as exc:
            show_message(self, "Recorte inválido", str(exc), kind="warning")
            return

        spec = DownloadSpec(url=url, formato=fmt, destino=destination, qualidade_audio=quality if fmt == "mp3" else "192", qualidade_video=quality if fmt == "mp4" else "1080p", tempo_inicio=start, tempo_fim=end)
        detail = f"{fmt.upper()} • {quality}{' kbps' if fmt == 'mp3' else ''}"
        if start or end:
            detail += f" • {start or '00:00'}–{end or 'fim'}"
        card = QueueCard(label, fmt, detail, spec)
        self.cards.append(card)
        self.queue_layout.insertWidget(self.queue_layout.count() - 1, card)
        self.queue_stack.setCurrentIndex(1)
        worker = DownloadRunnable(spec)
        self.workers[card] = worker
        self.queued_cards.add(card)
        worker.signals.started.connect(lambda c=card: self._started(c))
        worker.signals.title.connect(card.set_title)
        worker.signals.progress.connect(card.set_progress)
        worker.signals.completed.connect(lambda c=card: self._completed(c))
        worker.signals.cancelled.connect(lambda c=card: self._cancelled(c))
        worker.signals.failed.connect(lambda msg, c=card: self._failed(c, msg))
        card.cancel_requested.connect(lambda c=card, w=worker: self._request_cancel(c, w))
        self.download_pool.start(worker)
        self._refresh_stats()

    def _started(self, card: QueueCard) -> None:
        if card not in self.workers or self._closing:
            return
        self.queued_cards.discard(card)
        self.running_cards.add(card)
        card.mark_running()
        self._refresh_stats()

    def _request_cancel(self, card: QueueCard, worker: DownloadRunnable) -> None:
        if card not in self.workers:
            return
        worker.cancel()
        if card in self.queued_cards and self.download_pool.tryTake(worker):
            self._cancelled(card)
            return
        card.mark_cancelling()
        self._refresh_stats()

    def _record_history(self, card: QueueCard, status: str, message: str = "") -> None:
        self.history.add({"title": card.display_title, "status": status, "format": card.spec.formato.upper(), "destination": str(card.spec.destino), "message": message[:240], "finished_at": datetime.now().astimezone().isoformat(timespec="seconds")})
        self._refresh_history()

    def _finish_worker(self, card: QueueCard) -> None:
        self.workers.pop(card, None)
        self.queued_cards.discard(card)
        self.running_cards.discard(card)

    def _completed(self, card: QueueCard) -> None:
        if card.state == "completed" or self._closing:
            return
        self._finish_worker(card)
        card.mark_completed()
        self._record_history(card, "concluído")
        self._refresh_stats()

    def _cancelled(self, card: QueueCard) -> None:
        if card.state == "cancelled" or self._closing:
            return
        self._finish_worker(card)
        card.mark_cancelled()
        self._record_history(card, "cancelado")
        self._refresh_stats()

    def _failed(self, card: QueueCard, message: str) -> None:
        if card.state == "failed" or self._closing:
            return
        self._finish_worker(card)
        card.mark_failed(message)
        self._record_history(card, "erro", message)
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        active = len(self.running_cards)
        waiting = len(self.queued_cards)
        completed = sum(1 for card in self.cards if card.state == "completed")
        total_speed = sum(card.speed for card in self.running_cards)
        self.queue_badge.setText(f"{active} baixando • {waiting} aguardando • {completed} concluídos")
        self.speed_label.setText(f"Velocidade total: {human_bytes(total_speed)}/s")
        self.clear_finished_button.setEnabled(any(card.state in {"completed", "cancelled", "failed"} for card in self.cards))
        if not self.cards:
            self.queue_stack.setCurrentIndex(0)

    def _clear_finished_cards(self) -> None:
        removable = [card for card in self.cards if card.state in {"completed", "cancelled", "failed"}]
        for card in removable:
            self.queue_layout.removeWidget(card)
            self.cards.remove(card)
            card.deleteLater()
        self._refresh_stats()
        if removable:
            self._show_toast(f"{len(removable)} item(ns) removido(s) da fila visual.")

    def _restyle(self, widget: QWidget, object_name: str) -> None:
        widget.setObjectName(object_name)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _toggle_clipboard(self, enabled: bool) -> None:
        self.clip_button.setText("Desativar" if enabled else "Ativar")
        self.clip_status_text.setText("Ativo" if enabled else "Desligado")
        self.privacy_label.setText("Clipboard ativo" if enabled else "Clipboard desligado")
        self._restyle(self.clip_status_dot, "clipDotOn" if enabled else "clipDotOff")
        self._restyle(self.clip_status_text, "clipStateOn" if enabled else "clipStateOff")
        self._restyle(self.privacy_label, "privacyOn" if enabled else "privacyOff")
        if enabled:
            self.last_clipboard = QApplication.clipboard().text().strip()
            self.clip_timer.start()
        else:
            self.clip_timer.stop()

    def _poll_clipboard(self) -> None:
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

    def _select_txt_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar lista", "", "Arquivos de texto (*.txt)")
        if not path:
            return
        try:
            lines = read_txt_entries(path)
        except ValueError as exc:
            show_message(self, "Erro ao ler arquivo", str(exc), kind="error")
            return
        self.txt_items.clear()
        preview: list[str] = []
        valid_count = 0
        for value in lines:
            kind, normalized = classificar_link(value)
            valid = kind in {LinkType.DIRETO, LinkType.PLAYLIST, LinkType.PESQUISA_TEXTO, LinkType.PESQUISA_URL}
            valid_count += int(valid)
            self.txt_items.append((value, kind, normalized))
            preview.append(f"{'✓' if valid else '×'}  [{kind.value}]  {value}")
        self.txt_path_label.setText(display_path(path))
        self.txt_summary.setText(f"{len(lines)} entradas • {valid_count} válidas • {len(lines) - valid_count} inválidas")
        self.txt_preview.setPlainText("\n".join(preview))

    def _enqueue_txt_items(self) -> None:
        if not self.txt_items:
            show_message(self, "Lista TXT", "Escolha e revise um arquivo TXT primeiro.", kind="info")
            return
        if not self._ensure_ffmpeg():
            return
        destination = self._destination_path()
        if destination is None:
            return
        accepted = 0
        for original, kind, normalized in self.txt_items:
            if kind == LinkType.DIRETO:
                self._queue_download(normalized, "Importado de TXT", destination=destination)
                accepted += 1
            elif kind in {LinkType.PLAYLIST, LinkType.PESQUISA_TEXTO, LinkType.PESQUISA_URL}:
                worker = ResolveRunnable(original)
                worker.signals.resolved.connect(self._enqueue_resolved)
                worker.signals.failed.connect(lambda msg: self._show_toast(f"Item ignorado: {msg}", kind="error"))
                self.resolve_pool.start(worker)
                accepted += 1
        if accepted:
            self._show_toast(f"{accepted} itens enviados para processamento.", kind="success")
            self._navigate(0)

    def _choose_destination(self) -> None:
        try:
            current = str(validate_download_path(self.destination.text()))
        except ValueError:
            current = str(Path.home() / "Downloads")
        path = QFileDialog.getExistingDirectory(self, "Pasta de destino", current)
        if path:
            self.destination.setText(display_path(path))

    def _save_defaults(self) -> None:
        destination = self._destination_path()
        if destination is None:
            return
        fmt = "mp3" if self.mp3.isChecked() else "mp4"
        quality = self._quality_value() or ("192" if fmt == "mp3" else "1080p")
        concurrent = self.concurrent_slider.value()
        self.config.update(download_path=str(destination), formato_padrao=fmt, qualidade_audio=quality if fmt == "mp3" else self.config.get("qualidade_audio", "192"), qualidade_video=quality if fmt == "mp4" else self.config.get("qualidade_video", "1080p"), max_downloads_simultaneos=concurrent)
        self.download_pool.setMaxThreadCount(concurrent)
        self._show_toast("Preferências salvas localmente.", kind="success")

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _refresh_history(self) -> None:
        if not hasattr(self, "history_layout") or self._closing:
            return
        self._clear_layout(self.history_layout)
        entries = self.history.list()
        counts = {status: sum(1 for item in entries if item.get("status") == status) for status in ("concluído", "erro", "cancelado")}
        self.history_summary.setText(f"{len(entries)} registros • {counts['concluído']} concluídos • {counts['erro']} erros • {counts['cancelado']} cancelados")
        self.clear_history_button.setEnabled(bool(entries))
        if not entries:
            self.history_stack.setCurrentIndex(0)
            return
        self.history_stack.setCurrentIndex(1)
        for entry in entries[:100]:
            card = QFrame()
            card.setObjectName("historyCard")
            row = QHBoxLayout(card)
            info = QVBoxLayout()
            raw_title = str(entry.get("title") or "Mídia")
            title = plain_label(raw_title)
            title.setStyleSheet("font-weight:750;")
            title.setToolTip(raw_title)
            info.addWidget(title)
            date_text = human_datetime(str(entry.get("finished_at") or ""))
            path_text = display_path(str(entry.get("destination") or "")) if entry.get("destination") else "pasta não registrada"
            meta = plain_label(f"{entry.get('format', '')} • {date_text} • {path_text}")
            meta.setObjectName("muted")
            meta.setWordWrap(True)
            info.addWidget(meta)
            message = str(entry.get("message") or "")
            if message:
                msg = plain_label(message)
                msg.setObjectName("muted")
                msg.setWordWrap(True)
                msg.setToolTip(message)
                info.addWidget(msg)
            row.addLayout(info, 1)
            status = plain_label(str(entry.get("status") or ""))
            status.setObjectName({"concluído": "statusDone", "erro": "statusError", "cancelado": "statusWaiting"}.get(str(entry.get("status")), "statusWaiting"))
            row.addWidget(status)
            destination = str(entry.get("destination") or "").strip()
            folder = QPushButton("Abrir pasta")
            folder.setEnabled(bool(destination))
            if destination:
                folder.clicked.connect(lambda _=False, p=destination: self._open_folder(Path(p), create=False))
            row.addWidget(folder)
            self.history_layout.insertWidget(self.history_layout.count() - 1, card)

    def _clear_history(self) -> None:
        if not self.history.list():
            return
        if ask_confirmation(self, "Limpar histórico", "Remover todos os registros locais do histórico? Os arquivos baixados não serão apagados.", confirm_text="Limpar histórico", cancel_text="Cancelar", destructive=True):
            self.history.clear()
            self._refresh_history()
            self._show_toast("Histórico local removido.", kind="success")

    def _open_folder(self, path: Path, *, create: bool = False) -> None:
        raw = str(path).strip()
        if not raw:
            show_message(self, "Abrir pasta", "Nenhuma pasta válida foi registrada.", kind="warning")
            return
        target = Path(raw).expanduser()
        try:
            if create:
                target.mkdir(parents=True, exist_ok=True)
            elif not target.is_dir():
                show_message(self, "Abrir pasta", f"A pasta não existe mais:\n{display_path(target)}", kind="warning")
                return
        except OSError as exc:
            show_message(self, "Abrir pasta", str(exc), kind="error")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve()))):
            show_message(self, "Abrir pasta", f"Não foi possível abrir:\n{display_path(target)}", kind="error")

    def _show_toast(self, message: str, *, kind: str = "info", timeout: int = 3500) -> None:
        if self._closing:
            return
        self._toast_generation += 1
        generation = self._toast_generation
        self._restyle(self.toast_label, {"success": "toastSuccess", "error": "toastError"}.get(kind, "toastInfo"))
        self.toast_label.setText(message)
        QTimer.singleShot(timeout, lambda g=generation: self._clear_toast(g))

    def _clear_toast(self, generation: int) -> None:
        if not self._closing and generation == self._toast_generation:
            self.toast_label.setText("")

    def closeEvent(self, event) -> None:  # noqa: N802
        has_background = bool(self.workers) or self.resolve_pool.activeThreadCount() > 0
        if has_background:
            should_close = ask_confirmation(self, "Tarefas em andamento", "Há downloads ou resolução de links em andamento. Deseja cancelar as tarefas e sair?", confirm_text="Cancelar e sair", cancel_text="Continuar no app", destructive=True)
            if not should_close:
                event.ignore()
                return
        self._closing = True
        self.clip_timer.stop()
        self.stats_timer.stop()
        for worker in list(self.workers.values()):
            worker.cancel()
        self.download_pool.clear()
        self.resolve_pool.clear()
        self.download_pool.waitForDone(1500)
        self.resolve_pool.waitForDone(1500)
        event.accept()


def iniciar_app() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    window = YouTubeDownloaderWindow()
    window.show()
    raise SystemExit(app.exec())
