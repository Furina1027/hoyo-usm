"""probe 逻辑（CLI 与 GUI 共用）：只读解析 + 密钥形态 + 将走的管线。

从 cli 抽取；返回结构化 dict（即 CLI --json 的内容）。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import games as gmod
from . import usm
from .config import bundled_keys_dir
from .identify import resolve_game
from .keys import KeyStore


def probe_file(path: Path, *, game: str | None = None,
               keys_dir: Path | None = None,
               config_roots: dict[str, str] | None = None) -> dict:
    keys_dir = Path(keys_dir) if keys_dir else bundled_keys_dir()
    prof: gmod.GameProfile | None = gmod.resolve_game(game) if game else None
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))

    if prof is None:
        prof, reason = resolve_game(prof, [path], keys_dir)
        if prof is None:
            return {"file": str(path), "error": f"无法识别所属游戏：{reason}"}

    data = path.read_bytes()
    res = usm.parse_blocks(data)
    vbs = usm.video_blocks(res.blocks)
    streams = usm.audio_streams(res.blocks)
    head = vbs[0].payload if vbs else b""
    ivf = usm.ivf_info(head)
    nonce = usm.read_nonce(data)

    if ivf:
        video_kind = "vp9"
        desc = f"IVF {ivf.fourcc} {ivf.width}x{ivf.height} rate={ivf.rate}/{ivf.scale} 声明帧数={ivf.frame_count}"
    elif usm.looks_like_mpeg1(head):
        video_kind = "mpeg1"
        desc = "MPEG-1"
    elif usm.looks_like_h264(head):
        video_kind = "h264"
        desc = "H.264 Annex-B"
    else:
        video_kind = "unknown"
        desc = "无法识别（可能缺密钥/损坏）"

    store = KeyStore(keys_dir, key_file=prof.key_file, history_file=prof.history_file,
                     versions_file=prof.versions_file, by_path_file=prof.by_path_file,
                     by_path_prefixes=prof.by_path_prefixes)
    hit = store.lookup(_lookup_key(path, config_roots, prof))
    entry = hit.entry

    warnings: list[str] = []
    if res.truncated:
        warnings.append(f"文件截断/损坏：{res.error} —— 禁止导出残缺视频")
    if ivf and ivf.frame_count != len(vbs):
        warnings.append(f"帧数对账失败：声明 {ivf.frame_count} ≠ 实际块 {len(vbs)}（错钥/截断的典型信号）")
    if entry is None:
        if hit.via == "versions":
            warnings.append("同名文件存在多版本密钥归档，但目标版本未指定/未命中")
        else:
            warnings.append("密钥库整库未命中（mask/aes/plain 均无）")
    if entry is not None and entry.method == "aes" and nonce is None:
        warnings.append("aes 条目但文件内未找到 VIDEO_HDRINFO nonce，无法解密")
    if entry is not None and entry.method == "aes" and prof.has_audio and streams and not entry.audio_hex:
        warnings.append("aes 条目缺 audio key：解密可行，但音轨将按缺 key 跳过")
    if streams and not prof.has_audio:
        warnings.append("该游戏 profile 认为无音轨，但文件里发现 @SFA 块（请反馈）")

    magic_hist: dict[str, int] = {}
    for b in res.blocks:
        k = b.kind.decode("ascii", "replace")
        magic_hist[k] = magic_hist.get(k, 0) + 1

    multi_audio = len(streams) > 1 and prof.has_audio
    if video_kind == "vp9" and multi_audio:
        container = "MKV(-c:v copy)（多音轨）"
    else:
        container = {"vp9": "WebM(-c:v copy)", "h264": "MP4(-c:v copy)",
                     "mpeg1": "MKV(-c copy)", "unknown": "容器待定"}[video_kind]
    if entry is None:
        method_text = "缺密钥"
    elif entry.method == "plain":
        method_text = "明文"
    else:
        method_text = entry.method
    if not streams or not prof.has_audio:
        audio_text = "无音轨"
    else:
        audio_text = f"音轨×{len(streams)}[{'/'.join(s.codec for s in streams)}]（四轨/单轨可选）"
    pipeline = f"{method_text} → {container} ｜ {audio_text}"

    return {
        "file": str(path),
        "size": len(data),
        "game": prof.id,
        "game_title": prof.title,
        "codename": prof.codename,
        "blocks": len(res.blocks),
        "magic_hist": magic_hist,
        "truncated": res.truncated,
        "unknown_magics": {k.decode("ascii", "replace"): v for k, v in res.unknown_magics.items()},
        "video": {"blocks": len(vbs), "kind": video_kind, "desc": desc,
                  "ivf": ivf.__dict__ | {"declared_vs_actual": [ivf.frame_count, len(vbs)]} if ivf else None},
        "nonce": nonce.hex() if nonce else None,
        "audio": [{"chno": s.chno, "codec": s.codec, "blocks": s.block_count,
                   "lang": (prof.audio_langs or {}).get(s.chno)} for s in streams],
        "key": None if entry is None else {"method": entry.method, "audio": entry.audio_hex,
                                           "via": hit.via, "matched": hit.matched},
        "pipeline": pipeline,
        "warnings": warnings,
    }


def _lookup_key(path: Path, config_roots: dict[str, str] | None, prof: gmod.GameProfile) -> str:
    """构造密钥查询用的相对路径：游戏目录内 → 相对路径；否则绝对路径
    （by_path 前缀在绝对路径上同样可命中，basename 由 KeyStore 兜底）。"""
    if config_roots:
        root = config_roots.get(prof.id)
        if root and path.is_relative_to(Path(root)):
            return path.relative_to(Path(root)).as_posix()
    return path.as_posix()
