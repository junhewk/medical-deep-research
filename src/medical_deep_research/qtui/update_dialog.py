from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..updates import ReleaseInfo


class UpdateAvailableDialog(QDialog):
    installRequested = Signal()  # noqa: N815
    releaseRequested = Signal()  # noqa: N815
    skipRequested = Signal()  # noqa: N815

    def __init__(self, release: ReleaseInfo, current_version: str, t_fn, parent=None) -> None:
        super().__init__(parent)
        self._t = t_fn
        self.setWindowTitle(self._t("update_available"))
        self.setMinimumSize(620, 440)

        layout = QVBoxLayout(self)
        title = QLabel(
            self._t("update_version_summary").format(
                current=current_version,
                latest=release.version,
            )
        )
        title.setProperty("role", "section-title")
        title.setWordWrap(True)
        layout.addWidget(title)

        notes_label = QLabel(self._t("release_notes"))
        notes_label.setStyleSheet("font-weight: 700;")
        layout.addWidget(notes_label)

        notes = QPlainTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(release.notes or self._t("no_release_notes"))
        layout.addWidget(notes, 1)

        actions = QHBoxLayout()
        view_release = QPushButton(self._t("view_release"))
        view_release.clicked.connect(self.releaseRequested.emit)
        actions.addWidget(view_release)
        skip = QPushButton(self._t("skip_version"))
        skip.clicked.connect(self.skipRequested.emit)
        actions.addWidget(skip)
        actions.addStretch(1)
        install = QPushButton(self._t("download_restart"))
        install.setDefault(True)
        install.clicked.connect(self.installRequested.emit)
        actions.addWidget(install)
        later_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        later_box.button(QDialogButtonBox.StandardButton.Cancel).setText(self._t("later"))
        later_box.rejected.connect(self.reject)
        actions.addWidget(later_box)
        layout.addLayout(actions)

        self.setWindowModality(Qt.WindowModality.WindowModal)
