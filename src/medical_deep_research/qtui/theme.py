from __future__ import annotations

from PySide6.QtGui import QFont


ACCENT = "#1769aa"
ACCENT_DIM = "rgba(23, 105, 170, 0.10)"
BORDER_DIM = "#d6e1ea"
TEXT_MUTED = "#6e7f91"
TEXT_SECONDARY = "#3f5268"

# Minimal QSS — keep native widget look, just normalize spacing and add badge/accent classes.
APP_QSS = f"""
QMainWindow, QWidget {{
    font-size: 13px;
}}

QGroupBox {{
    font-weight: 600;
    border: 1px solid {BORDER_DIM};
    border-radius: 6px;
    margin-top: 1.2ex;
    padding: 8px 8px 8px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER_DIM};
    border-radius: 4px;
    top: -1px;
}}
QTabBar::tab {{
    padding: 6px 12px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    font-weight: 600;
}}

QPushButton[role="primary"] {{
    background: {ACCENT};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{
    background: #145d97;
}}
QPushButton[role="primary"]:disabled {{
    background: #9fb5c7;
}}

QPushButton[role="link"] {{
    background: transparent;
    color: {ACCENT};
    border: none;
    text-decoration: underline;
    padding: 2px 4px;
}}

QLabel[role="muted"] {{
    color: {TEXT_MUTED};
}}
QLabel[role="section-title"] {{
    font-weight: 700;
    font-size: 14px;
}}
QLabel[role="section-desc"] {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

QListWidget {{
    border: 1px solid {BORDER_DIM};
    border-radius: 4px;
}}
QListWidget::item {{
    padding: 8px;
    border-bottom: 1px solid #eef2f6;
}}
QListWidget::item:selected {{
    background: {ACCENT_DIM};
    color: {TEXT_SECONDARY};
}}

QProgressBar {{
    border: 1px solid {BORDER_DIM};
    border-radius: 3px;
    background: #f1f5f9;
    text-align: center;
    height: 12px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
}}

QTextBrowser, QPlainTextEdit, QTextEdit {{
    border: 1px solid {BORDER_DIM};
    border-radius: 4px;
    background: white;
    selection-background-color: {ACCENT_DIM};
}}
"""


def default_font() -> QFont:
    """Pick a sensible default UI font.  Qt will fall back automatically if missing."""
    f = QFont()
    f.setStyleHint(QFont.StyleHint.SansSerif)
    return f


def adjusted_point_size(font: QFont, delta: float, baseline: float = 10.0) -> float:
    """Return a positive point size relative to *font*.

    Some platforms initialize fonts via pixelSize() rather than pointSizeF(),
    in which case ``font.pointSizeF()`` returns -1.  Fall back to *baseline*
    in that case so ``QFont::setPointSizeF`` never receives <= 0.
    """
    current = font.pointSizeF()
    if current <= 0:
        current = baseline
    return max(1.0, current + delta)
