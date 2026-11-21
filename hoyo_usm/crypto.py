"""解密原语：反馈 XOR 掩码（旧代）与 AES-128-CTR（method2）。

实现依据：项目计划 PLAN §5.2 的格式规格（掩码派生表与解密循环来自
GI-cutscenes README §3.3/§4 的文字描述，音频掩码来自 §五；clean-room：
只依据规格描述实现，未参考任何实现源码）。

掩码体系要点（三家游戏通用）：
  * 加密区 = 每块载荷的 [0x40:]；前 0x40 字节恒为明文。
  * 载荷加密区长度（len(payload)-0x40）< 0x200 的块整个原样 —— 游戏根本
    不解这类小块，解了反而错。
  * 区域1 = 载荷 [0x140:]，用 mask2 解密，掩码状态随已解密字节逐字节反馈；
  * 区域2 = 载荷 [0x40:0x140)，用 mask1 解密，掩码状态由区域1 前段明文
    按位置累积反馈。每块独立解密（掩码状态不跨块）。
  * AES 体系没有小块豁免：所有视频数据块（含小块）都要解。

音频掩码（USM 层，旧代 @SFA）与视频掩码同源（mask1）但派生方式不同：
奇数位固定常量、偶数位 = mask1[i]^0xFF，32 字节循环、无反馈。
"""

from __future__ import annotations

import struct

import numpy as np

BLOCK_PLAIN_PREFIX = 0x40       # 载荷前 0x40 字节恒明文
REGION1_START = 0x140           # 载荷坐标：区域1 起点（区域2 = [0x40, 0x140)）
MIN_ENCRYPTED_SIZE = 0x200      # 加密区（len-0x40）低于此值整块明文

_AUDIO_MASK_CONST = b"URUC"     # 音频掩码奇数位固定常量


# ---------------------------------------------------------------------------
# 掩码派生
# ---------------------------------------------------------------------------

def build_masks(final_key: int) -> tuple[bytes, bytes]:
    """56 位成品 finalKey → (mask1, mask2)。

    输入是密钥库里"16位HEX"条目的整数值（已是成品 finalKey，不做文件名
    哈希等二次派生）。key 按小端拆 8 字节：key1 = 低 4 字节，key2 = 高 4 字节
    （56 位 key 的最高字节恒为 0，且它不参与视频掩码）。mask2 = mask1 ^ 0xFF。
    """
    kb = (final_key & 0xFFFFFFFFFFFFFF).to_bytes(8, "little")
    key1 = kb[0:4]
    key2 = kb[4:8]
    m = bytearray(32)

    def u8(x: int) -> int:
        return x & 0xFF

    # 前 8 项：key 字节的仿射变换（key1[0..3] + key2[0..2]）
    m[0x00] = key1[0]
    m[0x01] = key1[1]
    m[0x02] = key1[2]
    m[0x03] = u8(key1[3] - 0x34)
    m[0x04] = u8(key2[0] + 0xF9)
    m[0x05] = u8(key2[1] ^ 0x13)
    m[0x06] = u8(key2[2] + 0x61)
    # 后 24 项：由已派生的 m[0..6] 确定性展开（顺序依赖）
    m[0x07] = m[0x00] ^ 0xFF
    m[0x08] = u8(m[0x02] + m[0x01])
    m[0x09] = u8(m[0x01] - m[0x07])
    m[0x0A] = m[0x02] ^ 0xFF
    m[0x0B] = m[0x01] ^ 0xFF
    m[0x0C] = u8(m[0x0B] + m[0x09])
    m[0x0D] = u8(m[0x08] - m[0x03])
    m[0x0E] = m[0x0D] ^ 0xFF
    m[0x0F] = u8(m[0x0A] - m[0x0B])
    m[0x10] = u8(m[0x08] - m[0x0F])
    m[0x11] = m[0x10] ^ m[0x07]
    m[0x12] = m[0x0F] ^ 0xFF
    m[0x13] = m[0x03] ^ 0x10
    m[0x14] = u8(m[0x04] - 0x32)
    m[0x15] = u8(m[0x05] + 0xED)
    m[0x16] = m[0x06] ^ 0xF3
    m[0x17] = u8(m[0x13] - m[0x0F])
    m[0x18] = u8(m[0x15] + m[0x07])
    m[0x19] = u8(0x21 - m[0x13])
    m[0x1A] = m[0x14] ^ m[0x17]
    m[0x1B] = u8(m[0x16] + m[0x16])
    m[0x1C] = u8(m[0x17] + 0x44)
    m[0x1D] = u8(m[0x03] + m[0x04])
    m[0x1E] = u8(m[0x05] - m[0x16])
    m[0x1F] = m[0x1D] ^ m[0x13]

    mask1 = bytes(m)
    mask2 = bytes(x ^ 0xFF for x in m)
    return mask1, mask2


def build_audio_mask(mask1: bytes) -> bytes:
    """USM 层音频掩码：偶数位 = mask1[i]^0xFF，奇数位 = 固定常量按 (i>>1)&3 轮换。"""
    out = bytearray(32)
    for i in range(32):
        if i & 1:
            out[i] = _AUDIO_MASK_CONST[(i >> 1) & 3]
        else:
            out[i] = mask1[i] ^ 0xFF
    return bytes(out)


# ---------------------------------------------------------------------------
# 掩码解密（单块）
# ---------------------------------------------------------------------------

def decrypt_block_mask_reference(payload: bytes, mask1: bytes, mask2: bytes) -> bytes:
    """逐字节参考实现（与规格逐行对应，正确性基准；性能差仅用于对拍）。"""
    data = bytearray(payload)
    size = len(data) - BLOCK_PLAIN_PREFIX
    if size < MIN_ENCRYPTED_SIZE:
        return bytes(data)

    # 第一轮：区域1 = 载荷 [0x140:]，mask2，逐字节反馈
    mask = bytearray(mask2)
    for i in range(0x100, size):
        p = i & 0x1F
        data[0x40 + i] ^= mask[p]
        mask[p] = data[0x40 + i] ^ mask2[p]

    # 第二轮：区域2 = 载荷 [0x40:0x140)，mask1，区域1 明文按位置累积反馈
    mask = bytearray(mask1)
    for i in range(0x100):
        p = i & 0x1F
        mask[p] ^= data[REGION1_START + i]
        data[0x40 + i] ^= mask[p]
    return bytes(data)


def _decrypt_region1(data: bytearray, mask2: bytes) -> np.ndarray:
    """区域1（载荷 [0x140:]）闭式解。

    对同一掩码位置 p 的第 k 次出现（密文 d_k）：
        out_k = (d_1 ^ ... ^ d_k) ^ (mask2[p] 若 k 为奇数)
    推导：首字节 out_1 = d_1 ^ mask2[p]，反馈后掩码状态变为 d_1，
    out_2 = d_2 ^ d_1，再次反馈恢复 mask2 … 奇偶交替。
    （注意：规格文档 §4.1 的奇偶表述与此相反，以逐字节参考实现为准，
    两者已在单元测试中对拍一致。）
    """
    size = len(data) - BLOCK_PLAIN_PREFIX
    r1 = np.frombuffer(data, dtype=np.uint8, count=size - 0x100, offset=REGION1_START)
    k_rows = (r1.size + 31) // 32
    padded = np.zeros(k_rows * 32, dtype=np.uint8)
    padded[: r1.size] = r1
    mat = padded.reshape(k_rows, 32)
    cum = np.bitwise_xor.accumulate(mat, axis=0)
    parity = np.zeros(k_rows, dtype=np.uint8)
    parity[0::2] = 1                       # 0-based 偶数行 == 第奇数次出现
    out = cum ^ (parity[:, None] * np.frombuffer(mask2, dtype=np.uint8))
    return out.reshape(-1)[: r1.size]


def decrypt_block_mask(payload: bytes, mask1: bytes, mask2: bytes) -> bytes:
    """numpy 向量化版单块解密（与 decrypt_block_mask_reference 等价）。"""
    size = len(payload) - BLOCK_PLAIN_PREFIX
    if size < MIN_ENCRYPTED_SIZE:
        return payload
    data = bytearray(payload)
    r1 = _decrypt_region1(data, mask2)
    data[REGION1_START:] = r1.tobytes()

    # 区域2：掩码状态 = mask1[p] ^ 累积异或(区域1 明文在该位置的前 j 次出现)
    r2 = np.frombuffer(data, dtype=np.uint8, count=0x100, offset=BLOCK_PLAIN_PREFIX)
    fb_src = np.frombuffer(bytes(r1[:0x100]), dtype=np.uint8).reshape(8, 32)
    cum = np.bitwise_xor.accumulate(fb_src, axis=0)
    maskstate = cum ^ np.frombuffer(mask1, dtype=np.uint8)
    out2 = r2.reshape(8, 32) ^ maskstate
    data[0x40:0x140] = out2.reshape(-1).tobytes()
    return bytes(data)


def decrypt_video_mask(blocks, final_key: int) -> bytes:
    """拼接 @SFV 帧块并逐块掩码解密，返回完整基本流（VP9→IVF / H264→Annex-B）。"""
    mask1, mask2 = build_masks(final_key)
    out = bytearray()
    for b in blocks:
        if b.dtype != 0 or b.is_meta:
            continue
        out += decrypt_block_mask(b.payload, mask1, mask2)
    return bytes(out)


# ---------------------------------------------------------------------------
# AES-128-CTR（method2）
# ---------------------------------------------------------------------------

def decrypt_video_aes(blocks, key: bytes, nonce: bytes) -> bytes:
    """拼接 @SFV 帧块并逐块 AES-128-CTR 解密。

    计数器 = nonce(8B) ‖ BE32(块头 frame_time) ‖ 00000000，每块独立实例。
    加密区为载荷 [0x40:]（无小块豁免，小块也必须解）。
    """
    from Crypto.Cipher import AES  # 延迟导入：仅 aes 条目需要 pycryptodome

    if len(key) != 16:
        raise ValueError(f"AES key 长度应为 16 字节，得到 {len(key)}")
    if len(nonce) != 8:
        raise ValueError(f"nonce 长度应为 8 字节，得到 {len(nonce)}")
    out = bytearray()
    for b in blocks:
        if b.dtype != 0 or b.is_meta:
            continue
        counter = nonce + struct.pack(">I", b.frame_time) + b"\x00" * 4
        cipher = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=counter)
        out += b.payload[:BLOCK_PLAIN_PREFIX]
        out += cipher.decrypt(b.payload[BLOCK_PLAIN_PREFIX:])
    return bytes(out)


# ---------------------------------------------------------------------------
# USM 层音频解密（旧代 @SFA）
# ---------------------------------------------------------------------------

def decrypt_audio_chunk(payload: bytes, audio_mask: bytes) -> bytes:
    """对单个 @SFA 数据块载荷应用 USM 层音频掩码（无反馈，32 字节循环）。

    加密区从载荷 0x140 起（头块 96B/288B 均小于 0x140，天然整块明文）；
    掩码相位取载荷绝对偏移 & 0x1F（0x140 ≡ 0 mod 32，故与相对偏移一致）。
    """
    n = len(payload)
    if n <= REGION1_START:
        return payload
    data = bytearray(payload)
    idx = np.arange(REGION1_START, n) & 0x1F
    am = np.frombuffer(audio_mask, dtype=np.uint8)
    data[REGION1_START:] = (
        np.frombuffer(data, dtype=np.uint8, count=n - REGION1_START, offset=REGION1_START)
        ^ am[idx]
    ).tobytes()
    return bytes(data)
