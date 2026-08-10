# PyInstaller one-folder build specification for Windows x64.
from PyInstaller.utils.hooks import collect_submodules


hiddenimports = collect_submodules("mcp") + [
    "pydantic.deprecated.decorator",
    "skillcheck.reports",
]

a = Analysis(
    ["src/skillcheck/app/main.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="skillcheck",
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="skillcheck",
)
