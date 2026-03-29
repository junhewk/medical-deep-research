# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

import re as _re

datas = [('src/medical_deep_research', 'medical_deep_research')]
# Note: do NOT add the nicegui directory here — collect_all() below adds individual files,
# which lets the exclusion filter strip unused element bundles.
binaries = []
hiddenimports = ['medical_deep_research', 'medical_deep_research.main', 'medical_deep_research.ui', 'medical_deep_research.config', 'medical_deep_research.models', 'medical_deep_research.persistence', 'medical_deep_research.service', 'medical_deep_research.runtime', 'medical_deep_research.agentic_tools', 'medical_deep_research.tools', 'medical_deep_research.research', 'medical_deep_research.research.planning', 'medical_deep_research.research.search', 'medical_deep_research.research.scoring', 'medical_deep_research.research.verification', 'medical_deep_research.research.reporting', 'medical_deep_research.research.models', 'medical_deep_research.mcp', 'medical_deep_research.mcp.servers', 'pydantic_settings', 'sqlmodel', 'nicegui', 'httpx', 'anyio']
hiddenimports += collect_submodules('medical_deep_research')
tmp_ret = collect_all('nicegui')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Strip heavy NiceGUI element JS/CSS bundles that this app never uses (~57 MB)
_exclude_elements = [
    'plotly', 'echart', 'mermaid', 'codemirror', 'json_editor',
    'aggrid', 'scene', 'leaflet', 'xterm', 'joystick', 'anywidget',
]
_excl_pat = _re.compile(
    r'nicegui[/\\]elements[/\\](' + '|'.join(_exclude_elements) + r')([/\\]|$)'
)
datas = [(src, dst) for src, dst in datas if not _excl_pat.search(src) and not _excl_pat.search(dst)]

a = Analysis(
    ['scripts/desktop_entry.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
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
