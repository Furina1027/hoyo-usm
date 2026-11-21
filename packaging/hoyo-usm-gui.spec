# -*- mode: python ; coding: utf-8 -*-
"""便携版 GUI 打包配置（onedir + windowed）。

用法（仓库根目录执行）：
    pyinstaller packaging/hoyo-usm-gui.spec --noconfirm

数据捆绑：
    hoyo_usm/gui/dist → hoyo_usm/gui/dist   （Vue3 前端构建产物）
    keys/             → keys                （自包含密钥快照）
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent
DIST_WEB = ROOT / "hoyo_usm" / "gui" / "dist"
KEYS = ROOT / "keys"

datas = [
    (str(DIST_WEB), "hoyo_usm/gui/dist"),
    (str(KEYS), "keys"),
    (str(ROOT / "packaging" / "appicon.png"), "."),
]
binaries = []
hiddenimports = [
    "hoyo_usm.config", "hoyo_usm.detect", "hoyo_usm.identify", "hoyo_usm.probe",
    "hoyo_usm.export", "hoyo_usm.crypto", "hoyo_usm.keys", "hoyo_usm.games",
    "hoyo_usm.verify", "hoyo_usm.audio.hca", "hoyo_usm.audio.adx", "hoyo_usm.audio.pcm",
    "hoyo_usm.gui.server", "hoyo_usm.gui.app", "hoyo_usm.gui.tasks",
    # uvicorn 的延迟导入子模块
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.off",
]

# pywebview（WebView2 后端依赖 pythonnet/clr_loader 及其 DLL）、cricodecs（nanobind 扩展）
for pkg in ("webview", "pythonnet", "clr_loader", "cricodecs"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "packaging" / "gui_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 机器上可能同时装有多个 Qt 绑定（兄弟仓）；本应用用 WebView2 后端，全部排除。
    # 另外排除全局环境里与本应用无关的重型包（collect 链条误拉，约占 600MB）
    excludes=[
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "torch", "torchvision", "torchaudio", "cv2", "scipy", "sklearn",
        "pandas", "matplotlib", "PIL", "onnxruntime", "av", "imageio_ffmpeg",
        "cryptography", "IPython", "jupyter",
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
    name="hoyo-usm-gui",
    icon=str(ROOT / "packaging" / "appicon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 窗口应用：无控制台
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
    upx=False,
    upx_exclude=[],
    name="hoyo-usm-gui",
)
