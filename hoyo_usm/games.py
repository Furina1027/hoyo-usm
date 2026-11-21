"""三款游戏的 profile：目录布局、密钥文件、语言映射、扫描去重。

目录布局以本机实际安装为基准（2026-11 实测）：
  原神   YuanShen_Data/{StreamingAssets,Persistent}/VideoAssets/…
  星铁   StarRail_Data/{StreamingAssets,Persistent}/Video/Windows/…
  绝区零 ZenlessZoneZero_Data/{StreamingAssets,Persistent}/Video/HD/…

扫描去重规则：同一"视频相对路径"在基线（StreamingAssets）与热更（Persistent）
各有一份时，热更优先；来源相同则取较大文件。热更副本才是游戏当前实际使用的
内容（其 nonce / key 均可能与基线不同）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: @SFA chno → ISO 639-2 语言标签（与游戏内音轨顺序一致，导出时写入 language 元数据）
AUDIO_LANGS: dict[int, str] = {0: "zho", 1: "eng", 2: "jpn", 3: "kor"}


@dataclass(frozen=True)
class GameProfile:
    id: str                          # CLI 用短名：gi / hsr / zzz
    codename: str                    # 生态内部代号：hk4e / hkrpg / nap
    title: str
    key_file: str
    history_file: str | None = None
    versions_file: str | None = None
    by_path_file: str | None = None
    #: 基线目录（game-root 相对，/ 分隔，递归扫描 *.usm）
    baseline_dirs: tuple[str, ...] = ()
    #: 热更目录（优先于基线）
    hotfix_dirs: tuple[str, ...] = ()
    #: 由游戏内相对路径生成 by_path 候选键时要剥离的前缀
    by_path_prefixes: tuple[str, ...] = ()
    audio_langs: dict[int, str] | None = None

    @property
    def has_audio(self) -> bool:
        return self.audio_langs is not None


GAMES: dict[str, GameProfile] = {
    "gi": GameProfile(
        id="gi",
        codename="hk4e",
        title="原神",
        key_file="hk4e_keys.json",
        history_file="hk4e_history.json",
        baseline_dirs=("YuanShen_Data/StreamingAssets/VideoAssets",),
        hotfix_dirs=("YuanShen_Data/Persistent/VideoAssets",),
        audio_langs=AUDIO_LANGS,
    ),
    "hsr": GameProfile(
        id="hsr",
        codename="hkrpg",
        title="星穹铁道",
        key_file="hkrpg_keys.json",
        history_file="hkrpg_history.json",
        versions_file="hkrpg_keys_versions.json",
        baseline_dirs=("StarRail_Data/StreamingAssets/Video/Windows",),
        hotfix_dirs=("StarRail_Data/Persistent/Video/Windows",),
        audio_langs=AUDIO_LANGS,
    ),
    "zzz": GameProfile(
        id="zzz",
        codename="nap",
        title="绝区零",
        key_file="nap_keys.json",
        history_file="nap_history.json",
        by_path_file="nap_keys_by_path.json",
        baseline_dirs=("ZenlessZoneZero_Data/StreamingAssets/Video/HD",),
        hotfix_dirs=("ZenlessZoneZero_Data/Persistent/Video/HD",),
        by_path_prefixes=(
            "ZenlessZoneZero_Data/StreamingAssets/Video/HD/",
            "ZenlessZoneZero_Data/Persistent/Video/HD/",
        ),
        audio_langs=None,   # 绝区零 USM 无 @SFA 音频块，永远纯视频导出
    ),
}

#: 代号别名（hk4e/hkrpg/nap 也能当 --game 用）
ALIASES = {"hk4e": "gi", "hkrpg": "hsr", "nap": "zzz",
           "genshin": "gi", "starrail": "hsr", "zenless": "zzz"}


def resolve_game(name: str) -> GameProfile:
    key = name.strip().lower()
    key = ALIASES.get(key, key)
    if key not in GAMES:
        raise KeyError(f"未知游戏 {name!r}，可选：gi / hsr / zzz")
    return GAMES[key]


@dataclass
class ScannedFile:
    """扫描到的单个 USM（已按规则去重）。"""

    rel_video: str     # 相对视频根目录的路径（/ 分隔，含 .usm）—— 去重主键
    rel_root: str      # 相对游戏根目录的完整路径（/ 分隔）—— history/by_path 查询用
    path: Path         # 绝对路径
    source: str        # "baseline" | "hotfix"
    size: int

    @property
    def name(self) -> str:
        return Path(self.rel_video).stem


def _rank(f: ScannedFile) -> tuple[int, int]:
    return (1 if f.source == "hotfix" else 0, f.size)


def scan(root: Path, profile: GameProfile) -> dict[str, ScannedFile]:
    """递归扫描游戏目录下全部 .usm，按"热更优先、其次更大"去重。

    返回 {视频相对路径: ScannedFile}。root 可为 None 交给 resolve_root。
    """
    out: dict[str, ScannedFile] = {}
    for source, dirs in (("baseline", profile.baseline_dirs), ("hotfix", profile.hotfix_dirs)):
        for d in dirs:
            base = root / Path(d)
            if not base.is_dir():
                continue
            for p in base.rglob("*.usm"):
                if not p.is_file():
                    continue
                rel = p.relative_to(base).as_posix()
                cand = ScannedFile(
                    rel_video=rel,
                    rel_root=(Path(d).as_posix() + "/" + rel),
                    path=p,
                    source=source,
                    size=p.stat().st_size,
                )
                prev = out.get(rel)
                if prev is None or _rank(cand) > _rank(prev):
                    out[rel] = cand
    return out


def resolve_root(profile: GameProfile, override: str | None = None,
                 config_roots: dict[str, str] | None = None) -> Path | None:
    """解析游戏根目录：显式覆盖 > 配置文件 > 环境变量 > 检测（注册表快查 + 后台缓存）。

    检测为非阻塞设计：注册表快查同步执行；盘符全量扫描由 detect 后台线程
    承担（GUI 启动即开跑），未完成时返回 None，由上层提示手动选择或稍后重试。
    """
    if override:
        p = Path(override)
        return p if p.is_dir() else None
    if config_roots:
        val = config_roots.get(profile.id)
        if val and Path(val).is_dir():
            return Path(val)
    env = {"gi": "HOYO_USM_GI_ROOT", "hsr": "HOYO_USM_HSR_ROOT", "zzz": "HOYO_USM_ZZZ_ROOT"}
    val = os.environ.get(env[profile.id])
    if val and Path(val).is_dir():
        return Path(val)
    from . import detect
    fast = detect.fast_game_roots().get(profile.id)
    if fast:
        return Path(fast)
    detect.start_background_scan()
    cached = detect.cached_game_roots()
    if cached["done"] and cached["result"]:
        found = cached["result"].get(profile.id)
        return Path(found) if found else None
    return None
