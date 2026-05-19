from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTextBrowser

from ..theme import ACCENT, BORDER_DIM, SURFACE, TEXT_MUTED, TEXT_PRIMARY, report_font


class MarkdownView(QTextBrowser):
    """QTextBrowser wrapper with throttled streaming markdown updates."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.setFont(report_font())
        self.setViewportMargins(12, 10, 12, 10)
        self.document().setDocumentMargin(10)
        self.document().setDefaultStyleSheet(
            f"""
            body {{
                color: {TEXT_PRIMARY};
                background: {SURFACE};
                line-height: 1.45;
            }}
            h1 {{
                font-size: 24px;
                margin: 0 0 14px 0;
                color: {TEXT_PRIMARY};
            }}
            h2 {{
                font-size: 19px;
                margin: 22px 0 10px 0;
                color: {TEXT_PRIMARY};
            }}
            h3 {{
                font-size: 16px;
                margin: 18px 0 8px 0;
                color: {TEXT_PRIMARY};
            }}
            p, li {{
                margin-top: 6px;
                margin-bottom: 6px;
            }}
            blockquote {{
                color: {TEXT_MUTED};
                border-left: 3px solid {BORDER_DIM};
                margin-left: 0;
                padding-left: 12px;
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
        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def _on_anchor_clicked(self, url: QUrl) -> None:
        if url.isValid() and url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
