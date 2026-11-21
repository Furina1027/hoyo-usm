"""CRI USM 容器统一解析（原神 / 星穹铁道 / 绝区零共用同一套布局）。

实现依据：项目计划 PLAN §5.1 的格式规格（clean-room：只依据规格描述，
不参考任何现有实现的源码）。

块头布局（每块以 8 字节公共头开始，多字节整数一律大端）：

    +0x00  4B   magic：块类型（"CRID" / "@SFV" / "@SFA" / "@CUE"）。
                部分文件的 magic 最高位被混淆，判别一律按位 & 0x7F。
    +0x04  4B   csize：本块去掉前 8 字节头之后的长度；
                下一块偏移 = 当前偏移 + 8 + csize。
    +0x08  1B   保留
    +0x09  1B   ext：扩展头总长度（从偏移 8 起算）；载荷从 8 + ext 开始。
                绝区零实测恒为 24，其他游戏"通常 0x18"，故总是从块头读取，
                不做硬编码假设。
    +0x0A  2B   padding：尾部填充字节数。
    +0x0C  1B   chno：流内通道号。视频块通常为 0；音频的多条语言轨各占一个
                chno（0..3 = zho/eng/jpn/kor）。判断流类型必须先看 magic
                再看 chno —— 视频与音频的 chno 都可能是 0。
    +0x0D  2B   保留
    +0x0F  1B   dtype：低 2 位有效；0 = 数据载荷，非 0 = 元数据 / 流头标记。
    +0x10  4B   frame_time：帧时间戳；method2（AES-CTR）计数器的组成部分。
    +0x14  4B   frame_rate。
    +0x18  ...  扩展头其余字段（本模块不解释）
    8+ext ...   载荷
    尾部        填充（padding 字节）

关键事实（实现必须遵守）：
  * 两条加密体系（掩码 / AES-CTR）的加密区都是载荷的 [0x40:]，前 0x40 字节
    恒为明文 —— 因此头部魔数探测对"错钥"恒为真，只能用作警告（见
    looks_like_ivf / looks_like_h264 的注释）。
  * method2 的 8 字节 nonce 存在文件自身的 VIDEO_HDRINFO 元数据表里，
    紧贴字符串池标记 NONCE_MARKER 之前，每个文件独立，必须现读。
  * @SFV/@SFA 载荷以 @UTF 开头的是元数据表块，不属于流数据。
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass, field

MAGIC_CRID = b"CRID"
MAGIC_VIDEO = b"@SFV"
MAGIC_AUDIO = b"@SFA"
MAGIC_CUE = b"@CUE"
META_MAGIC = b"@UTF"

#: method2 nonce 的定位标记；nonce(8B) 紧贴其前
NONCE_MARKER = b"<NULL>\x00VIDEO_HDRINFO"

#: 合法块在 8 字节头之后至少应有的长度（低于此值视为文件尾部残余/损坏）
MIN_CSIZE = 0x20

#: 扩展头长度下限：必须覆盖固定字段区（frame_time 位于块内偏移 0x10）
MIN_EXT = 0x10


def mask_magic(raw: bytes) -> bytes:
    """magic 判别用：按位 & 0x7F 去掉混淆最高位。"""
    return bytes(b & 0x7F for b in raw)


@dataclass(frozen=True)
class Block:
    """单个 USM 块。payload 已按 ext/padding 切好。"""

    offset: int          # 块在文件中的起始偏移（诊断用）
    magic: bytes         # 原始 4 字节（可能带混淆位）；判别请用 kind
    csize: int
    ext: int
    padding: int
    chno: int
    dtype: int           # 原始字节 & 0x3
    frame_time: int
    frame_rate: int
    payload: bytes

    @property
    def kind(self) -> bytes:
        return mask_magic(self.magic)

    @property
    def is_meta(self) -> bool:
        """载荷是否为 @UTF 元数据表块。"""
        return mask_magic(self.payload[:4]) == META_MAGIC

    @property
    def is_stream_data(self) -> bool:
        """是否为普通数据载荷块（dtype==0 且非元数据表）。"""
        return self.dtype == 0 and not self.is_meta


@dataclass
class ParseResult:
    blocks: list[Block]
    truncated: bool = False        # 文件被截断 / 块头损坏，解析提前终止
    error: str | None = None
    stop_offset: int | None = None  # 解析停止位置（诊断用）
    unknown_magics: Counter = field(default_factory=Counter)  # 未识别的 magic


def parse_blocks(data: bytes) -> ParseResult:
    """遍历整个 USM 文件并返回全部块。

    任何结构性异常（块尺寸非法、越界、文件中途截断）都会置 truncated=True
    并在 error 里给出人话说明 —— 上层必须把截断文件当作损坏处理，
    禁止静默导出残缺视频。
    """
    n = len(data)
    blocks: list[Block] = []
    unknown: Counter = Counter()
    pos = 0
    while pos < n:
        if pos + 8 > n:
            return ParseResult(blocks, True, f"块头不完整（偏移 {pos:#x}，仅剩 {n - pos} 字节）", pos, unknown)
        (csize,) = struct.unpack_from(">I", data, pos + 4)
        if csize < MIN_CSIZE:
            return ParseResult(blocks, True, f"块尺寸异常 csize={csize}（偏移 {pos:#x}）", pos, unknown)
        end = pos + 8 + csize
        if end > n:
            return ParseResult(blocks, True, f"块越界 csize={csize}（偏移 {pos:#x}，超出 {end - n} 字节）", pos, unknown)

        ext = data[pos + 9]
        (padding,) = struct.unpack_from(">H", data, pos + 10)
        chno = data[pos + 12]
        dtype = data[pos + 15] & 0x3
        (frame_time,) = struct.unpack_from(">I", data, pos + 16)
        (frame_rate,) = struct.unpack_from(">I", data, pos + 20)

        if ext < MIN_EXT or ext + padding > csize:
            return ParseResult(
                blocks, True,
                f"扩展头/填充异常 ext={ext} padding={padding} csize={csize}（偏移 {pos:#x}）",
                pos, unknown,
            )

        start = pos + 8 + ext
        stop = pos + 8 + csize - padding
        payload = data[start:stop] if stop > start else b""
        blk = Block(pos, data[pos:pos + 4], csize, ext, padding, chno, dtype,
                    frame_time, frame_rate, payload)
        blocks.append(blk)
        if blk.kind not in (MAGIC_CRID, MAGIC_VIDEO, MAGIC_AUDIO, MAGIC_CUE):
            unknown[blk.kind] += 1
        pos = end
    return ParseResult(blocks, False, None, None, unknown)


def read_nonce(data: bytes) -> bytes | None:
    """从 VIDEO_HDRINFO 元数据表读取 method2 的 8 字节 nonce。

    nonce 紧贴字符串池标记 NONCE_MARKER 之前。注意：必须对**实际要导出的
    那份文件**调用 —— 热更副本与基线副本的 nonce 不同，拿错文件等于错钥。
    """
    i = data.find(NONCE_MARKER)
    if i < 8:
        return None
    return data[i - 8:i]


def video_blocks(blocks: list[Block]) -> list[Block]:
    """视频流数据块：@SFV + dtype==0 + 非 @UTF 元数据表。"""
    return [b for b in blocks if b.kind == MAGIC_VIDEO and b.is_stream_data]


@dataclass
class AudioStream:
    """一条按 chno 聚合的独立音频流。

    每条 chno 是一个完整独立的音频文件流（独立容器头 + 帧序列），
    按块序拼接 chunks 即得；不同 chno 绝不能混拼。
    chunks 保留分块结构 —— USM 层音频掩码是按块从 0x140 起作用的，
    必须先按块解密再拼接。
    """

    chno: int
    codec: str           # "HCA" | "ADX" | "unknown"
    chunks: list[bytes]  # 各 @SFA 数据块的载荷（保持块序）
    block_count: int

    @property
    def data(self) -> bytes:
        return b"".join(self.chunks)


def detect_audio_codec(head: bytes) -> str:
    """按首块载荷头部判音频编码。

    HCA 头块前 4 字节被 HCA_MASK 混淆（"HCA\\0" → C8 C3 C1 xx），
    判别同样用 & 0x7F；ADX 头两字节固定 80 00。
    """
    if len(head) >= 3 and mask_magic(head[:3]) == b"HCA":
        return "HCA"
    if len(head) >= 2 and head[0] == 0x80 and head[1] == 0x00:
        return "ADX"
    return "unknown"


def audio_streams(blocks: list[Block]) -> list[AudioStream]:
    """把 @SFA 数据块按 chno 聚合成独立音频流（chno 升序）。"""
    groups: dict[int, list[Block]] = {}
    for b in blocks:
        if b.kind == MAGIC_AUDIO and b.is_stream_data:
            groups.setdefault(b.chno, []).append(b)
    out: list[AudioStream] = []
    for chno in sorted(groups):
        blks = groups[chno]
        out.append(AudioStream(chno, detect_audio_codec(blks[0].payload),
                               [b.payload for b in blks], len(blks)))
    return out


def audio_block_count(blocks: list[Block]) -> int:
    return sum(1 for b in blocks if b.kind == MAGIC_AUDIO and b.is_stream_data)


@dataclass(frozen=True)
class IvfInfo:
    fourcc: str          # "VP90" / "VP80"
    width: int
    height: int
    rate: int
    scale: int
    frame_count: int     # IVF 头声明的总帧数 —— 与实际视频块数对账用


def ivf_info(stream: bytes) -> IvfInfo | None:
    """解析 32 字节 IVF 文件头（VP9 视频流首块载荷的开头）。"""
    if len(stream) < 32 or stream[:4] != b"DKIF":
        return None
    fourcc = stream[8:12].decode("ascii", "replace")
    width, height = struct.unpack_from("<HH", stream, 12)
    rate, scale, frame_count = struct.unpack_from("<III", stream, 16)
    return IvfInfo(fourcc, width, height, rate, scale, frame_count)


def looks_like_h264(data: bytes) -> bool:
    """警告级探测：Annex-B 起始码。不可作为成功判据（前 0x40 恒明文）。"""
    return data[:4] == b"\x00\x00\x00\x01" or data[:3] == b"\x00\x00\x01"


def looks_like_mpeg1(data: bytes) -> bool:
    """警告级探测：MPEG-1 序列头。不可作为成功判据。"""
    return data[:4] == b"\x00\x00\x01\xb3"


def looks_like_ivf(data: bytes) -> bool:
    """警告级探测：DKIF + VP9/VP8 fourcc。

    注意：掩码加密保留前 0x40 明文（含整个 IVF 头），错钥时本检查恒通过；
    真正的密钥正确性判定 = IVF 声明帧数对账 + ffmpeg 全量零错误解码（M2 verify）。
    """
    if len(data) < 32 or data[:4] != b"DKIF":
        return False
    return data[8:12] in (b"VP90", b"VP80")


def concat_video(blocks: list[Block]) -> bytes:
    """把（已解密的）视频块载荷按序拼成完整基本流。

    VP9/IVF：首块载荷自带 32 字节 IVF 文件头，顺序拼接即为合法 IVF；
    H.264：Annex-B，同理。解密路径（M2）在拼接前逐块处理。
    """
    return b"".join(b.payload for b in blocks)
