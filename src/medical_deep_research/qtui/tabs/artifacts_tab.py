from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..theme import adjusted_point_size


class ArtifactsTab(QWidget):
    """List of run artifacts with preview pane."""

    def __init__(self, t: Callable[[str], str], parent=None) -> None:
        super().__init__(parent)
        self._t = t

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._title = QLabel(self._t("artifacts"))
        f = self._title.font(); f.setBold(True); f.setPointSizeF(adjusted_point_size(f, 1)); self._title.setFont(f)
        layout.addWidget(self._title)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #6e7f91; font-size: 11px;")
        layout.addWidget(self._count_label)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Type", "Name"])
        self._tree.itemSelectionChanged.connect(self._on_selection)
        self._splitter.addWidget(self._tree)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setStyleSheet("QPlainTextEdit { font-family: monospace; font-size: 11px; background: #f8fafc; }")
        self._splitter.addWidget(self._preview)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 2)
        layout.addWidget(self._splitter, 1)

        self._empty = QLabel(self._t("no_artifacts"))
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #6e7f91; font-size: 12px;")
        layout.addWidget(self._empty)

        self._artifacts: list = []

    def set_artifacts(self, artifacts: list) -> None:
        self._artifacts = artifacts
        self._count_label.setText(f"{len(artifacts)} artifacts")
        self._tree.clear()
        self._preview.clear()
        if not artifacts:
            self._empty.setVisible(True)
            self._splitter.setVisible(False)
            return
        self._empty.setVisible(False)
        self._splitter.setVisible(True)
        for i, art in enumerate(artifacts):
            item = QTreeWidgetItem([art.artifact_type, art.name])
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self._tree.addTopLevelItem(item)

    def _on_selection(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        idx = items[0].data(0, Qt.ItemDataRole.UserRole)
        if idx is None or idx >= len(self._artifacts):
            return
        art = self._artifacts[idx]
        chunks = []
        if art.content_text:
            chunks.append(art.content_text)
        if art.content_json:
            chunks.append(art.content_json)
        self._preview.setPlainText("\n\n".join(chunks))

    def retranslate(self) -> None:
        self._title.setText(self._t("artifacts"))
        self._empty.setText(self._t("no_artifacts"))
