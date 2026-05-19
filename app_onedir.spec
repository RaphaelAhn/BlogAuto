# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = [
    ('automation/app.py', 'automation'),
    ('automation/streamlit_launcher.py', 'automation'),
    ('automation/data', 'automation/data'),
    ('automation/scripts', 'automation/scripts'),
    ('automation/content', 'automation/content'),
]

streamlit_datas, streamlit_binaries, streamlit_hiddenimports = collect_all('streamlit')
datas += streamlit_datas

datas += copy_metadata('streamlit')
datas += copy_metadata('pandas')
datas += copy_metadata('requests')

a = Analysis(
    ['automation/streamlit_launcher.py'],
    pathex=['automation/scripts'],
    binaries=streamlit_binaries,
    datas=datas,
    hiddenimports=[
        'pandas',
        'requests',
        'bs4',
        'lxml',
        'concurrent.futures',
    ] + streamlit_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['plotly', 'altair', 'selenium', 'webdriver_manager'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Project_Blog',
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
    name='Project_Blog',
)
