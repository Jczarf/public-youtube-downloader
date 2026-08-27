from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


C = {
    "window": "#05070a",
    "bg": "#090c12",
    "sidebar": "#0b0e14",
    "panel": "#10141c",
    "panel2": "#141a24",
    "input": "#0a0f16",
    "border": "#242d39",
    "border_soft": "#1b2430",
    "text": "#f2f5f8",
    "muted": "#8c98a8",
    "accent": "#ff5c63",
    "accent_hover": "#ff7379",
    "green": "#55d88b",
    "amber": "#f2c46d",
    "blue": "#68a7ff",
}


def choose_font_family() -> str:
    """Escolhe uma fonte previsível sem empacotar arquivos de fonte."""
    available = set(QFontDatabase.families())
    for family in ("Inter", "Noto Sans", "DejaVu Sans", "Liberation Sans"):
        if family in available:
            return family
    return "Sans Serif"


def display_path(value: str | Path) -> str:
    """Encurta caminhos do diretório pessoal para evitar ruído e exposição na UI."""
    path = Path(value).expanduser()
    try:
        relative = path.relative_to(Path.home())
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


def human_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%d/%m/%Y • %H:%M")
    except ValueError:
        return value


def make_nav_icon(kind: str, color: str, size: int = 18) -> QIcon:
    """Ícones vetoriais simples para não depender de glifos da fonte do sistema."""
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    pen = QPen(QColor(color), 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    if kind == "queue":
        painter.drawLine(QPointF(9, 3), QPointF(9, 12))
        painter.drawLine(QPointF(5.8, 9), QPointF(9, 12.2))
        painter.drawLine(QPointF(12.2, 9), QPointF(9, 12.2))
        painter.drawLine(QPointF(4, 15), QPointF(14, 15))
    elif kind == "history":
        painter.drawEllipse(QPointF(9, 9), 6, 6)
        painter.drawLine(QPointF(9, 9), QPointF(9, 5.5))
        painter.drawLine(QPointF(9, 9), QPointF(12, 10.5))
    elif kind == "list":
        for y in (5, 9, 13):
            painter.drawEllipse(QPointF(4, y), 0.8, 0.8)
            painter.drawLine(QPointF(7, y), QPointF(14, y))
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


class StyledComboBox(QComboBox):
    """QComboBox com chevron próprio para reduzir variação entre temas Linux."""

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(C["muted"]), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        x = self.width() - 18
        y = self.height() / 2 - 1
        painter.drawLine(QPointF(x - 4, y - 2), QPointF(x, y + 2))
        painter.drawLine(QPointF(x, y + 2), QPointF(x + 4, y - 2))
        painter.end()


class AppDialog(QDialog):
    """Diálogo próprio para impedir QMessageBox claro/ilegível em temas escuros."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        kind: str = "info",
        confirm_text: str = "Entendi",
        cancel_text: str | None = None,
        destructive: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(title)
        self.setMinimumWidth(470)
        self.setMaximumWidth(620)
        self.setObjectName("appDialog")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        card = QFrame()
        card.setObjectName("dialogCard")
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(14)
        mark = QLabel({"error": "!", "warning": "!", "question": "?"}.get(kind, "i"))
        mark.setObjectName(f"dialogMark_{kind}")
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(mark)

        copy = QVBoxLayout()
        copy.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        copy.addWidget(heading)
        body = QLabel(message)
        body.setObjectName("dialogText")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy.addWidget(body)
        top.addLayout(copy, 1)
        root.addLayout(top)

        actions = QHBoxLayout()
        actions.addStretch()
        if cancel_text:
            cancel = QPushButton(cancel_text)
            cancel.setObjectName("dialogSecondary")
            cancel.clicked.connect(self.reject)
            actions.addWidget(cancel)

        confirm = QPushButton(confirm_text)
        confirm.setObjectName("dialogDanger" if destructive else "dialogPrimary")
        confirm.setDefault(True)
        confirm.clicked.connect(self.accept)
        actions.addWidget(confirm)
        root.addLayout(actions)

        self.setStyleSheet(
            f"""
            QDialog#appDialog {{ background:{C['window']}; color:{C['text']}; }}
            QFrame#dialogCard {{
                background:{C['panel']}; border:1px solid {C['border']}; border-radius:16px;
            }}
            QLabel#dialogTitle {{ color:{C['text']}; font-size:16px; font-weight:800; }}
            QLabel#dialogText {{ color:{C['muted']}; font-size:12px; }}
            QLabel#dialogMark_info, QLabel#dialogMark_question {{
                color:{C['blue']}; background:#152033; border:1px solid #29456e;
                border-radius:19px; font-size:18px; font-weight:900;
            }}
            QLabel#dialogMark_warning {{
                color:{C['amber']}; background:#292312; border:1px solid #5a4a1f;
                border-radius:19px; font-size:18px; font-weight:900;
            }}
            QLabel#dialogMark_error {{
                color:{C['accent']}; background:#28151a; border:1px solid #5d2b34;
                border-radius:19px; font-size:18px; font-weight:900;
            }}
            QPushButton {{
                min-width:92px; background:#161e29; color:{C['text']};
                border:1px solid #2b3645; border-radius:10px; padding:9px 14px;
                font-weight:700;
            }}
            QPushButton:hover {{ background:#1a2431; border-color:#465569; }}
            QPushButton#dialogPrimary {{
                background:{C['accent']}; color:#16090b; border:none;
            }}
            QPushButton#dialogDanger {{
                background:#28151a; color:{C['accent']}; border:1px solid #5d2b34;
            }}
            """
        )


def ask_confirmation(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    confirm_text: str = "Confirmar",
    cancel_text: str = "Cancelar",
    destructive: bool = False,
) -> bool:
    dialog = AppDialog(
        parent,
        title,
        message,
        kind="question",
        confirm_text=confirm_text,
        cancel_text=cancel_text,
        destructive=destructive,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


def show_message(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    kind: str = "info",
) -> None:
    AppDialog(parent, title, message, kind=kind).exec()
