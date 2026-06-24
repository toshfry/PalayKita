# -*- mode: python ; coding: utf-8 -*-
r"""
PyInstaller spec for PalayKita Desktop.

Default build command:
    pyinstaller palaykita_desktop.spec --clean

Why this spec uses a fresh output folder:
    Windows cannot delete dist\PalayKita while the old desktop app is open.
    To prevent locked-folder build failures, the default output is:

        dist\PalayKita_Build_YYYYMMDD_HHMMSS\PalayKita.exe

Stable release build, only when the old app is closed:
    PowerShell:
        $env:PALAYKITA_DIST_NAME = "PalayKita"
        pyinstaller palaykita_desktop.spec --clean --noconfirm
"""

from datetime import datetime
from pathlib import Path
import os


ROOT = Path(globals().get("SPECPATH", ".")).resolve()


def _mkdir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def _add_data(datas, source, target):
    source_path = ROOT / source
    if source_path.exists():
        datas.append((str(source_path), target))
    else:
        print(f"WARNING: Skipping missing data path: {source_path}")


# Runtime folders are created here so the source tree is ready, but they are not
# bundled as application data. Bundling them can copy local databases/backups into
# the EXE folder and can also make rebuilds fail when an old build is running.
for runtime_folder in (
    "instance",
    "backups",
    "exports/reports/daily",
    "exports/reports/weekly",
    "exports/reports/monthly",
    "exports/reports/custom",
    "exports/reports/commercial",
):
    _mkdir(ROOT / runtime_folder)


datas = []
_add_data(datas, "templates", "templates")
_add_data(datas, "static", "static")

if (ROOT / "palaykita_logo.png").exists():
    _add_data(datas, "palaykita_logo.png", ".")


dist_name = os.environ.get("PALAYKITA_DIST_NAME")
if not dist_name:
    dist_name = f"PalayKita_Build_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


block_cipher = None


a = Analysis(
    ["desktop_app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "app.server_control",
        "flask",
        "flask_sqlalchemy",
        "werkzeug.security",
        "waitress",
        "sqlalchemy",
        "sqlite3",
        "openpyxl",
        "dotenv",
        "webview",
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "clr",
        "clr_loader",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="PalayKita",
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
    icon=str(ROOT / "static" / "icons" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=dist_name,
)
