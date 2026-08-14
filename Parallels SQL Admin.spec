# -*- mode: python ; coding: utf-8 -*-
# Кроссплатформенная спецификация PyInstaller.
#
#   macOS:   EXE + COLLECT + BUNDLE (.app) с .icns;
#   Windows: EXE + COLLECT (one-folder) с .ico;
#   Linux:   EXE + COLLECT (one-folder), иконка exe не встраивается.
#
# Windows/Linux-сборки выполняются в GitHub Actions (см. build.yml):
# PyInstaller не поддерживает кросс-компиляцию.
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

from common.version import APP_VERSION

datas = [('config.ini', '.'), ('servers.txt', '.'), ('assets', 'assets')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('PySide6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
hiddenimports += collect_submodules('encodings')

for pkg in ('pymssql', 'cryptography', 'psycopg'):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

if sys.platform == 'win32':
    icon_path = 'assets/ParallelsSQLAdmin.ico'
else:
    icon_path = 'assets/ParallelsSQLAdmin.icns'

# Иконка EXE встраивается только на Windows (.ico) и macOS (.icns);
# на Linux она игнорируется PyInstaller.
exe_icon = [icon_path] if sys.platform in ('win32', 'darwin') else []


a = Analysis(
    ['app.py'],
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
    name='Parallels SQL Admin',
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
    icon=exe_icon,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Parallels SQL Admin',
)
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Parallels SQL Admin.app',
        icon=icon_path,
        bundle_identifier=None,
        info_plist={
            'CFBundleShortVersionString': APP_VERSION,
            'CFBundleVersion': APP_VERSION,
        },
    )
