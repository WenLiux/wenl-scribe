from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


project_root = Path(SPEC).resolve().parents[1]
datas = [(str(project_root / "desktop-dist"), "static")]
datas += collect_data_files("faster_whisper")
binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("av")
hiddenimports = [
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "huggingface_hub",
    "onnxruntime",
    "pystray._win32",
]

a = Analysis(
    [str(project_root / "backend" / "desktop_main.py")],
    pathex=[str(project_root / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "matplotlib",
        "pystray._appindicator",
        "pystray._darwin",
        "pystray._gtk",
        "pystray._xorg",
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
    name="WENL Scribe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WENL Scribe",
)
