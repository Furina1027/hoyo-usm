"""ADX 流重建：加密判定、(c)CRI 版权串补丁。

实测结论（以真实文件字节证据为准，修正了上游文档的两处说法）：
  * ADX 头 288B，帧数据从 0x120 起，帧头是**单字节** 0x00 同步
    （每帧 18B，实测密文区帧首解密后 00 占 91.7%）。
  * "(c)CRI" 版权串位置固定在 0x11A；头内 0x02 字段值（miHoYo 写 0x11C）
    保持原样即可被 ffmpeg/vgmstream 接受 —— 不要按"字段-4"的通用 ADX
    约定去改字段或挪串，实测反而会解析失败。
  * 加密判定用"帧首同步字节为 00 的比例"：明文流 ≈ 92%+，密文流 ≈ 7%
    （密文区帧首 = 00 ^ 掩码偶位字节）。比 scale 提取可靠得多。
"""

from __future__ import annotations

CRI_STRING = b"(c)CRI"
CRI_OFFSET = 0x11A              # 版权串固定位置（帧数据 0x120 前 6 字节）
FRAME_START = CRI_OFFSET + 6    # 0x120：帧数据起点
FRAME_SIZE_OFFSET = 0x05        # 头内 block_size 字段
DEFAULT_FRAME_SIZE = 18
PLAIN_SYNC_MIN_RATIO = 0.5      # 帧首 00 比例 ≥ 此值判明文

_MAGIC = 0x8000


def patch_cri(stream: bytes) -> tuple[bytes, bool]:
    """版权串缺失时在 0x11A 补回；返回 (流, 是否做了补丁)。

    头内 0x02 字段一律保持原值（见模块注释的实测结论）。
    """
    if len(stream) < CRI_OFFSET + 6 or stream[:2] != b"\x80\x00":
        return stream, False
    if stream[CRI_OFFSET:CRI_OFFSET + 6] == CRI_STRING:
        return stream, False
    data = bytearray(stream)
    data[CRI_OFFSET:CRI_OFFSET + 6] = CRI_STRING
    return bytes(data), True


def _frame_size(stream: bytes) -> int:
    if len(stream) > FRAME_SIZE_OFFSET and stream[FRAME_SIZE_OFFSET] >= 12:
        return stream[FRAME_SIZE_OFFSET]
    return DEFAULT_FRAME_SIZE


def plaintext_sync_ratio(stream: bytes, max_frames: int = 512) -> float | None:
    """帧首同步字节（单字节 0x00）在采样帧中的占比；无法判定返回 None。"""
    if len(stream) < FRAME_START + 4 or stream[:2] != b"\x80\x00":
        return None
    step = _frame_size(stream)
    total = ok = 0
    pos = FRAME_START
    while pos < len(stream) and total < max_frames:
        total += 1
        if stream[pos] == 0:
            ok += 1
        pos += step
    if total < 8:                   # 采样太少不足以下结论
        return None
    return ok / total


def looks_encrypted(stream: bytes) -> bool:
    """同步字判定：比例不足 → 加密；无法解析时按加密处理（宁多解不漏解）。"""
    ratio = plaintext_sync_ratio(stream)
    if ratio is None:
        return True
    return ratio < PLAIN_SYNC_MIN_RATIO
