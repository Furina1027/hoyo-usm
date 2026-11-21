"""通用游戏目录检测（面向分发的其他用户，不假设任何个人路径）。

检测链（全部失败 → None，调用方进入手动选择）：
  1. 注册表卸载项：HKLM/HKCU Uninstall，按 key 名前缀/DisplayName 匹配游戏，
     InstallLocation 常是**启动器根**（如 E:\\miHoYo Launcher），需在其下限深搜索
     含游戏 exe 的目录；云游戏（云·原神 / *Cloud）排除
  2. 盘符扫描：固定盘根目录 + 两级子目录（限量），找游戏 exe 标记

判定标记：游戏根目录 = 含 YuanShen.exe（原神）/ StarRail.exe（星铁）/
ZenlessZoneZero.exe（绝区零）的目录。
"""

from __future__ import annotations

import os
import threading
from collections import deque
from pathlib import Path

try:
    import winreg
except ImportError:          # 非 Windows（预留跨平台）
    winreg = None            # type: ignore[assignment]

#: 游戏主程序 exe 标记（渠道不同 exe 名不同，全部列出）
GAME_EXES: dict[str, tuple[str, ...]] = {
    "gi": ("YuanShen.exe", "GenshinImpact.exe"),
    "hsr": ("StarRail.exe",),
    "zzz": ("ZenlessZoneZero.exe",),
}

#: 注册表 key 名/DisplayName 的匹配关键词
GAME_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "gi": ("genshin", "yuan", "hk4e", "原神"),
    "hsr": ("hkrpg", "star rail", "崩坏：星穹铁道", "崩坏:星穹铁道"),
    "zzz": ("nap", "zenless", "绝区零"),
}

SCAN_DRIVES = "CDEFGH"
SCAN_MAX_DIRS = 1500         # 每盘 BFS 目录数上限（三级深度，纯 is_file 检查）
SEARCH_DEPTH = 3             # 注册表 InstallLocation 下的搜索深度

#: BFS 剪枝：已知与游戏无关的大目录（AppData/Windows 等），跳过可大幅提速
_PRUNE_DIRS = {"windows", "program files", "program files (x86)", "programdata",
               "$recycle.bin", "system volume information", "appdata",
               "perflogs", "recovery", "intel", "nvidia", "drivers", "temp"}

# 后台扫描缓存：服务启动即开跑，向导/设置轮询结果
_cache_lock = threading.Lock()
_cache: dict = {"result": None, "done": False, "started": False}


def _pruned_subdirs(d: Path) -> list[Path]:
    try:
        return [c for c in d.iterdir()
                if c.is_dir() and c.name.lower() not in _PRUNE_DIRS]
    except OSError:
        return []


def _bfs_collect(base: Path, max_depth: int, cap: int) -> list[Path]:
    """从 base 出发收集 ≤max_depth 层的目录（剪枝 + 限量）。"""
    dirs: list[Path] = []
    dq: deque[tuple[Path, int]] = deque([(base, 0)])
    seen = 0
    while dq and seen < cap:
        d, depth = dq.popleft()
        seen += 1
        dirs.append(d)
        if depth < max_depth:
            dq.extend((c, depth + 1) for c in _pruned_subdirs(d))
    return dirs


def start_background_scan() -> None:
    """启动后台全量扫描（幂等）；结果供 cached_game_roots() 轮询。"""
    with _cache_lock:
        if _cache["started"]:
            return
        _cache["started"] = True

    def _work() -> None:
        r = detect_game_roots()
        with _cache_lock:
            _cache["result"] = r
            _cache["done"] = True

    threading.Thread(target=_work, daemon=True, name="hoyo-usm-detect").start()


def cached_game_roots() -> dict:
    with _cache_lock:
        return {"result": _cache["result"], "done": _cache["done"]}


def fast_game_roots() -> dict[str, str | None]:
    """仅注册表（毫秒级）；供不能阻塞的场景使用。"""
    found = _from_registry()
    return {gid: found.get(gid) for gid in GAME_EXES}


def detect_game_roots() -> dict[str, str | None]:
    """全量检测（注册表 + 盘符扫描，可能数秒）——建议经后台缓存调用。"""
    found = _from_registry()
    for gid, loc in _from_drive_scan().items():
        found.setdefault(gid, loc)
    return {gid: found.get(gid) for gid in GAME_EXES}


def _has_game_exe(root: Path, gid: str) -> bool:
    return any((root / exe).is_file() for exe in GAME_EXES[gid])


def _is_cloud(display: str, key_name: str) -> bool:
    return "cloud" in key_name.lower() or display.startswith("云")


def _exe_root_under(base: Path, gid: str) -> Path | None:
    """在 base 及其 ≤SEARCH_DEPTH 层子目录中找含游戏 exe 的目录（先浅后深）。"""
    for d in _bfs_collect(base, SEARCH_DEPTH, 800):
        if _has_game_exe(d, gid):
            return d
    return None
    return None


def _match_gid(key_name: str, display: str) -> list[str]:
    """返回与该卸载项匹配的游戏 id 列表（可多个，调用方逐个验证）。"""
    text = (key_name + " " + display).lower()
    return [gid for gid, hints in GAME_NAME_HINTS.items() if any(h in text for h in hints)]


def _from_registry() -> dict[str, str]:
    found: dict[str, str] = {}
    if winreg is None:
        return found
    views = [winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY]
    hives = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]
    for hive in hives:
        for view in views:
            try:
                base = winreg.OpenKey(hive,
                                      r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                                      0, winreg.KEY_READ | view)
            except OSError:
                continue
            with base:
                i = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(base, i)
                        i += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(base, sub_name, 0, winreg.KEY_READ | view) as sub:
                            display = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                            try:
                                loc = str(winreg.QueryValueEx(sub, "InstallLocation")[0])
                            except OSError:
                                loc = ""
                    except OSError:
                        continue
                    if not loc or _is_cloud(display, sub_name):
                        continue
                    for gid in _match_gid(sub_name, display):
                        if gid in found:
                            continue
                        root = _exe_root_under(Path(loc), gid)
                        if root:
                            found[gid] = str(root)
    return found


def _from_drive_scan() -> dict[str, str]:
    found: dict[str, str] = {}
    for drive in SCAN_DRIVES:
        if all(g in found for g in GAME_EXES):
            break
        root = Path(f"{drive}:\\")
        if not root.is_dir():
            continue
        for d in _bfs_collect(root, 3, SCAN_MAX_DIRS):
            for gid, exes in GAME_EXES.items():
                if gid not in found and any((d / exe).is_file() for exe in exes):
                    found[gid] = str(d)
    return found


def detect_game_roots() -> dict[str, str | None]:
    """返回 {"gi": 路径或 None, "hsr": ..., "zzz": ...}。"""
    found = _from_registry()
    for gid, loc in _from_drive_scan().items():
        found.setdefault(gid, loc)
    return {gid: found.get(gid) for gid in GAME_EXES}
