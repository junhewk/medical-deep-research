from __future__ import annotations

from importlib import resources

from PySide6.QtGui import QFont, QFontDatabase


# A restrained contemporary clinical palette: warm paper, teal primary,
# indigo secondary, amber warnings, and clear semantic states.
APP_BG = "#f6f8f7"
SURFACE = "#ffffff"
SURFACE_SOFT = "#f0f6f4"
ACCENT = "#0f766e"
ACCENT_HOVER = "#115e59"
ACCENT_DIM = "rgba(15, 118, 110, 0.11)"
ACCENT_SOFT = "#e4f3f1"
SECONDARY = "#4f46e5"
SECONDARY_SOFT = "#eef2ff"
BORDER_DIM = "#d9e5df"
BORDER_STRONG = "#b8cac2"
TEXT_PRIMARY = "#182230"
TEXT_SECONDARY = "#344054"
TEXT_MUTED = "#667085"
SUCCESS = "#027a48"
WARNING = "#b54708"
ERROR = "#b42318"

_FONT_FAMILY = "Pretendard"


def load_embedded_fonts() -> list[str]:
    """Load bundled application fonts and return the registered families."""
    global _FONT_FAMILY

    try:
        font_ref = resources.files("medical_deep_research").joinpath(
            "assets/fonts/PretendardVariable.ttf"
        )
        with resources.as_file(font_ref) as font_path:
            font_id = QFontDatabase.addApplicationFont(str(font_path))
    except (FileNotFoundError, ModuleNotFoundError):
        return []

    if font_id < 0:
        return []

    families = QFontDatabase.applicationFontFamilies(font_id)
    if families:
        _FONT_FAMILY = families[0]
    return families


# Keep native widgets recognizable, while giving the app a coherent modern
# visual system. The app font is applied through QApplication.setFont().
APP_QSS = f"""
QMainWindow, QWidget {{
    font-size: 14px;
    color: {TEXT_PRIMARY};
}}

QMainWindow, QTabWidget, QScrollArea, QStackedWidget {{
    background: {APP_BG};
}}

QGroupBox {{
    background: {SURFACE};
    font-weight: 650;
    border: 1px solid {BORDER_DIM};
    border-radius: 8px;
    margin-top: 1.2ex;
    padding: 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {TEXT_SECONDARY};
}}

QTabWidget::pane {{
    border: 1px solid {BORDER_DIM};
    border-radius: 8px;
    top: -1px;
    background: {SURFACE};
}}
QTabBar::tab {{
    padding: 8px 14px;
    margin-right: 3px;
    color: {TEXT_MUTED};
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}}
QTabBar::tab:selected {{
    background: {SURFACE};
    color: {ACCENT};
    border-color: {BORDER_DIM};
    font-weight: 650;
}}
QTabBar::tab:hover:!selected {{
    background: {SURFACE_SOFT};
    color: {TEXT_SECONDARY};
}}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit, QTextBrowser {{
    border: 1px solid {BORDER_DIM};
    border-radius: 7px;
    background: {SURFACE};
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit, QComboBox, QSpinBox {{
    padding: 5px 7px;
    min-height: 24px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus, QTextBrowser:focus {{
    border-color: {ACCENT};
}}

QPushButton {{
    border: 1px solid {BORDER_DIM};
    border-radius: 7px;
    padding: 6px 12px;
    background: {SURFACE};
    color: {TEXT_SECONDARY};
}}
QPushButton:hover {{
    background: {SURFACE_SOFT};
    border-color: {BORDER_STRONG};
}}
QPushButton:disabled {{
    color: #98a2b3;
    background: #f2f4f7;
}}
QPushButton[role="primary"] {{
    background: {ACCENT};
    color: white;
    border: none;
    padding: 8px 16px;
    font-weight: 650;
}}
QPushButton[role="primary"]:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton[role="primary"]:disabled {{
    background: #9db8b4;
}}
QPushButton[role="danger"] {{
    color: {ERROR};
    border-color: #f3c3bd;
}}
QPushButton[role="link"] {{
    background: transparent;
    color: {ACCENT};
    border: none;
    text-decoration: underline;
    padding: 2px 4px;
}}

QToolButton[role="tab-corner"] {{
    border: 1px solid {BORDER_DIM};
    border-radius: 7px;
    padding: 5px 10px;
    margin-right: 8px;
    background: {SURFACE};
    color: {TEXT_SECONDARY};
}}
QToolButton[role="tab-corner"]:hover {{
    background: {SURFACE_SOFT};
}}

QLabel[role="muted"] {{
    color: {TEXT_MUTED};
}}
QLabel[role="section-title"] {{
    font-weight: 700;
    font-size: 15px;
}}
QLabel[role="section-desc"] {{
    color: {TEXT_MUTED};
    font-size: 13px;
}}

QListWidget {{
    border: 1px solid {BORDER_DIM};
    border-radius: 7px;
    background: {SURFACE};
}}
QListWidget::item {{
    padding: 8px;
    border-bottom: 1px solid #edf2ef;
}}
QListWidget::item:selected {{
    background: {ACCENT_DIM};
    color: {TEXT_SECONDARY};
}}
QListWidget[role="report-outline"] {{
    background: {SURFACE_SOFT};
}}
QListWidget[role="report-outline"]::item {{
    border-bottom: none;
    padding: 7px 8px;
}}

QProgressBar {{
    border: 1px solid {BORDER_DIM};
    border-radius: 4px;
    background: #eef4f1;
    text-align: center;
    height: 12px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 3px;
}}

QTextBrowser, QPlainTextEdit, QTextEdit {{
    background: {SURFACE};
}}
QStatusBar {{
    background: {SURFACE};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER_DIM};
}}
"""


def default_font() -> QFont:
    """Pick the bundled UI font, with platform CJK fallback for Korean text."""
    f = QFont(_FONT_FAMILY)
    f.setStyleHint(QFont.StyleHint.SansSerif)
    f.setPointSizeF(11.0)
    return f


def report_font() -> QFont:
    f = QFont(_FONT_FAMILY)
    f.setStyleHint(QFont.StyleHint.SansSerif)
    f.setPointSizeF(12.0)
    return f


def adjusted_point_size(font: QFont, delta: float, baseline: float = 10.0) -> float:
    """Return a positive point size relative to *font*.

    Some platforms initialize fonts via pixelSize() rather than pointSizeF(),
    in which case ``font.pointSizeF()`` returns -1. Fall back to *baseline*
    in that case so ``QFont::setPointSizeF`` never receives <= 0.
    """
    current = font.pointSizeF()
    if current <= 0:
        current = baseline
    return max(1.0, current + delta)
