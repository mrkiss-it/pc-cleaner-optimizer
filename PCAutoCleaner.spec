# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/Project/pc_cleaner_optimizer/main.py'],
    pathex=[],
    binaries=[],
    datas=[('D:/Project/pc_cleaner_optimizer/assets', 'assets')],
    hiddenimports=['PyQt5.QtNetwork', 'PyQt5.QtCore', 'PyQt5.QtWidgets', 'PyQt5.QtGui', 'psutil', 'winreg', 'core.security_scanner', 'core.hardware_monitor', 'core.ai_advisor', 'core.service_optimizer', 'core.context_menu_manager', 'core.uninstaller_manager', 'core.winsxs_cleaner', 'core.predictive_ai', 'ui.hardware_dialog', 'ui.ai_advisor_dialog', 'ui.service_context_dialog', 'ui.uninstaller_dialog', 'ui.winsxs_dialog'],
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
    name='PCAutoCleaner',
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
    icon=['D:/Project/pc_cleaner_optimizer/assets/icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PCAutoCleaner',
)
