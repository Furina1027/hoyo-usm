"""usm.py 容器解析的合成数据单元测试（不需要真实游戏文件）。"""

from __future__ import annotations

import struct
import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hoyo_usm import usm


def chunk(magic: bytes, payload: bytes, *, chno: int = 0, dtype: int = 0,
          frame_time: int = 0, frame_rate: int = 0, ext: int = 24,
          padding: int = 0, corrupt_high_bit: bool = False) -> bytes:
    """按 PLAN §5.1 规格合成一个 USM 块（csize 不含前 8 字节头）。"""
    head = bytearray(8 + ext)
    head[0:4] = magic
    if corrupt_high_bit:
        head[0:4] = bytes(b | 0x80 for b in magic)
    struct.pack_into(">I", head, 4, ext + len(payload) + padding)
    head[9] = ext
    struct.pack_into(">H", head, 10, padding)
    head[12] = chno
    head[15] = dtype & 0x3
    struct.pack_into(">I", head, 16, frame_time)
    struct.pack_into(">I", head, 20, frame_rate)
    return bytes(head) + payload + b"\x00" * padding


IVF_HEADER = (
    b"DKIF" + struct.pack("<HH", 0, 32) + b"VP90"
    + struct.pack("<HH", 1920, 1080) + struct.pack("<III", 30, 1, 57)
    + b"\x00" * 4
)


class TestParse(unittest.TestCase):
    def test_basic_parse(self):
        crid = chunk(b"CRID", b"\x00" * 16, dtype=1)
        v0 = chunk(b"@SFV", IVF_HEADER + b"frame0", frame_time=100, frame_rate=30)
        v1 = chunk(b"@SFV", b"frame1data", frame_time=133)
        meta = chunk(b"@SFV", b"@UTF" + b"\x00" * 64)          # VIDEO_HDRINFO 元数据表
        a0 = chunk(b"@SFA", b"audio000", chno=0)
        data = crid + v0 + meta + v1 + a0

        res = usm.parse_blocks(data)
        self.assertFalse(res.truncated)
        self.assertIsNone(res.error)
        self.assertEqual(len(res.blocks), 5)
        self.assertEqual(res.blocks[0].kind, b"CRID")
        self.assertEqual(res.blocks[1].payload, IVF_HEADER + b"frame0")
        self.assertEqual(res.blocks[1].frame_time, 100)
        self.assertEqual(res.blocks[2].is_meta, True)
        self.assertEqual(res.blocks[3].frame_time, 133)

        self.assertEqual(len(usm.video_blocks(res.blocks)), 2)   # meta 块被排除
        self.assertEqual(usm.read_nonce(data), None)

    def test_high_bit_magic(self):
        """magic 最高位混淆后判别结果不变。"""
        data = chunk(b"@SFV", b"x" * 10, corrupt_high_bit=True)
        res = usm.parse_blocks(data)
        self.assertEqual(res.blocks[0].kind, b"@SFV")
        self.assertEqual(len(usm.video_blocks(res.blocks)), 1)
        self.assertNotIn(b"@SFV", res.unknown_magics)

    def test_truncated_tail(self):
        data = chunk(b"@SFV", b"x" * 10)
        res = usm.parse_blocks(data[: len(data) - 5])
        self.assertTrue(res.truncated)
        self.assertIn("越界", res.error or "")

    def test_bad_csize(self):
        bad = b"@SFV" + struct.pack(">I", 3) + b"\x00" * 3
        res = usm.parse_blocks(bad)
        self.assertTrue(res.truncated)

    def test_stop_offset(self):
        data = chunk(b"@SFV", b"a" * 10) + chunk(b"@SFV", b"b" * 10)
        res = usm.parse_blocks(data + b"garbage!!!")
        self.assertTrue(res.truncated)
        self.assertEqual(res.blocks[0].payload, b"a" * 10)


class TestNonce(unittest.TestCase):
    def test_nonce_before_marker(self):
        marker = b"<NULL>\x00VIDEO_HDRINFO"
        nonce = bytes(range(8))
        data = b"\x00" * 64 + nonce + marker + b"\x00" * 32
        self.assertEqual(usm.read_nonce(data), nonce)

    def test_nonce_missing(self):
        self.assertIsNone(usm.read_nonce(b"\x00" * 128))
        self.assertIsNone(usm.read_nonce(b""))


class TestAudioStreams(unittest.TestCase):
    def test_grouping_by_chno(self):
        # HCA 头块前 3 字节混淆（HCA\0 → C8 C3 C1 00）
        hca_head = bytes([0xC8, 0xC3, 0xC1, 0x00]) + b"\x00" * 92
        adx_head = b"\x80\x00" + b"\x00" * 286
        data = (
            chunk(b"@SFA", hca_head, chno=0)
            + chunk(b"@SFA", hca_head[0:16], chno=0)
            + chunk(b"@SFA", adx_head, chno=1)
        )
        streams = usm.audio_streams(usm.parse_blocks(data).blocks)
        self.assertEqual([s.chno for s in streams], [0, 1])
        self.assertEqual(streams[0].codec, "HCA")
        self.assertEqual(streams[0].block_count, 2)
        self.assertEqual(streams[1].codec, "ADX")

    def test_keep_data_concat(self):
        data = chunk(b"@SFA", b"AAAABBBB", chno=2) + chunk(b"@SFA", b"CCCCDDDD", chno=2)
        s = usm.audio_streams(usm.parse_blocks(data).blocks)[0]
        self.assertEqual(s.data, b"AAAABBBBCCCCDDDD")
        self.assertEqual(s.chunks, [b"AAAABBBB", b"CCCCDDDD"])


class TestIvf(unittest.TestCase):
    def test_ivf_info(self):
        info = usm.ivf_info(IVF_HEADER)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.fourcc, "VP90")
        self.assertEqual((info.width, info.height), (1920, 1080))
        self.assertEqual((info.rate, info.scale), (30, 1))
        self.assertEqual(info.frame_count, 57)
        self.assertIsNone(usm.ivf_info(b"\x00" * 64))

    def test_looks_like(self):
        self.assertTrue(usm.looks_like_ivf(IVF_HEADER))
        self.assertTrue(usm.looks_like_h264(b"\x00\x00\x00\x01\x67"))
        self.assertTrue(usm.looks_like_mpeg1(b"\x00\x00\x01\xb3"))


if __name__ == "__main__":
    unittest.main()
