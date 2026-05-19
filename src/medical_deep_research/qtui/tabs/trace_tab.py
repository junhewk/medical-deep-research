from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..theme import adjusted_point_size


class TraceTab(QWidget):
    """Live execution-event timeline for the selected run."""

    def __init__(self, t: Callable[[str], str], parent=None) -> None:
        super().__init__(parent)
        self._t = t

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._title = QLabel(self._t("execution_trace"))
        f = self._title.font(); f.setBold(True); f.setPointSizeF(adjusted_point_size(f, 1)); self._title.setFont(f)
        layout.addWidget(self._title)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #6e7f91; font-size: 11px;")
        layout.addWidget(self._count_label)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setStyleSheet(
            "QListWidget { border: 1px solid #d6e1ea; border-radius: 4px; background: white; }"
            "QListWidget::item { border-bottom: 1px solid #eef2f6; padding: 6px 10px; }"
        )
        layout.addWidget(self._list, 1)

        self._empty = QLabel(self._t("waiting_events"))
        self._empty.setStyleSheet("color: #6e7f91; font-size: 12px; padding: 8px;")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)

    def set_events(self, events: list) -> None:
        self._count_label.setText(f"{len(events)} {self._t('events')}")
        self._list.clear()

        if not events:
            self._empty.setVisible(True)
            self._list.setVisible(False)
            return

        self._empty.setVisible(False)
        self._list.setVisible(True)

        # Show the last 200 events to keep redraws snappy
        for event in events[-200:]:
            meta_parts = [event.phase, event.event_type, f"{event.progress}%"]
            if event.tool_name:
                meta_parts.append(event.tool_name)
            if event.agent_name:
                meta_parts.append(event.agent_name)
            meta = " · ".join(meta_parts)
            text = f"{event.sequence:03d}   {event.message}\n        {meta}"
            item = QListWidgetItem(text)
            self._list.addItem(item)
        # Auto-scroll to bottom for live updates
        self._list.scrollToBottom()

    def retranslate(self) -> None:
        self._title.setText(self._t("execution_trace"))
        self._empty.setText(self._t("waiting_events"))
