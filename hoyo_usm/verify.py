"""导出验收：ffmpeg 全量零错误解码 + 帧数对账。

判据纪律（三仓踩坑共识，失败必须可见）：
  * 成功 = ffmpeg `-v error -i X -map 0 -f null -` 返回 0 **且 stderr 为空**。
    ffprobe / 解码器"能出帧"都有错误掩盖误报，只能当快筛。
  * 禁止 `-frames:v N` 早停（吞掉末帧错误）。
  * 头部魔数（DKIF/H264 起始码）在前 0x40 明文区，错钥恒通过 —— 只可当警告。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .audio.pcm import FfmpegError


def ffmpeg_full_decode_ok(ffmpeg: str, path: Path, *, timeout: int = 900,
                          ignore_dts_quirk: bool = False) -> tuple[bool, str]:
    """全量解码校验：返回 (是否通过, 错误摘要)。

    ignore_dts_quirk：MPEG-1 源流固有 B 帧时间基准重复（"non monotonically
    increasing dts"），属容器级时间戳噪声而非解码错误 —— 仅在 mpeg1 类产物
    上容忍这类行，其余解码错误仍严格拦截。
    """
    cmd = [ffmpeg, "-v", "error", "-i", str(path), "-map", "0", "-f", "null", "-"]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              creationflags=flags)
    except FileNotFoundError as exc:
        raise FfmpegError(f"找不到 ffmpeg（{ffmpeg}）：{exc}") from exc
    except subprocess.TimeoutExpired:
        return False, "ffmpeg 全量解码超时"
    err = proc.stderr.decode("utf-8", "replace").strip()
    if ignore_dts_quirk:
        kept = [ln for ln in err.splitlines() if "non monotonically increasing dts" not in ln]
        err = "\n".join(kept).strip()
    if proc.returncode == 0 and not err:
        return True, ""
    return False, (err[:400] or f"returncode={proc.returncode}")


def ivf_frames_match(ivf_declared: int, actual_blocks: int) -> bool:
    """IVF 头声明帧数 == 实际视频块数（错钥/截断的强信号）。"""
    return ivf_declared == actual_blocks
