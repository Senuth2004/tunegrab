# Build with: python -m PyInstaller --noconfirm tunegrab.spec
from PyInstaller.utils.hooks import collect_all
import sys

datas = []
binaries = []
hiddenimports = []
datas.append(("tunegrab/assets/tunegrab.svg", "."))
datas.append(("THIRD_PARTY_NOTICES.txt", "."))
if sys.platform == "win32":
    from imageio_ffmpeg import get_ffmpeg_exe

    binaries.append((get_ffmpeg_exe(), "."))
for package in ("yt_dlp", "mutagen"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    ["packaging/launcher.py"],
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
    name="Tunegrab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Tunegrab",
)
