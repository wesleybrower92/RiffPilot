# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Riff Pilot (macOS).
Build with:  python -m PyInstaller --clean --noconfirm RiffPilot_mac.spec
Must be run on a Mac.
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Check if FFmpeg binary exists for bundling
ffmpeg_binary = []
if os.path.exists('ffmpeg'):
    ffmpeg_binary = [('ffmpeg', '.')]

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
    collect_data_files('yt_dlp') +
    [
        ('Logo.png', '.'),
    ]
)

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=ffmpeg_binary,
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
    upx=False,               # UPX not commonly used on macOS
    console=False,            # No console window — GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon='app_icon.icns',     # macOS uses .icns format
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RiffPilot',
)

app = BUNDLE(
    coll,
    name='Riff Pilot.app',
    icon='app_icon.icns',
    bundle_identifier='com.gabconsultancy.riffpilot',
    info_plist={
        'CFBundleName': 'Riff Pilot',
        'CFBundleDisplayName': 'Riff Pilot',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'NSMicrophoneUsageDescription': 'Riff Pilot needs microphone access for the Guitar Tuner.',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
    },
)
