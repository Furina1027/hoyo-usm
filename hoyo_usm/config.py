"""应用配置：安装版 / 便携版 / 开发三种形态的目录策略与读写。

形态判定：
  * 冻结（PyInstaller）且 exe 旁存在 portable.ini → 便携版：配置在 exe 旁 config/
  * 冻结且无标记 → 安装版：配置在 %APPDATA%/hoyo-usm/
  * 未冻结（源码运行）→ 开发：配置在仓库根 config/

密钥目录解析顺序（gui/settings 变更后生效）：
  settings.keys_dir 显式指定 > <应用数据>/keys（密钥更新产生的用户副本）
  > 随包快照（bundled keys/）
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def exe_dir() -> Path:
    return Path(sys.executable).resolve().parent


def app_data_dir() -> Path:
    """应用配置/用户数据的根目录（按形态判定）。"""
    if is_frozen():
        if (exe_dir() / "portable.ini").exists():
            base = exe_dir() / "config"                       # 便携版：exe 旁
        else:
            base = Path(os.environ.get("APPDATA") or Path.home()) / "hoyo-usm"  # 安装版
    else:
        base = Path(__file__).resolve().parent.parent / "config"   # 开发：仓库根 config/
    base.mkdir(parents=True, exist_ok=True)
    return base


def bundled_keys_dir() -> Path:
    """随包原始密钥快照目录。"""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", exe_dir()))
        return base / "keys"
    return Path(__file__).resolve().parent.parent / "keys"


def user_keys_dir() -> Path:
    """密钥更新产生的用户副本目录（首次更新时从随包快照复制基底）。"""
    d = app_data_dir() / "keys"
    if not d.exists():
        bundled = bundled_keys_dir()
        if bundled.is_dir():
            import shutil

            shutil.copytree(bundled, d, dirs_exist_ok=True)
    return d


def effective_keys_dir(settings: "Settings") -> Path:
    if settings.keys_dir:
        return Path(settings.keys_dir)
    user = user_keys_dir()
    if any(user.glob("*.json")):
        return user
    return bundled_keys_dir()


def bundled_ffmpeg() -> Path | None:
    """随包捆绑的 ffmpeg（便携版/安装版：exe 旁 ffmpeg/ 目录）。"""
    if not is_frozen():
        return None
    for base in (exe_dir(), Path(getattr(sys, "_MEIPASS", exe_dir()))):
        p = base / "ffmpeg" / "ffmpeg.exe"
        if p.is_file():
            return p
    return None


@dataclass
class Settings:
    """GUI/CLI 共用的持久化设置。"""

    keys_dir: str = ""                          # 空 = 自动（见 effective_keys_dir）
    game_roots: dict[str, str] = field(default_factory=dict)   # {"gi": "...", ...}
    ffmpeg_path: str = ""                       # 空 = HOYO_USM_FFMPEG 或 PATH
    out_dir: str = ""                           # 空 = 仓库 export/（开发）或文档/导出
    jobs: int = 1
    theme: str = "dark"
    wizard_done: bool = False
    key_update_url: str = ""                    # 密钥更新源（raw 目录 URL），空 = 未配置
    # GUI 导出默认项（导出对话框记忆上次选择）
    audio: str = "all"
    audio_format: str = "flac"
    container: str = "auto"
    verify: bool = True

    def save(self) -> None:
        path = app_data_dir() / "config.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                        encoding="utf-8")

    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "config.json"
        s = cls()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                known = asdict(s)
                for k, v in data.items():
                    if k in known and v is not None:
                        setattr(s, k, v)
            except (json.JSONDecodeError, OSError):
                pass  # 配置损坏时回退默认值
        return s
