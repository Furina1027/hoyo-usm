"""便携版 GUI 启动入口（PyInstaller 打包用）。

命令行参数（双击运行时全部可选）：
  --port=8788   服务端口（被占用自动顺延）
  --browser     用系统浏览器打开（回退模式）
  --no-open     仅启动服务，不开窗口/浏览器（冒烟测试用）
"""

import os
import sys
import traceback

from pathlib import Path


def _error_log(msg: str) -> None:
    """窗口模式下崩溃无处可看：写入配置目录 error.log。"""
    try:
        from hoyo_usm.config import app_data_dir

        (app_data_dir() / "error.log").write_text(msg, encoding="utf-8")
    except Exception:
        pass


def _guard_none_streams() -> None:
    """窗口模式（console=False）双击启动时 sys.stdout/stderr 为 None：
    uvicorn 等库的日志格式化器会调用 isatty() 而崩溃，重定向到 devnull。"""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main() -> int:
    _guard_none_streams()
    port = 8788
    browser = False
    window = True
    for a in sys.argv[1:]:
        if a == "--browser":
            browser = True
        elif a == "--no-open":
            window = False
        elif a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    try:
        from hoyo_usm.config import Settings
        from hoyo_usm.gui.app import launch_gui

        settings = Settings.load()
        return launch_gui(settings, browser=browser, port=port,
                          open_browser=False, window=window)
    except Exception:
        _error_log(traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(main())
