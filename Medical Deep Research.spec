# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

import importlib.util as _importlib_util

datas = [('src/medical_deep_research', 'medical_deep_research')]
binaries = []
hiddenimports = [
    'medical_deep_research',
    'medical_deep_research.main',
    'medical_deep_research.qtui',
    'medical_deep_research.qtui.main_window',
    'medical_deep_research.qtui.sidebar',
    'medical_deep_research.qtui.run_list',
    'medical_deep_research.qtui.i18n',
    'medical_deep_research.qtui.theme',
    'medical_deep_research.qtui.widgets.badge',
    'medical_deep_research.qtui.widgets.markdown_view',
    'medical_deep_research.qtui.tabs.trace_tab',
    'medical_deep_research.qtui.tabs.artifacts_tab',
    'medical_deep_research.qtui.tabs.report_tab',
    'medical_deep_research.qtui.tabs.diagnostics_tab',
    'medical_deep_research.qtui.tabs.studies_tab',
    'medical_deep_research.config',
    'medical_deep_research.models',
    'medical_deep_research.persistence',
    'medical_deep_research.service',
    'medical_deep_research.runtime',
    'medical_deep_research.agentic_tools',
    'medical_deep_research.tools',
    'medical_deep_research.research',
    'medical_deep_research.research.planning',
    'medical_deep_research.research.search',
    'medical_deep_research.research.scoring',
    'medical_deep_research.research.verification',
    'medical_deep_research.research.reporting',
    'medical_deep_research.research.models',
    'medical_deep_research.mcp',
    'medical_deep_research.mcp.servers',
    'pydantic_settings',
    'sqlmodel',
    'qasync',
    'httpx',
    'anyio',
]
hiddenimports += collect_submodules('medical_deep_research')

# Let PyInstaller's PySide6 hooks collect only the Qt modules imported by the
# app. collect_all('PySide6') pulls in WebEngine, QML, Designer, PDF, and other
# unused Qt runtimes, which makes the Windows ZIP hundreds of MB larger.
tmp_ret = collect_all('qasync')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

for _pkg in ('anthropic', 'langchain', 'langchain_anthropic', 'langgraph', 'deepagents', 'markitdown'):
    if _importlib_util.find_spec(_pkg) is None:
        continue
    tmp_ret = collect_all(_pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

a = Analysis(
    ['scripts/desktop_entry.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtCharts',
        'PySide6.QtMultimedia',
        'PySide6.QtBluetooth',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Medical Deep Research',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    icon='assets/icon.ico',
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    contents_directory='runtime',
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Medical Deep Research',
)
app = BUNDLE(
    coll,
    name='Medical Deep Research.app',
    icon='assets/icon.icns',
    bundle_identifier='com.junhewk.medical-deep-research',
)
