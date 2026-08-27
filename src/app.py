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
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .downloader import DownloadSpec, Downloader, Progress, validate_clip
from .history import HistoryStore
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
        except Exception as exc:
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
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class QueueCard(QFrame):
    cancel_requested = Signal()

    def __init__(self, label: str, formato: str, detail: str, spec: DownloadSpec) -> None:
        super().__init__()
        self.setObjectName("queueCard")
        self.setMinimumHeight(106)
        self.speed = 0.0
        self.spec = spec

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

    @property
    def display_title(self) -> str:
        return self.title_label.text().strip() or "Mídia"

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
    PAGE_META = {
        0: ("Downloader de mídia", "Links, pesquisa, filas e recortes em uma experiência única."),
        1: ("Histórico", "Downloads concluídos, cancelados e falhas registrados apenas no seu computador."),
        2: ("Listas TXT", "Revise uma lista antes de enviar vários itens para a fila."),
        3: ("Configurações", "Preferências locais, ferramentas e comportamento padrão da aplicação."),
    }

    def __init__(self) -> None:
        super().__init__()
        self.config = Config()
        self.history = HistoryStore(self.config.config_file.parent / "history.json")
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(int(self.config.get("max_downloads_simultaneos", 3)))
        self.cards: list[QueueCard] = []
        self.workers: dict[QueueCard, DownloadRunnable] = {}
        self.seen_clipboard: set[str] = set()
        self.last_clipboard = ""
        self.completed_count = 0
        self.txt_items: list[tuple[str, LinkType, str]] = []

        self.setWindowTitle("YouTube Downloader")
        self.resize(1600, 960)
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

        if bool(self.config.get("clipboard_monitor", False)):
            self.clip_button.setChecked(True)

    def _theme(self) -> None:
        self.setFont(QFont("Inter", 10))
        self.setStyleSheet(f"""
            QMainWindow, QWidget#root, QWidget#mainShell, QStackedWidget#pages {{
                background:{C['bg']}; color:{C['text']};
            }}
            QFrame#sidebar {{
                background:{C['sidebar']}; border-right:1px solid {C['border']};
            }}
            QFrame#panel, QFrame#queueCard, QFrame#historyCard {{
                background:{C['panel']}; border:1px solid {C['border']}; border-radius:14px;
            }}
            QFrame#queueCard {{ background:{C['panel2']}; }}
            QFrame#emptyState {{
                background:#0b1017; border:1px dashed #2a3442; border-radius:14px;
            }}
            QLabel {{ color:{C['text']}; background:transparent; }}
            QLabel#muted {{ color:{C['muted']}; font-size:12px; }}
            QLabel#queueTitle {{ font-size:15px; font-weight:700; }}
            QLabel#emptyTitle {{ color:{C['text']}; font-size:18px; font-weight:800; }}
            QLabel#emptyHint {{ color:{C['muted']}; font-size:12px; }}
            QLabel#mediaIcon {{
                background:#24151a; color:{C['accent']}; border-radius:10px;
                font-size:18px; font-weight:800;
            }}
            QLabel#statusWaiting {{
                color:{C['amber']}; background:#292312; border-radius:10px;
                padding:5px 10px; font-weight:700;
            }}
            QLabel#statusActive {{
                color:{C['blue']}; background:#152033; border-radius:10px;
                padding:5px 10px; font-weight:700;
            }}
            QLabel#statusDone {{
                color:{C['green']}; background:#102319; border-radius:10px;
                padding:5px 10px; font-weight:700;
            }}
            QLabel#statusError {{
                color:{C['accent']}; background:#28151a; border-radius:10px;
                padding:5px 10px; font-weight:700;
            }}
            QLabel#queueBadge {{
                color:{C['green']}; background:#102319; border-radius:10px;
                padding:5px 9px; font-weight:750;
            }}
            QPushButton {{
                background:#161e29; color:{C['text']}; border:1px solid #2b3645;
                border-radius:10px; padding:10px 14px; font-weight:650;
            }}
            QPushButton:hover {{ border-color:#465569; }}
            QPushButton#primary {{
                background:{C['accent']}; color:#16090b; border:none; font-weight:800;
            }}
            QPushButton#primary:hover {{ background:{C['accent_hover']}; }}
            QPushButton#danger {{
                background:#28151a; color:{C['accent']}; border:1px solid #5d2b34;
            }}
            QPushButton#nav {{
                background:transparent; border:none; color:{C['muted']};
                text-align:left; padding:12px 14px;
            }}
            QPushButton#nav:checked {{
                background:#29171c; color:{C['text']}; border:1px solid #51262d;
            }}
            QPushButton#iconButton {{
                padding:0; background:transparent; color:{C['muted']};
                border:none; font-size:21px;
            }}
            QPushButton#formatButton {{ background:#151d28; }}
            QPushButton#formatButton:checked {{
                background:#2b1920; color:{C['text']}; border:1px solid #5d2b34;
            }}
            QPushButton#clipToggle:checked {{
                background:#102319; color:{C['green']}; border:1px solid #24573a;
            }}
            QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
                background:#0a0f16; color:{C['text']}; border:1px solid #2a3442;
                border-radius:11px; padding:10px 12px; min-height:20px;
                selection-background-color:{C['accent']};
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
                border-color:{C['accent']};
            }}
            QComboBox::drop-down {{ border:none; width:28px; }}
            QComboBox QAbstractItemView {{
                background:#10141c; color:{C['text']}; border:1px solid #2a3442;
                selection-background-color:#2b1920;
            }}
            QCheckBox {{ color:{C['text']}; spacing:8px; }}
            QSlider::groove:horizontal {{
                background:#0a0f16; height:7px; border-radius:3px;
            }}
            QSlider::sub-page:horizontal {{
                background:{C['accent']}; border-radius:3px;
            }}
            QSlider::handle:horizontal {{
                background:{C['text']}; width:16px; margin:-5px 0; border-radius:8px;
            }}
            QProgressBar {{
                background:#080c12; border:none; border-radius:4px;
                min-height:8px; max-height:8px;
            }}
            QProgressBar::chunk {{ background:{C['accent']}; border-radius:4px; }}
            QScrollArea {{ background:transparent; border:none; }}
            QScrollArea#queueScroll {{ background:transparent; border:none; }}
            QWidget#queueViewport, QWidget#queueBody, QWidget#historyBody {{
                background:{C['panel']};
            }}
            QScrollBar:vertical {{ background:transparent; width:8px; }}
            QScrollBar::handle:vertical {{
                background:#2a3543; border-radius:4px; min-height:30px;
            }}
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
        sidebar.setFixedWidth(255)
        shell.addWidget(sidebar)
        self._build_sidebar(sidebar)

        main = QWidget()
        main.setObjectName("mainShell")
        body = QVBoxLayout(main)
        body.setContentsMargins(28, 22, 28, 22)
        body.setSpacing(18)
        shell.addWidget(main, 1)

        header = QHBoxLayout()
        htext = QVBoxLayout()
        self.page_title = QLabel()
        self.page_title.setStyleSheet("font-size:28px;font-weight:800;")
        self.page_subtitle = QLabel()
        self.page_subtitle.setObjectName("muted")
        htext.addWidget(self.page_title)
        htext.addWidget(self.page_subtitle)
        header.addLayout(htext)
        header.addStretch()

        ffmpeg_ok = bool(shutil.which("ffmpeg"))
        self.ffmpeg_badge = QLabel("FFmpeg ✓" if ffmpeg_ok else "FFmpeg ausente")
        self.ffmpeg_badge.setStyleSheet(
            f"color:{C['green'] if ffmpeg_ok else C['amber']};font-weight:700;"
        )
        header.addWidget(self.ffmpeg_badge)

        self.ytdlp_badge = QLabel(f"yt-dlp {yt_dlp.version.__version__}")
        self.ytdlp_badge.setStyleSheet(f"color:{C['blue']};font-weight:700;")
        header.addWidget(self.ytdlp_badge)
        body.addLayout(header)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        self.pages.addWidget(self._build_queue_page())
        self.pages.addWidget(self._build_history_page())
        self.pages.addWidget(self._build_txt_page())
        self.pages.addWidget(self._build_settings_page())
        body.addWidget(self.pages, 1)

        self._navigate(0)

    def _build_sidebar(self, sidebar: QFrame) -> None:
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(18, 24, 18, 20)

        brand = QLabel("▶  YouTube Downloader")
        brand.setStyleSheet(f"font-size:17px;font-weight:850;color:{C['text']};")
        lay.addWidget(brand)

        sub = QLabel("DOWNLOADER DE MÍDIA")
        sub.setStyleSheet(f"color:{C['muted']};font-size:10px;font-weight:700;")
        lay.addWidget(sub)
        lay.addSpacing(26)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        labels = ("⇩   Fila", "◷   Histórico", "≡   Listas TXT", "⚙   Configurações")
        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(labels):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            lay.addWidget(button)

        self.nav_group.idClicked.connect(self._navigate)
        self.nav_buttons[0].setChecked(True)

        lay.addStretch()
        privacy = self._panel()
        pv = QVBoxLayout(privacy)
        pv.addWidget(self._small_label("PRIVACIDADE"))
        self.privacy_label = QLabel("Clipboard desligado")
        self.privacy_label.setStyleSheet(f"color:{C['green']};font-weight:750;")
        pv.addWidget(self.privacy_label)
        note = QLabel("Nenhum link é lido até você ativar o monitor.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        pv.addWidget(note)
        lay.addWidget(privacy)

        local = QLabel("Uso pessoal • local")
        local.setObjectName("muted")
        lay.addWidget(local)

    def _build_queue_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        add_row = QHBoxLayout()
        add_panel = self._panel()
        add_layout = QVBoxLayout(add_panel)
        add_layout.setContentsMargins(20, 16, 20, 16)
        add_layout.addWidget(
            self._heading("Adicionar conteúdo", "Cole um link, uma pesquisa ou importe uma lista TXT.")
        )

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Link do YouTube ou nome da música...")
        self.input.returnPressed.connect(self._resolve_input)
        input_row.addWidget(self.input, 1)

        txt = QPushButton("TXT")
        txt.clicked.connect(lambda: self._navigate(2))
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
        clip_layout.addWidget(
            self._heading("Monitor de clipboard", "Só lê links após ativação explícita.")
        )
        self.clip_button = QPushButton("●  Desligado — Ativar")
        self.clip_button.setObjectName("clipToggle")
        self.clip_button.setCheckable(True)
        self.clip_button.toggled.connect(self._toggle_clipboard)
        clip_layout.addWidget(self.clip_button)
        add_row.addWidget(clip_panel)
        layout.addLayout(add_row)

        content = QHBoxLayout()

        queue_panel = self._panel()
        qlayout = QVBoxLayout(queue_panel)
        qlayout.setContentsMargins(20, 18, 20, 18)

        qhead = QHBoxLayout()
        qtitle = QLabel("Fila de downloads")
        qtitle.setStyleSheet("font-size:20px;font-weight:800;")
        qhead.addWidget(qtitle)

        self.queue_badge = QLabel("0 ativos • 0 concluídos")
        self.queue_badge.setObjectName("queueBadge")
        qhead.addWidget(self.queue_badge)
        qhead.addStretch()

        self.speed_label = QLabel("Velocidade total: 0.0 B/s")
        self.speed_label.setObjectName("muted")
        qhead.addWidget(self.speed_label)
        qlayout.addLayout(qhead)

        scroll = QScrollArea()
        scroll.setObjectName("queueScroll")
        scroll.setWidgetResizable(True)
        scroll.viewport().setObjectName("queueViewport")

        scroll_body = QWidget()
        scroll_body.setObjectName("queueBody")
        self.queue_layout = QVBoxLayout(scroll_body)
        self.queue_layout.setContentsMargins(0, 10, 4, 0)
        self.queue_layout.setSpacing(10)

        self.empty_state = QFrame()
        self.empty_state.setObjectName("emptyState")
        self.empty_state.setMinimumHeight(310)
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(28, 28, 28, 28)
        empty_layout.addStretch()

        empty_icon = QLabel("⇩")
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setStyleSheet(f"color:{C['accent']};font-size:34px;font-weight:800;")
        empty_title = QLabel("Sua fila está vazia")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = QLabel("Cole um link, pesquise uma mídia ou importe uma lista TXT para começar.")
        empty_hint.setObjectName("emptyHint")
        empty_hint.setWordWrap(True)
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_layout.addWidget(empty_icon)
        empty_layout.addSpacing(8)
        empty_layout.addWidget(empty_title)
        empty_layout.addSpacing(4)
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch()

        self.queue_layout.addWidget(self.empty_state)
        self.queue_layout.addStretch()
        scroll.setWidget(scroll_body)
        qlayout.addWidget(scroll, 1)
        content.addWidget(queue_panel, 1)

        settings = self._panel()
        settings.setFixedWidth(360)
        sl = QVBoxLayout(settings)
        sl.setContentsMargins(20, 18, 20, 18)

        s_title = QLabel("Configuração rápida")
        s_title.setStyleSheet("font-size:20px;font-weight:800;")
        sl.addWidget(s_title)
        sl.addWidget(self._small_label("Formato"))

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

        sl.addWidget(self._small_label("Qualidade"))
        self.quality = QComboBox()
        self._populate_quality_combo()
        sl.addWidget(self.quality)

        sl.addWidget(self._small_label("Recorte"))
        cut = QHBoxLayout()
        self.start_time = QLineEdit()
        self.start_time.setPlaceholderText("De  00:03")
        self.end_time = QLineEdit()
        self.end_time.setPlaceholderText("Até  02:30")
        cut.addWidget(self.start_time)
        cut.addWidget(self.end_time)
        sl.addLayout(cut)

        sl.addWidget(self._small_label("Pasta de destino"))
        self.destination = QLineEdit(str(self.config.get("download_path")))
        sl.addWidget(self.destination)
        choose = QPushButton("Escolher pasta")
        choose.clicked.connect(self._choose_destination)
        sl.addWidget(choose)

        sl.addWidget(self._small_label("Concorrência"))
        concurrency_row = QHBoxLayout()
        self.concurrent_slider = QSlider(Qt.Orientation.Horizontal)
        self.concurrent_slider.setRange(1, 8)
        self.concurrent_slider.setValue(self.pool.maxThreadCount())
        self.concurrent_value = QLabel(str(self.pool.maxThreadCount()))
        self.concurrent_value.setMinimumWidth(24)
        self.concurrent_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.concurrent_slider.valueChanged.connect(
            lambda value: self.concurrent_value.setText(str(value))
        )
        concurrency_row.addWidget(self.concurrent_slider, 1)
        concurrency_row.addWidget(self.concurrent_value)
        sl.addLayout(concurrency_row)

        save = QPushButton("Salvar como padrão")
        save.clicked.connect(self._save_defaults)
        sl.addWidget(save)
        sl.addStretch()

        legal = QLabel(
            "Uso pessoal. Baixe somente conteúdo que você tem direito de acessar "
            "e respeite os termos da plataforma."
        )
        legal.setWordWrap(True)
        legal.setObjectName("muted")
        sl.addWidget(legal)
        content.addWidget(settings)

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
        title = QLabel("Atividade recente")
        title.setStyleSheet("font-size:20px;font-weight:800;")
        toolbar.addWidget(title)
        toolbar.addStretch()

        open_folder = QPushButton("Abrir pasta padrão")
        open_folder.clicked.connect(lambda: self._open_folder(Path(self.config.get("download_path"))))
        toolbar.addWidget(open_folder)

        clear = QPushButton("Limpar histórico")
        clear.setObjectName("danger")
        clear.clicked.connect(self._clear_history)
        toolbar.addWidget(clear)
        root.addLayout(toolbar)

        note = QLabel(
            "O histórico é armazenado localmente em JSON. Ele não contém arquivos de mídia nem é enviado ao GitHub."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)

        self.history_summary = QLabel()
        self.history_summary.setObjectName("muted")
        root.addWidget(self.history_summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_body = QWidget()
        scroll_body.setObjectName("historyBody")
        self.history_layout = QVBoxLayout(scroll_body)
        self.history_layout.setContentsMargins(0, 4, 4, 0)
        self.history_layout.setSpacing(10)
        self.history_layout.addStretch()
        scroll.setWidget(scroll_body)
        root.addWidget(scroll, 1)

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
        title = QLabel("Importar lista TXT")
        title.setStyleSheet("font-size:20px;font-weight:800;")
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

        self.txt_path_label = QLabel("Nenhum arquivo selecionado")
        self.txt_path_label.setObjectName("muted")
        root.addWidget(self.txt_path_label)

        self.txt_summary = QLabel("0 entradas analisadas")
        self.txt_summary.setObjectName("queueBadge")
        root.addWidget(self.txt_summary, alignment=Qt.AlignmentFlag.AlignLeft)

        self.txt_preview = QPlainTextEdit()
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setPlaceholderText(
            "Cada linha pode conter um link do YouTube, playlist, URL de pesquisa ou texto para pesquisa."
        )
        root.addWidget(self.txt_preview, 1)

        hint = QLabel(
            "A prévia não inicia downloads. Revise os itens e só então use “Adicionar válidos à fila”. "
            "No máximo 500 entradas são processadas por arquivo para manter a interface responsiva."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        layout.addWidget(panel, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        prefs = self._panel()
        pl = QVBoxLayout(prefs)
        pl.setContentsMargins(22, 20, 22, 20)
        pl.setSpacing(10)

        title = QLabel("Preferências")
        title.setStyleSheet("font-size:20px;font-weight:800;")
        pl.addWidget(title)

        pl.addWidget(self._small_label("Pasta padrão"))
        self.settings_destination = QLineEdit(str(self.config.get("download_path")))
        pl.addWidget(self.settings_destination)
        pick = QPushButton("Escolher pasta")
        pick.clicked.connect(self._choose_settings_destination)
        pl.addWidget(pick)

        pl.addWidget(self._small_label("Formato padrão"))
        self.settings_format = QComboBox()
        self.settings_format.addItems(["MP3", "MP4"])
        self.settings_format.setCurrentText(str(self.config.get("formato_padrao", "mp3")).upper())
        pl.addWidget(self.settings_format)

        pl.addWidget(self._small_label("Qualidade de áudio"))
        self.settings_audio = QComboBox()
        self.settings_audio.addItems(["128", "192", "256", "320"])
        self.settings_audio.setCurrentText(str(self.config.get("qualidade_audio", "192")))
        pl.addWidget(self.settings_audio)

        pl.addWidget(self._small_label("Qualidade de vídeo"))
        self.settings_video = QComboBox()
        self.settings_video.addItems(["480p", "720p", "1080p"])
        self.settings_video.setCurrentText(str(self.config.get("qualidade_video", "1080p")))
        pl.addWidget(self.settings_video)

        pl.addWidget(self._small_label("Downloads simultâneos"))
        self.settings_concurrency = QSpinBox()
        self.settings_concurrency.setRange(1, 8)
        self.settings_concurrency.setValue(int(self.config.get("max_downloads_simultaneos", 3)))
        pl.addWidget(self.settings_concurrency)

        self.settings_clipboard = QCheckBox("Ativar monitor de clipboard ao iniciar")
        self.settings_clipboard.setChecked(bool(self.config.get("clipboard_monitor", False)))
        pl.addWidget(self.settings_clipboard)

        save = QPushButton("Salvar preferências")
        save.setObjectName("primary")
        save.clicked.connect(self._save_settings_page)
        pl.addWidget(save)
        pl.addStretch()
        layout.addWidget(prefs, 1)

        system = self._panel()
        sl = QVBoxLayout(system)
        sl.setContentsMargins(22, 20, 22, 20)
        sl.setSpacing(12)

        stitle = QLabel("Ambiente")
        stitle.setStyleSheet("font-size:20px;font-weight:800;")
        sl.addWidget(stitle)

        self.env_ffmpeg = self._env_row("FFmpeg", "Disponível" if shutil.which("ffmpeg") else "Não encontrado")
        self.env_ytdlp = self._env_row("yt-dlp", yt_dlp.version.__version__)
        self.env_python = self._env_row("Python", sys.version.split()[0])
        self.env_config = self._env_row("Configuração", str(self.config.config_file))
        self.env_history = self._env_row("Histórico", str(self.history.path))
        for row in (self.env_ffmpeg, self.env_ytdlp, self.env_python, self.env_config, self.env_history):
            sl.addWidget(row)

        open_config = QPushButton("Abrir pasta de configuração")
        open_config.clicked.connect(lambda: self._open_folder(self.config.config_file.parent))
        sl.addWidget(open_config)

        privacy = QLabel(
            "Preferências e histórico ficam em diretório XDG local. O monitor de clipboard é opcional "
            "e pode ser desativado a qualquer momento."
        )
        privacy.setWordWrap(True)
        privacy.setObjectName("muted")
        sl.addWidget(privacy)
        sl.addStretch()
        layout.addWidget(system, 1)

        return page

    def _env_row(self, name: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("historyCard")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 10, 14, 10)
        label = QLabel(name)
        label.setStyleSheet("font-weight:700;")
        row.addWidget(label)
        row.addStretch()
        val = QLabel(value)
        val.setObjectName("muted")
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(val)
        return frame

    def _heading(self, title: str, subtitle: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(2)
        a = QLabel(title)
        a.setStyleSheet("font-size:16px;font-weight:750;")
        b = QLabel(subtitle)
        b.setObjectName("muted")
        layout.addWidget(a)
        layout.addWidget(b)
        return box

    def _small_label(self, value: str) -> QLabel:
        label = QLabel(value)
        label.setStyleSheet(
            f"color:{C['muted']};font-size:11px;font-weight:750;margin-top:8px;"
        )
        return label

    @Slot(int)
    def _navigate(self, index: int) -> None:
        if not 0 <= index < self.pages.count():
            return
        self.pages.setCurrentIndex(index)
        if hasattr(self, "nav_buttons"):
            self.nav_buttons[index].setChecked(True)
        title, subtitle = self.PAGE_META[index]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        if index == 1:
            self._refresh_history()
        elif index == 3:
            self._sync_settings_page()

    def _populate_quality_combo(self) -> None:
        fmt = "mp3" if self.mp3.isChecked() else "mp4"
        current = (
            str(self.config.get("qualidade_audio", "192"))
            if fmt == "mp3"
            else str(self.config.get("qualidade_video", "1080p"))
        )
        self.quality.blockSignals(True)
        self.quality.clear()
        self.quality.addItems(["128", "192", "256", "320"] if fmt == "mp3" else ["480p", "720p", "1080p"])
        self.quality.setCurrentText(current)
        self.quality.blockSignals(False)

    def _set_format(self, fmt: str) -> None:
        self.mp3.setChecked(fmt == "mp3")
        self.mp4.setChecked(fmt == "mp4")
        self._populate_quality_combo()

    def _resolve_input(self) -> None:
        value = self.input.text().strip()
        if not value:
            return
        self.input.setEnabled(False)
        worker = ResolveRunnable(value)
        worker.signals.resolved.connect(self._resolved_from_input)
        worker.signals.failed.connect(self._resolution_failed)
        self.pool.start(worker)

    @Slot(object)
    def _resolved_from_input(self, result: object) -> None:
        self.input.setEnabled(True)
        self.input.clear()
        self._enqueue_resolved(result)

    @Slot(object)
    def _enqueue_resolved(self, result: object) -> None:
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
        quality = self.quality.currentText().strip() or ("192" if fmt == "mp3" else "1080p")
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

        card = QueueCard(label, fmt, detail, spec)
        self.cards.append(card)
        self.empty_state.setVisible(False)
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

    def _record_history(self, card: QueueCard, status: str, message: str = "") -> None:
        self.history.add(
            {
                "title": card.display_title,
                "url": card.spec.url,
                "status": status,
                "format": card.spec.formato.upper(),
                "destination": str(card.spec.destino),
                "message": message[:240],
                "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        )
        self._refresh_history()

    def _completed(self, card: QueueCard) -> None:
        card.mark_completed()
        self.completed_count += 1
        self.workers.pop(card, None)
        self._record_history(card, "concluído")

    def _cancelled(self, card: QueueCard) -> None:
        card.mark_cancelled()
        self.workers.pop(card, None)
        self._record_history(card, "cancelado")

    def _failed(self, card: QueueCard, message: str) -> None:
        card.mark_failed(message)
        self.workers.pop(card, None)
        self._record_history(card, "erro", message)

    def _refresh_stats(self) -> None:
        active = len(self.workers)
        total_speed = sum(card.speed for card in self.cards)
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

    def _select_txt_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar lista", "", "Arquivos de texto (*.txt)")
        if not path:
            return
        try:
            lines = [
                line.strip()
                for line in Path(path).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ][:500]
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self, "Erro ao ler arquivo", str(exc))
            return

        self.txt_items.clear()
        preview: list[str] = []
        valid_count = 0
        for value in lines:
            kind, normalized = classificar_link(value)
            valid = kind in {
                LinkType.DIRETO,
                LinkType.PLAYLIST,
                LinkType.PESQUISA_TEXTO,
                LinkType.PESQUISA_URL,
            }
            if valid:
                valid_count += 1
            self.txt_items.append((value, kind, normalized))
            icon = "✓" if valid else "×"
            preview.append(f"{icon}  [{kind.value}]  {value}")

        self.txt_path_label.setText(path)
        invalid_count = len(lines) - valid_count
        self.txt_summary.setText(
            f"{len(lines)} entradas • {valid_count} válidas • {invalid_count} inválidas"
        )
        self.txt_preview.setPlainText("\n".join(preview))

    def _enqueue_txt_items(self) -> None:
        if not self.txt_items:
            QMessageBox.information(self, "Lista TXT", "Escolha e revise um arquivo TXT primeiro.")
            return

        accepted = 0
        for original, kind, normalized in self.txt_items:
            if kind == LinkType.DIRETO:
                self._queue_download(normalized, "Importado de TXT")
                accepted += 1
            elif kind in {LinkType.PLAYLIST, LinkType.PESQUISA_TEXTO, LinkType.PESQUISA_URL}:
                worker = ResolveRunnable(original)
                worker.signals.resolved.connect(self._enqueue_resolved)
                worker.signals.failed.connect(
                    lambda msg: self.statusBar().showMessage(f"Item ignorado: {msg}", 4000)
                )
                self.pool.start(worker)
                accepted += 1

        if accepted:
            self.statusBar().showMessage(f"{accepted} itens enviados para processamento.", 4000)
            self._navigate(0)

    def _choose_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pasta de destino", self.destination.text())
        if path:
            self.destination.setText(path)

    def _save_defaults(self) -> None:
        fmt = "mp3" if self.mp3.isChecked() else "mp4"
        quality = self.quality.currentText().strip() or ("192" if fmt == "mp3" else "1080p")
        concurrent = self.concurrent_slider.value()

        self.config.update(
            download_path=str(Path(self.destination.text()).expanduser()),
            formato_padrao=fmt,
            qualidade_audio=quality if fmt == "mp3" else self.config.get("qualidade_audio", "192"),
            qualidade_video=quality if fmt == "mp4" else self.config.get("qualidade_video", "1080p"),
            max_downloads_simultaneos=concurrent,
        )
        self.pool.setMaxThreadCount(concurrent)
        self._sync_settings_page()
        QMessageBox.information(self, "Preferências", "Configurações salvas localmente.")

    def _choose_settings_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Pasta de destino", self.settings_destination.text()
        )
        if path:
            self.settings_destination.setText(path)

    def _save_settings_page(self) -> None:
        fmt = self.settings_format.currentText().lower()
        concurrent = int(self.settings_concurrency.value())
        self.config.update(
            download_path=str(Path(self.settings_destination.text()).expanduser()),
            formato_padrao=fmt,
            qualidade_audio=self.settings_audio.currentText(),
            qualidade_video=self.settings_video.currentText(),
            max_downloads_simultaneos=concurrent,
            clipboard_monitor=self.settings_clipboard.isChecked(),
        )
        self.pool.setMaxThreadCount(concurrent)

        self.destination.setText(str(self.config.get("download_path")))
        self.concurrent_slider.setValue(concurrent)
        self._set_format(fmt)
        self.clip_button.setChecked(bool(self.config.get("clipboard_monitor", False)))
        QMessageBox.information(self, "Preferências", "Configurações salvas localmente.")

    def _sync_settings_page(self) -> None:
        if not hasattr(self, "settings_destination"):
            return
        self.settings_destination.setText(str(self.config.get("download_path")))
        self.settings_format.setCurrentText(str(self.config.get("formato_padrao", "mp3")).upper())
        self.settings_audio.setCurrentText(str(self.config.get("qualidade_audio", "192")))
        self.settings_video.setCurrentText(str(self.config.get("qualidade_video", "1080p")))
        self.settings_concurrency.setValue(int(self.config.get("max_downloads_simultaneos", 3)))
        self.settings_clipboard.setChecked(bool(self.config.get("clipboard_monitor", False)))

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _refresh_history(self) -> None:
        if not hasattr(self, "history_layout"):
            return

        self._clear_layout(self.history_layout)
        entries = self.history.list()
        counts = {
            "concluído": sum(1 for item in entries if item.get("status") == "concluído"),
            "erro": sum(1 for item in entries if item.get("status") == "erro"),
            "cancelado": sum(1 for item in entries if item.get("status") == "cancelado"),
        }
        self.history_summary.setText(
            f"{len(entries)} registros • {counts['concluído']} concluídos • "
            f"{counts['erro']} erros • {counts['cancelado']} cancelados"
        )

        if not entries:
            empty = QFrame()
            empty.setObjectName("emptyState")
            box = QVBoxLayout(empty)
            box.setContentsMargins(24, 48, 24, 48)
            label = QLabel("Nenhum download finalizado ainda.")
            label.setObjectName("emptyTitle")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint = QLabel("Quando um item terminar, falhar ou for cancelado, ele aparecerá aqui.")
            hint.setObjectName("emptyHint")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(label)
            box.addWidget(hint)
            self.history_layout.insertWidget(0, empty)
            return

        for entry in entries[:100]:
            card = QFrame()
            card.setObjectName("historyCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 12, 16, 12)

            info = QVBoxLayout()
            title = QLabel(str(entry.get("title") or "Mídia"))
            title.setStyleSheet("font-weight:750;")
            info.addWidget(title)

            meta = QLabel(
                f"{entry.get('format', '')} • {entry.get('finished_at', '')} • "
                f"{entry.get('destination', '')}"
            )
            meta.setObjectName("muted")
            meta.setWordWrap(True)
            info.addWidget(meta)

            message = str(entry.get("message") or "")
            if message:
                msg = QLabel(message)
                msg.setObjectName("muted")
                msg.setWordWrap(True)
                info.addWidget(msg)
            row.addLayout(info, 1)

            status = QLabel(str(entry.get("status") or ""))
            status_name = {
                "concluído": "statusDone",
                "erro": "statusError",
                "cancelado": "statusWaiting",
            }.get(str(entry.get("status")), "statusWaiting")
            status.setObjectName(status_name)
            row.addWidget(status)

            folder = QPushButton("Abrir pasta")
            folder.clicked.connect(
                lambda _=False, p=str(entry.get("destination") or ""): self._open_folder(Path(p))
            )
            row.addWidget(folder)
            self.history_layout.insertWidget(self.history_layout.count() - 1, card)

    def _clear_history(self) -> None:
        if not self.history.list():
            return
        answer = QMessageBox.question(
            self,
            "Limpar histórico",
            "Remover todos os registros locais do histórico? Os arquivos baixados não serão apagados.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self._refresh_history()

    def _open_folder(self, path: Path) -> None:
        target = Path(path).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve()))):
            QMessageBox.warning(self, "Abrir pasta", f"Não foi possível abrir:\n{target}")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.workers:
            answer = QMessageBox.question(
                self,
                "Downloads em andamento",
                "Há downloads em andamento. Deseja cancelar e sair?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for worker in list(self.workers.values()):
                worker.cancel()
        event.accept()


def iniciar_app() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = YouTubeDownloaderWindow()
    window.show()
    raise SystemExit(app.exec())
