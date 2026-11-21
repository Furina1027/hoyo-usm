"""文件/游戏识别：目录特征、basename、内容 md5 三路识别 + 直接文件目标。

CLI 与 GUI（server）共用；识别链：
  1. 游戏目录特征（路径包含某游戏的视频目录段）
  2. basename 在密钥库里命中（三库唯一）
  3. 内容 md5 在版本历史里命中（三库唯一，顺带恢复原始路径）
"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from . import games as gmod
from .export import Target
from .keys import History, KeyStore, load_key_map


def guess_game_by_dir(path: Path) -> gmod.GameProfile | None:
    """按路径里出现的游戏视频目录段识别。"""
    s = path.resolve().as_posix().replace("\\", "/").lower()
    for prof in gmod.GAMES.values():
        for d in prof.baseline_dirs + prof.hotfix_dirs:
            if d.lower() in s:
                return prof
    return None


def guess_game_by_keys(paths: list[Path], keys_dir: Path) -> gmod.GameProfile | None:
    """按文件名（basename）在三游戏密钥库里识别游戏；唯一全命中才返回。"""
    stems = {p.stem for p in paths}
    hits: list[str] = []
    for gid, prof in gmod.GAMES.items():
        try:
            key_map, _ = load_key_map(keys_dir / prof.key_file)
        except Exception:
            continue
        if stems and all(s in key_map for s in stems):
            hits.append(gid)
    if len(hits) == 1:
        return gmod.GAMES[hits[0]]
    return None


def file_md5(path: Path) -> str | None:
    """流式计算文件 md5；读取失败返回 None。"""
    h = hashlib.md5()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def guess_game_by_md5(paths: list[Path], keys_dir: Path) -> gmod.GameProfile | None:
    """按内容 md5 在三游戏版本历史里识别游戏；唯一全命中才返回。"""
    digests: list[str] = []
    for p in paths:
        d = file_md5(p)
        if d is None:
            return None
        digests.append(d)
    hits: list[str] = []
    for gid, prof in gmod.GAMES.items():
        if not prof.history_file:
            continue
        hist = History.load(keys_dir / prof.history_file)
        if digests and all(hist.paths_by_md5(d) for d in digests):
            hits.append(gid)
    if len(hits) == 1:
        return gmod.GAMES[hits[0]]
    return None


def resolve_game(prof: gmod.GameProfile | None, paths: list[Path],
                 keys_dir: Path) -> tuple[gmod.GameProfile | None, str | None]:
    """识别链：路径特征 → basename → md5。返回 (profile, 未识别原因)。"""
    if prof is not None:
        return prof, None
    if paths:
        if len(paths) == 1:
            prof = guess_game_by_dir(paths[0])
            if prof is not None:
                return prof, None
        prof = guess_game_by_keys(paths, keys_dir)
        if prof is not None:
            return prof, None
        prof = guess_game_by_md5(paths, keys_dir)
        if prof is not None:
            return prof, None
        return None, "路径特征/文件名/内容 md5 均未命中"
    return None, None


def locate_by_name(name: str) -> tuple[gmod.GameProfile, gmod.ScannedFile] | None:
    """在已配置的游戏目录里按文件名查找（裸文件名场景）。"""
    for prof in gmod.GAMES.values():
        root = gmod.resolve_root(prof)
        if root is None:
            continue
        for f in gmod.scan(root, prof).values():
            if f.name.lower() == name.lower():
                return prof, f
    return None


def direct_target(prof: gmod.GameProfile, root: Path | None, store: KeyStore,
                  path: Path, target_version: str | None) -> Target:
    """把用户直接给出的 .usm 路径包装成导出目标。

    游戏目录内的文件按相对路径查 key；目录外的文件丢失了路径信息，
    先用内容 md5 在版本历史里反查原始游戏内路径（大小预筛避免大文件
    白白哈希），恢复成功则 by_path 同名异钥覆盖表继续生效。
    """
    p = path.resolve()
    if root is not None:
        try:
            rel = p.relative_to(root)
            rel_root = rel.as_posix()
            hit = store.lookup(rel_root, target_version=target_version)
            e = hit.entry
            return Target(
                game_id=prof.id,
                rel_video=rel_root,
                path=p,
                source="hotfix" if "Persistent" in rel_root else "baseline",
                entry_method=e.method if e else None,
                entry_key_hex=e.key_hex if e else None,
                entry_audio_hex=e.audio_hex if e else None,
                via=hit.via,
                cls=None,
                size=p.stat().st_size,
            )
        except ValueError:
            pass

    # 游戏目录外：md5 → 历史库反查原始路径
    recovered: list[str] = []
    if store.history is not None:
        size = p.stat().st_size
        if size in store.history.sizes():
            digest = file_md5(p)
            if digest:
                recovered = store.history.paths_by_md5(digest)

    if recovered:
        lookups = [(rp, store.lookup(rp, target_version=target_version)) for rp in recovered]
        path_hits = [(rp, lk) for rp, lk in lookups if lk.via == "path" and lk.entry]
        if path_hits and len({lk.entry.key_hex for _, lk in path_hits}) == 1:
            rp, lk = path_hits[0]
            e = lk.entry
            return Target(
                game_id=prof.id,
                rel_video=rp,               # 用恢复出的游戏内路径命名输出
                path=p,
                source="external(md5)",
                entry_method=e.method,
                entry_key_hex=e.key_hex,
                entry_audio_hex=e.audio_hex,
                via=lk.via,
                cls=None,
                size=p.stat().st_size,
            )

    # md5 未恢复 / 多路径异 key → 按文件名兜底
    hit = store.lookup(p.as_posix(), target_version=target_version)
    e = hit.entry
    return Target(
        game_id=prof.id,
        rel_video=p.stem + ".usm",
        path=p,
        source="external",
        entry_method=e.method if e else None,
        entry_key_hex=e.key_hex if e else None,
        entry_audio_hex=e.audio_hex if e else None,
        via=hit.via,
        cls=None,
        size=p.stat().st_size,
    )
