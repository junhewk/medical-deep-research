from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from .theme import ACCENT, ACCENT_SOFT, BORDER_DIM, TEXT_MUTED, adjusted_point_size
from .widgets.badge import BadgePill, status_badge_kind


_QUERY_ROLE = Qt.ItemDataRole.UserRole + 1
_META_ROLE = Qt.ItemDataRole.UserRole + 2
_STATUS_ROLE = Qt.ItemDataRole.UserRole + 3
_RUN_ID_ROLE = Qt.ItemDataRole.UserRole + 4


class _RunRowDelegate(QStyledItemDelegate):
    """Two-line list rows: bold query (truncated) on top, provider/model + status badge below."""

    BADGE_KIND_COLORS = {
        "active":  (QColor(ACCENT_SOFT), QColor(ACCENT), QColor("#b7dad5")),
        "success": (QColor("#e7f6ef"), QColor("#0f684c"), QColor("#bfe5d2")),
        "warn":    (QColor("#fff4de"), QColor("#8a4d08"), QColor("#f5d39a")),
        "error":   (QColor("#fff0ef"), QColor("#9f2018"), QColor("#f4c7c3")),
        "neutral": (QColor("#f2f4f7"), QColor("#344054"), QColor(BORDER_DIM)),
    }

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), 54)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        rect = option.rect
        selected = bool(option.state & QStyleOptionViewItem.StateFlag.State_Selected)
        if selected:
            painter.fillRect(rect, QColor(ACCENT_SOFT))
        elif option.state & QStyleOptionViewItem.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor("#f0f6f4"))

        query: str = index.data(_QUERY_ROLE) or ""
        meta: str = index.data(_META_ROLE) or ""
        status: str = index.data(_STATUS_ROLE) or ""

        padding_x = 10
        text_left = rect.left() + padding_x
        # Estimate badge size
        badge_kind = status_badge_kind(status)
        badge_text = status
        font = option.font
        metrics = painter.fontMetrics()
        badge_w = metrics.horizontalAdvance(badge_text) + 14
        badge_h = 18
        badge_right = rect.right() - padding_x
        badge_left = badge_right - badge_w
        text_right = badge_left - 10

        # Draw query (line 1)
        title_font = QFont(font)
        title_font.setBold(False)
        title_font.setPointSizeF(adjusted_point_size(font, 0.5))
        painter.setFont(title_font)
        painter.setPen(QPen(QColor("#132033")))
        title_metrics = painter.fontMetrics()
        elided_query = title_metrics.elidedText(query, Qt.TextElideMode.ElideRight, max(40, text_right - text_left))
        painter.drawText(text_left, rect.top() + 6 + title_metrics.ascent(), elided_query)

        # Draw meta (line 2, mono-ish, muted)
        meta_font = QFont(font)
        meta_font.setPointSizeF(max(8.0, adjusted_point_size(font, -1.5)))
        painter.setFont(meta_font)
        painter.setPen(QPen(QColor(TEXT_MUTED)))
        meta_metrics = painter.fontMetrics()
        elided_meta = meta_metrics.elidedText(meta, Qt.TextElideMode.ElideRight, max(40, text_right - text_left))
        painter.drawText(text_left, rect.bottom() - 8, elided_meta)

        # Draw status badge (right-aligned, vertically centered)
        bg, fg, border = self.BADGE_KIND_COLORS.get(badge_kind, self.BADGE_KIND_COLORS["neutral"])
        badge_y = rect.top() + (rect.height() - badge_h) // 2
        painter.setPen(QPen(border))
        painter.setBrush(bg)
        painter.drawRoundedRect(badge_left, badge_y, badge_w, badge_h, 9, 9)
        painter.setPen(QPen(fg))
        badge_font = QFont(font)
        badge_font.setBold(True)
        badge_font.setPointSizeF(max(7.5, adjusted_point_size(font, -2.0)))
        painter.setFont(badge_font)
        painter.drawText(badge_left, badge_y, badge_w, badge_h, Qt.AlignmentFlag.AlignCenter, badge_text)

        # Bottom border line
        painter.setPen(QPen(QColor("#edf2ef")))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        painter.restore()


class RunListPanel(QWidget):
    """Sidebar widget showing paginated research runs and emitting selection."""

    runSelected = Signal(str)  # noqa: N815
    pageChanged = Signal()     # noqa: N815

    def __init__(self, t: Callable[[str], str], parent=None) -> None:
        super().__init__(parent)
        self._t = t
        self._page = 0
        self._per_page = 8
        self._total = 0
        self._selected_run_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header row: title + count
        header = QHBoxLayout()
        self._title = QLabel(self._t("research_runs"))
        self._title.setProperty("role", "section-title")
        self._title.style().unpolish(self._title); self._title.style().polish(self._title)
        f = self._title.font(); f.setBold(True); f.setPointSizeF(adjusted_point_size(f, 1)); self._title.setFont(f)
        header.addWidget(self._title)
        header.addStretch(1)
        self._range_label = QLabel("")
        self._range_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        header.addWidget(self._range_label)
        layout.addLayout(header)

        # List
        self._list = QListWidget()
        self._list.setItemDelegate(_RunRowDelegate(self._list))
        self._list.setMouseTracking(True)
        self._list.setUniformItemSizes(True)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list, 1)

        # Empty state
        self._empty_label = QLabel(self._t("no_runs"))
        self._empty_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 8px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        # Pagination
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        self._prev_btn = QPushButton("‹")
        self._prev_btn.setFixedWidth(28)
        self._prev_btn.clicked.connect(self._prev_page)
        nav.addWidget(self._prev_btn)
        self._page_label = QLabel("1/1")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        nav.addWidget(self._page_label, 1)
        self._next_btn = QPushButton("›")
        self._next_btn.setFixedWidth(28)
        self._next_btn.clicked.connect(self._next_page)
        nav.addWidget(self._next_btn)
        layout.addLayout(nav)

    @property
    def offset(self) -> int:
        return self._page * self._per_page

    @property
    def per_page(self) -> int:
        return self._per_page

    def set_runs(self, runs: list[Any], total: int) -> None:
        self._total = total
        # Preserve selection visually after refresh
        prev_id = self._selected_run_id
        self._list.blockSignals(True)
        self._list.clear()
        for run in runs:
            item = QListWidgetItem()
            item.setData(_RUN_ID_ROLE, run.id)
            item.setData(_QUERY_ROLE, run.query)
            item.setData(_META_ROLE, f"{run.provider} / {run.model}")
            item.setData(_STATUS_ROLE, run.status)
            self._list.addItem(item)
            if run.id == prev_id:
                item.setSelected(True)
        self._list.blockSignals(False)

        self._empty_label.setVisible(total == 0)
        self._list.setVisible(total > 0)

        if total > 0:
            start = self.offset + 1
            end = min(self.offset + self._per_page, total)
            self._range_label.setText(f"{start}–{end} of {total}")
            total_pages = max(1, (total + self._per_page - 1) // self._per_page)
            self._page_label.setText(f"{self._page + 1}/{total_pages}")
        else:
            self._range_label.setText("")
            self._page_label.setText("1/1")

        self._prev_btn.setEnabled(self._page > 0)
        self._next_btn.setEnabled(self.offset + self._per_page < total)

    def select_run(self, run_id: str) -> None:
        """Programmatically select a run (used after creating a new run)."""
        self._selected_run_id = run_id
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.data(_RUN_ID_ROLE) == run_id:
                self._list.blockSignals(True)
                it.setSelected(True)
                self._list.blockSignals(False)
                return

    def retranslate(self) -> None:
        self._title.setText(self._t("research_runs"))
        self._empty_label.setText(self._t("no_runs"))

    def _on_selection_changed(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return
        run_id = items[0].data(_RUN_ID_ROLE)
        if run_id and run_id != self._selected_run_id:
            self._selected_run_id = run_id
            self.runSelected.emit(run_id)

    def _prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self.pageChanged.emit()

    def _next_page(self) -> None:
        if self.offset + self._per_page < self._total:
            self._page += 1
            self.pageChanged.emit()
