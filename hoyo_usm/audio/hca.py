"""HCA 解码（cricodecs 封装）与头信息读取。

cricodecs 的 decode(keycode) 对"ciph=56 + keycode 错误"会**静默**产出另一种
PCM（样本数完全相同）——keycode 来源的正确性由上层保证：
  * mask 条目 → keycode = finalKey（低 56 位；三家通用规则，GI 侧实测四轨全解）
  * aes 条目  → keycode = 密钥条目 audio 字段；缺失则上层直接跳过该轨
  * plain 条目 → keycode = 0（未加密流）
"""

from __future__ import annotations

from dataclasses import dataclass

import cricodecs.hca as cri_hca

#: 标准 HCA 每帧采样数
SAMPLES_PER_FRAME = 1024


@dataclass(frozen=True)
class HcaMeta:
    channels: int
    sample_rate: int
    frame_count: int
    encoder_delay: int
    encoder_padding: int


def read_meta(data: bytes) -> HcaMeta | None:
    """解析 HCA 头（fmt 块）；流结构非法返回 None。"""
    try:
        hdr = cri_hca.Hca.load_bytes(data).header()
        fmt = hdr.fmt
        if fmt is None:
            return None
        return HcaMeta(
            channels=fmt.channel_count,
            sample_rate=fmt.sample_rate,
            frame_count=fmt.frame_count,
            encoder_delay=fmt.encoder_delay,
            encoder_padding=fmt.encoder_padding,
        )
    except Exception:
        return None


def decode_to_wav(data: bytes, keycode: int) -> bytes:
    """HCA → RIFF WAV bytes。结构错误抛异常；keycode 错误不报错（见模块注释）。"""
    return cri_hca.decode(data, keycode=keycode)
