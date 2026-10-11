# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file build for the tia-agent CLI (E6/R1).

Build:
    cd apps/tia-agent
    .venv-build/bin/pyinstaller --noconfirm --clean tia-agent.spec
    # -> dist/tia-agent

No data files are bundled: the backend compose is rendered at runtime from
``tia_agent.backend.compose`` and config/credentials live under ``~/.tia-agent``.
"""

from tia_agent.packaging import BINARY_NAME, ENTRY_SCRIPT, EXCLUDES, hidden_imports

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports(),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(EXCLUDES),
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=BINARY_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
