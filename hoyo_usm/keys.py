"""密钥库加载与查询（自包含快照：仓库 keys/ 目录）。

快照数据来自兄弟仓库生态的人工/社区维护成果，本项目只读消费、不派生、不采集。
条目三形态（规格见 keys/PROVENANCE.md）：

    "16位HEX" 非全零        → mask   库值即成品 finalKey，直接参与掩码派生
    "0000000000000000"      → plain  明文文件
    {"aes": "32位HEX",      → aes    method2；"audio" 为 HCA keycode，
     "audio": "16位HEX"?}            缺失或全零 = 该文件音轨按缺 key 处理

查询规则（三级，命中即停）：
    1. 路径覆盖表（by_path）—— 同名异钥问题的唯一正解（如绝区零
       Transfer/HollowLoading/* 与 Yorozuya/* 同名不同内容、不同 key）
    2. basename 主库
    3. 同名多版本归档（versions）—— 同一文件名在不同游戏版本被官方
       重新下发过不同 key
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_HEX16 = re.compile(r"^[0-9a-fA-F]{16}$")
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")


@dataclass(frozen=True)
class KeyEntry:
    """归一后的密钥条目。"""

    method: str                    # "mask" | "aes" | "plain"
    key_hex: str                   # mask: 16hex；aes: 32hex；plain: 全零
    audio_hex: str | None = None   # aes 条目的音频 keycode；None = 无/未入库
    source: str = ""               # 诊断：来自哪个库文件


def normalize_entry(raw: object, source: str = "") -> KeyEntry | None:
    """把密钥库原始条目归一成 KeyEntry；非法/不完整条目返回 None（丢弃）。

    aes 条目 key 全零或长度非法视为不完整 —— 用全零 AES key 解密只会产出
    垃圾，宁可丢弃后让上层明确报"缺 key"。
    """
    if isinstance(raw, str):
        s = raw.strip()
        if not _HEX16.fullmatch(s):
            return None
        if int(s, 16) == 0:
            return KeyEntry("plain", s.lower(), None, source)
        return KeyEntry("mask", s.lower(), None, source)
    if isinstance(raw, dict):
        aes = raw.get("aes")
        if not isinstance(aes, str):
            return None
        aes = aes.strip()
        if not _HEX32.fullmatch(aes) or int(aes, 16) == 0:
            return None
        audio = raw.get("audio")
        audio_hex: str | None = None
        if isinstance(audio, str):
            audio = audio.strip()
            if _HEX16.fullmatch(audio) and int(audio, 16) != 0:
                audio_hex = audio.lower()
        return KeyEntry("aes", aes.lower(), audio_hex, source)
    return None


@dataclass(frozen=True)
class KeyStoreStats:
    total: int = 0
    mask: int = 0
    aes: int = 0
    plain: int = 0
    aes_with_audio: int = 0
    dropped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total, "mask": self.mask, "aes": self.aes,
            "plain": self.plain, "aes_with_audio": self.aes_with_audio,
            "dropped": self.dropped,
        }


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_key_map(path: Path) -> tuple[dict[str, KeyEntry], KeyStoreStats]:
    """加载 basename 主库或路径覆盖表（两种文件同构）。"""
    raw = _load_json(path)
    if isinstance(raw, dict) and isinstance(raw.get("keys"), dict):
        raw = raw["keys"]  # 兼容 nap_keys_by_path.json 的带壳写法
    if not isinstance(raw, dict):
        raise ValueError(f"密钥库格式不正确：{path}")
    out: dict[str, KeyEntry] = {}
    c = Counter()
    for k, v in raw.items():
        c["total"] += 1
        e = normalize_entry(v, source=path.name)
        if e is None:
            c["dropped"] += 1
            continue
        c[e.method] += 1
        if e.method == "aes" and e.audio_hex:
            c["aes_with_audio"] += 1
        out[str(k)] = e
    return out, KeyStoreStats(**c)


def load_by_path(path: Path) -> dict[str, KeyEntry]:
    """加载路径覆盖表（无表则空）。"""
    if not path.is_file():
        return {}
    m, _ = load_key_map(path)
    return m


def load_versions(path: Path) -> dict[str, dict[str, KeyEntry]]:
    """加载同名多版本归档：{文件名: {游戏版本: mask key hex}}。"""
    if not path.is_file():
        return {}
    raw = _load_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"多版本归档格式不正确：{path}")
    out: dict[str, dict[str, KeyEntry]] = {}
    for name, per_ver in raw.items():
        if not isinstance(per_ver, dict):
            continue
        out[str(name)] = {}
        for ver, hexkey in per_ver.items():
            e = normalize_entry(hexkey, source=path.name)
            if e is not None:
                out[str(name)][str(ver)] = e
    return out


@dataclass(frozen=True)
class HistoryEntry:
    """history 单条记录：文件名 + 状态 + 按时间正序的版本列表。

    versions[0] 是**首次出现**的版本（实测 nap_history：1.0.0 → 1.1.0 → 2.2.0，
    每次 md5 变化记一条；文件被删除时追加 DELETED 条目）。
    """

    filename: str
    state: str | None
    versions: tuple[dict, ...]     # 每项含 version/state/md5/size，时间正序


class History:
    """版本历史：支持 new / modified 分类（语义见 classify）与 md5 反查。"""

    def __init__(self, entries: dict[str, "HistoryEntry" | dict]):
        """entries 既接受 HistoryEntry 表，也接受 load 出来的原始 dict 形态。"""
        norm: dict[str, HistoryEntry] = {}
        for k, v in entries.items():
            if isinstance(v, HistoryEntry):
                norm[str(k)] = v
            elif isinstance(v, dict):
                versions = v.get("versions") or []
                norm[str(k)] = HistoryEntry(
                    filename=str(v.get("filename") or PurePosixPath(str(k)).name),
                    state=v.get("state"),
                    versions=tuple(x for x in versions if isinstance(x, dict)),
                )
        self.entries = norm
        self._md5_index: dict[str, list[str]] | None = None
        self._sizes: set[int] | None = None

    @classmethod
    def load(cls, path: Path) -> "History":
        if not path.is_file():
            return cls({})
        raw = _load_json(path)
        if not isinstance(raw, dict):
            raise ValueError(f"版本历史格式不正确：{path}")
        return cls({str(k): v for k, v in raw.items() if isinstance(v, dict)})

    def get(self, candidates: list[str]) -> HistoryEntry | None:
        """按候选键依次查找（调用方生成：完整相对路径、目录段互换等）。"""
        for c in candidates:
            e = self.entries.get(c)
            if e is not None:
                return e
        return None

    def classify(self, entry: HistoryEntry, target_version: str) -> str | None:
        """相对目标版本的归属：
        new        = 该文件首次出现于目标版本（versions[0] 即目标版本）
        modified   = 目标版本出现在后续版本里（内容被官方更新，md5 变化）
        None       = 与目标版本无关
        """
        vnums = [str(v.get("version")) for v in entry.versions]
        if not vnums:
            return None
        if vnums[0] == target_version:
            return "new"
        if target_version in vnums[1:]:
            return "modified"
        return None

    def latest_version(self) -> str | None:
        """全库中最大的版本号，作为 CLI --version 的默认值。"""
        versions = [
            str(v.get("version"))
            for e in self.entries.values() for v in e.versions
            if v.get("version") is not None
        ]
        if not versions:
            return None
        return max(versions, key=self._version_key)

    @staticmethod
    def _version_key(v: str) -> tuple:
        """版本号排序键：数字段按数值比较（1.10.0 > 1.9.0），异常段按 0。"""
        return tuple(
            int(seg) if seg.isdigit() else 0
            for seg in re.findall(r"\d+", v)
        ) or (0,)

    def md5_index(self) -> dict[str, list[str]]:
        """md5 → 出现过该内容的游戏内路径列表（懒构建，跨全部历史版本）。

        用途：游戏目录外的文件丢失了路径信息，用内容 md5 反查它原本的
        游戏内路径，从而让 by_path 同名异钥覆盖表继续生效。
        """
        if self._md5_index is None:
            idx: dict[str, list[str]] = {}
            for path, e in self.entries.items():
                for v in e.versions:
                    md5 = str(v.get("md5") or "").strip().lower()
                    if md5:
                        lst = idx.setdefault(md5, [])
                        if path not in lst:
                            lst.append(path)
            self._md5_index = idx
        return self._md5_index

    def sizes(self) -> set[int]:
        """历史库中出现过的全部文件大小（外部文件快速预筛用）。"""
        if self._sizes is None:
            self._sizes = {
                int(v["size"]) for e in self.entries.values() for v in e.versions
                if v.get("size") is not None and str(v.get("size")).isdigit()
            }
        return self._sizes

    def paths_by_md5(self, md5: str) -> list[str]:
        """按内容 md5 反查原始游戏内路径（可能多个：同内容多路径发行）。"""
        return self.md5_index().get(md5.strip().lower(), [])


@dataclass(frozen=True)
class LookupResult:
    """密钥查询结果。via=None 表示整库未命中。"""

    entry: KeyEntry | None
    via: str | None = None        # "path" | "name" | "versions"
    matched: str | None = None    # 命中的库内键（诊断）
    version: str | None = None    # versions 归档命中时的游戏版本


class KeyStore:
    """单游戏的密钥查询门面：by_path → basename → versions 三级。"""

    def __init__(self, keys_dir: Path, *, key_file: str, history_file: str | None = None,
                 versions_file: str | None = None, by_path_file: str | None = None,
                 by_path_prefixes: tuple[str, ...] = ()):
        self.keys_dir = keys_dir
        self.by_name, self.stats = load_key_map(keys_dir / key_file)
        self.by_path = load_by_path(keys_dir / by_path_file) if by_path_file else {}
        self.versions = load_versions(keys_dir / versions_file) if versions_file else {}
        self.history = History.load(keys_dir / history_file) if history_file else None
        self.by_path_prefixes = by_path_prefixes

    def path_candidates(self, rel_path: str) -> list[str]:
        """由游戏内相对路径生成 by_path 候选键（去 .usm，去视频根前缀）。

        覆盖表的键是"视频根之下的相对路径去 .usm"（如
        Transfer/HollowLoading/Zero/Dup），必须保留目录层级 —— 只按 basename
        查会命中同名异钥的另一份内容。
        """
        rel = rel_path.replace("\\", "/")
        cands: list[str] = []
        for prefix in self.by_path_prefixes:
            idx = rel.find(prefix)
            if idx >= 0:
                suffix = rel[idx + len(prefix):]
                if suffix.lower().endswith(".usm"):
                    suffix = suffix[:-4]
                cands.append(suffix)
        cands.append(PurePosixPath(rel).stem)
        # 去重保序
        seen: set[str] = set()
        return [c for c in cands if not seen.add(c)]

    def lookup(self, rel_path: str, target_version: str | None = None) -> LookupResult:
        for cand in self.path_candidates(rel_path):
            e = self.by_path.get(cand)
            if e is not None:
                return LookupResult(e, "path", cand)
        stem = PurePosixPath(rel_path.replace("\\", "/")).stem
        e = self.by_name.get(stem)
        if e is not None:
            return LookupResult(e, "name", stem)
        archive = self.versions.get(stem)
        if archive:
            if target_version and target_version in archive:
                return LookupResult(archive[target_version], "versions", stem, target_version)
            return LookupResult(None, "versions", stem, None)  # 命中归档但缺目标版本
        return LookupResult(None, None, None)

    def history_candidates(self, rel_path: str) -> list[str]:
        """history 键查找候选：原样 + StreamingAssets↔Persistent 互换
        （热更副本与基线副本在 history 里可能登记在不同目录段下）。"""
        rel = rel_path.replace("\\", "/")
        cands = [rel]
        if "/StreamingAssets/" in rel:
            cands.append(rel.replace("/StreamingAssets/", "/Persistent/", 1))
        elif "/Persistent/" in rel:
            cands.append(rel.replace("/Persistent/", "/StreamingAssets/", 1))
        return cands
