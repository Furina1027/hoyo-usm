"""GUI 启动入口：本地 FastAPI 服务 + pywebview 原生窗口（可回退浏览器）。

pywebview 的 js_api 暴露原生文件/目录选择对话框；窗口模式下还在 document 上
挂 drop 监听，拿到拖入文件的真实路径（浏览器安全模型拿不到）后回推给前端
window.__hoyoNativeDrop(paths)。浏览器模式下这两项不可用，前端退回"粘贴路径"。
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from ..config import Settings
from .server import create_app


def _icon_path() -> Path | None:
    """窗口图标（png）：随包 appicon.png，源码运行取仓库 packaging/。"""
    if getattr(sys, "frozen", False):
        for base in (Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).resolve().parent):
            p = base / "appicon.png"
            if p.is_file():
                return p
        return None
    p = Path(__file__).resolve().parents[2] / "packaging" / "appicon.png"
    return p if p.is_file() else None


def _window():
    import webview

    return webview.windows[0] if webview.windows else None


class NativeApi:
    """暴露给前端 JS 的原生对话框（window.pywebview.api.*）。"""

    def pick_usm_files(self) -> list[str]:
        import webview

        w = _window()
        if w is None:
            return []
        r = w.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                 file_types=("USM 动画 (*.usm)", "全部文件 (*.*)"))
        return list(r or [])

    def pick_directory(self, initial: str = "") -> str:
        import webview

        w = _window()
        if w is None:
            return ""
        r = w.create_file_dialog(webview.FileDialog.FOLDER, directory=initial or "")
        return r[0] if r else ""

    def pick_file(self, initial: str = "", pattern: str = "全部文件 (*.*)") -> str:
        import webview

        w = _window()
        if w is None:
            return ""
        r = w.create_file_dialog(webview.FileDialog.OPEN, directory=initial or "",
                                 file_types=(pattern,))
        return r[0] if r else ""


def _bind_native_drop(window) -> None:
    """document 级 drop 监听：pywebview 会在事件里补上 pywebviewFullPath。"""
    from webview.dom import DOMEventHandler

    def on_drop(e: dict) -> None:
        files = (e.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            window.evaluate_js(f"window.__hoyoNativeDrop && window.__hoyoNativeDrop({json.dumps(paths)})")

    window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)


def _free_port(start: int) -> int:
    port = start
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1
    return start


def launch_gui(settings: Settings, *, browser: bool = False, port: int | None = None,
               open_browser: bool = True, window: bool = True) -> int:
    """启动 GUI：后台线程跑 FastAPI，主线程开 pywebview 窗口（或浏览器）。

    window=False 时不打开任何窗口/浏览器，仅运行服务（冒烟测试用）。
    """
    import uvicorn

    port = _free_port(port or 8788)
    # log_config=None：跳过 uvicorn 自带的 dictConfig（其 DefaultFormatter 会访问
    # sys.stdout.isatty()，窗口模式双击启动时 stdout 为 None 而崩溃）
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1",
                                           port=port, log_level="warning",
                                           log_config=None))
    th = threading.Thread(target=server.run, daemon=True, name="hoyo-usm-server")
    th.start()
    for _ in range(100):            # 等待就绪（最多 10s）
        if server.started:
            break
        time.sleep(0.1)

    url = f"http://127.0.0.1:{port}/"
    if window and not browser:
        try:
            import webview          # pywebview（Windows: WebView2 + pythonnet）

            dark = (settings.theme or "dark") != "light"
            win = webview.create_window(
                "hoyo-usm", url, width=1360, height=880, min_size=(1100, 720),
                js_api=NativeApi(), background_color="#0c0c10" if dark else "#f6f6f8")
            win.events.loaded += lambda: _bind_native_drop(win)
            webview.start(icon=_icon_path())  # 阻塞至窗口关闭
            server.should_exit = True
            th.join(timeout=5)
            return 0
        except Exception as exc:    # pywebview 不可用 → 回退浏览器
            print(f"pywebview 不可用（{exc}），回退浏览器模式", flush=True)

    if open_browser:
        webbrowser.open(url)
    print(f"hoyo-usm GUI 已启动：{url}（关闭此进程即停止服务）", flush=True)
    try:
        while server.started and not server.should_exit:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    server.should_exit = True
    return 0
