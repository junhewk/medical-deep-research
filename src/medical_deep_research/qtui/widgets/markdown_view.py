from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import QTextBrowser, QTextEdit

from ..theme import (
    ACCENT,
    BORDER_DIM,
    SURFACE,
    SURFACE_SOFT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    report_font,
)


class MarkdownView(QTextBrowser):
    """QTextBrowser wrapper with throttled streaming markdown updates."""

    def __init__(self, parent=None, *, report_mode: bool = False) -> None:
        super().__init__(parent)
        self._report_mode = report_mode
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.setFont(report_font())
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(
            18 if report_mode else 12,
            18 if report_mode else 10,
            18 if report_mode else 12,
            18 if report_mode else 10,
        )
        self.document().setDocumentMargin(16 if report_mode else 10)
        if report_mode:
            self.setLineWrapMode(QTextEdit.LineWrapMode.FixedPixelWidth)
            self.setLineWrapColumnOrWidth(980)
        self.document().setDefaultStyleSheet(
            f"""
            body {{
                color: {TEXT_PRIMARY};
                background: {SURFACE};
                line-height: {"1.58" if report_mode else "1.45"};
            }}
            h1 {{
                font-size: {"26px" if report_mode else "24px"};
                margin: 0 0 {"18px" if report_mode else "14px"} 0;
                color: {TEXT_PRIMARY};
            }}
            h2 {{
                font-size: {"20px" if report_mode else "19px"};
                margin: {"28px" if report_mode else "22px"} 0
                    {"12px" if report_mode else "10px"} 0;
                color: {TEXT_PRIMARY};
            }}
            h3 {{
                font-size: {"17px" if report_mode else "16px"};
                margin: {"23px" if report_mode else "18px"} 0
                    {"10px" if report_mode else "8px"} 0;
                color: {TEXT_PRIMARY};
            }}
            p, li {{
                margin-top: {"8px" if report_mode else "6px"};
                margin-bottom: {"8px" if report_mode else "6px"};
            }}
            ul, ol {{
                margin-top: {"8px" if report_mode else "4px"};
                margin-bottom: {"14px" if report_mode else "6px"};
            }}
            strong {{
                font-weight: 700;
            }}
            blockquote {{
                color: {TEXT_MUTED};
                border-left: 3px solid {BORDER_DIM};
                margin-left: 0;
                padding-left: {"16px" if report_mode else "12px"};
                background: {SURFACE_SOFT if report_mode else SURFACE};
            }}
            a {{
                color: {ACCENT};
                text-decoration: none;
            }}
            code {{
                background: #eef4f1;
                border: 1px solid {BORDER_DIM};
                border-radius: 4px;
                padding: 2px 4px;
            }}
            """
        )
        self.anchorClicked.connect(self._on_anchor_clicked)
        self._buffer = ""
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(60)  # 60 ms cadence — smooth without re-parsing on every chunk
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush)

    def set_markdown(self, text: str) -> None:
        self._buffer = text
        self._flush_timer.stop()
        self._flush()

    def append_chunk(self, chunk: str) -> None:
        self._buffer += chunk
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def force_flush(self) -> None:
        self._flush_timer.stop()
        self._flush()

    def _flush(self) -> None:
        # Preserve scroll position at bottom only if user was already at the bottom
        scrollbar = self.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        self.setMarkdown(self._buffer)
        self._apply_report_spacing()
        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._report_mode:
            available = max(360, self.width() - 44)
            text_width = min(1020, available)
            side_margin = max(22, int((available - text_width) / 2) + 22)
            self.setViewportMargins(side_margin, 20, side_margin, 20)
            self.setLineWrapColumnOrWidth(text_width)

    def _apply_report_spacing(self) -> None:
        if not self._report_mode:
            return

        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        while True:
            block = cursor.block()
            block_format = block.blockFormat()
            text = block.text().strip()
            block_format.setLineHeight(
                158,
                QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
            )
            block_format.setTopMargin(4.0 if text else 0.0)
            block_format.setBottomMargin(8.0 if text else 6.0)
            cursor.setBlockFormat(block_format)
            if not cursor.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        cursor.endEditBlock()

    def _on_anchor_clicked(self, url: QUrl) -> None:
        if url.isValid() and url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
