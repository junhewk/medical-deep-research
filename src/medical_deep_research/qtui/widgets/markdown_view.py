from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTextBrowser


class MarkdownView(QTextBrowser):
    """QTextBrowser wrapper with throttled streaming markdown updates."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
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
