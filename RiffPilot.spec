# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Riff Pilot.
Build with:  python -m PyInstaller --clean --noconfirm RiffPilot.spec
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Only collect submodules we actually need — avoid pulling in test suites
hiddenimports = (
    collect_submodules('librosa') +
    collect_submodules('sounddevice') +
    collect_submodules('soundfile') +
    collect_submodules('yt_dlp') +
    collect_submodules('demucs') +
    [
        'numpy',
        'scipy',
        'scipy.signal',
        'scipy.fft',
        'scipy.io',
        'scipy.io.wavfile',
        'scipy.sparse',
        'soxr',
        'sklearn.decomposition',
        'sklearn.utils',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
    ]
)

# Collect data files required at runtime
datas = (
    collect_data_files('librosa') +
    collect_data_files('demucs') +
    [
        ('Logo.png', '.'),
    ]
)

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'sklearn.tests',
        'sklearn.datasets.tests',
        'sklearn.decomposition.tests',
        'sklearn.ensemble.tests',
        'sklearn.experimental.tests',
        'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DRender',
        'PySide6.Qt3DInput',
        'PySide6.QtQuick',
        'PySide6.QtQml',
        'PySide6.QtDesigner',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RiffPilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No console window — GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon='app_icon.ico',    # Window icon + taskbar icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RiffPilot',
)
