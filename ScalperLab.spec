# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH).resolve()
webview_datas, webview_binaries, webview_hidden = collect_all("webview")
mt5_datas, mt5_binaries, mt5_hidden = collect_all("MetaTrader5")
pythonnet_datas, pythonnet_binaries, pythonnet_hidden = collect_all("pythonnet")
clr_datas, clr_binaries, clr_hidden = collect_all("clr_loader")

common_hidden = sorted(set(
    webview_hidden + mt5_hidden + pythonnet_hidden + clr_hidden
    + ["webview.platforms.edgechromium", "webview.platforms.winforms",
       "webview.platforms.mshtml", "clr", "_cffi_backend", "numpy"]
))
common_datas = (
    webview_datas + mt5_datas + pythonnet_datas + clr_datas
    + [(str(ROOT / "templates"), "templates"), (str(ROOT / "static"), "static")]
    + [(str(ROOT / "mt5"), "MT5")]
)
common_binaries = webview_binaries + mt5_binaries + pythonnet_binaries + clr_binaries

app_analysis = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=common_binaries,
    datas=common_datas,
    hiddenimports=common_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff"],
    noarchive=False,
    optimize=0,
)
app_pyz = PYZ(app_analysis.pure)
app_exe = EXE(
    app_pyz,
    app_analysis.scripts,
    [],
    exclude_binaries=True,
    name="ScalperLab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "static" / "brand" / "scalperlab-pro.ico"),
    uac_admin=True,
)

validator_analysis = Analysis(
    [str(ROOT / "tools" / "strategy_validator_worker.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
validator_pyz = PYZ(validator_analysis.pure)
validator_exe = EXE(
    validator_pyz,
    validator_analysis.scripts,
    [],
    exclude_binaries=True,
    name="ScalperLabStrategyValidator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    app_exe,
    validator_exe,
    app_analysis.binaries,
    app_analysis.datas,
    validator_analysis.binaries,
    validator_analysis.datas,
    strip=False,
    upx=False,
    name="ScalperLab",
)
