"""crypto.py / adx.py / export.resolve_mux 的单元测试（合成数据）。"""

from __future__ import annotations

import os
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hoyo_usm.audio import adx as adx_mod
from hoyo_usm import crypto
from hoyo_usm.export import resolve_mux


def make_mask_payload(encrypted_len: int) -> bytearray:
    """合成一个待解密载荷：0x40 明文前缀 + 加密区（总长 ≥ 0x240 才会触发解密）。"""
    payload = bytearray(os.urandom(0x40 + encrypted_len))
    return payload


class TestBuildMasks(unittest.TestCase):
    def test_structure(self):
        key = 0x000000000B3E3FD5
        m1, m2 = crypto.build_masks(key)
        self.assertEqual(len(m1), 32)
        self.assertEqual(bytes(a ^ 0xFF for a in m1), m2)
        # key 按小端展开：mask1[0..2] = key 低 3 字节
        kb = key.to_bytes(8, "little")
        self.assertEqual(m1[0], kb[0])
        self.assertEqual(m1[1], kb[1])
        self.assertEqual(m1[2], kb[2])
        self.assertEqual(m1[3], (kb[3] - 0x34) & 0xFF)
        self.assertEqual(m1[4], (kb[4] + 0xF9) & 0xFF)
        self.assertEqual(m1[5], kb[5] ^ 0x13)
        self.assertEqual(m1[6], (kb[6] + 0x61) & 0xFF)
        # 第 8 个 key 字节（56 位 key 恒为 0）不参与掩码
        self.assertNotEqual(m1[7], 0)

    def test_deterministic(self):
        self.assertEqual(crypto.build_masks(0x1234), crypto.build_masks(0x1234))
        self.assertNotEqual(crypto.build_masks(0x1234), crypto.build_masks(0x1235))


class TestMaskDecrypt(unittest.TestCase):
    def test_reference_matches_numpy(self):
        """逐字节参考实现与 numpy 闭式解在随机数据上必须逐位一致。"""
        for trial in range(30):
            key = int.from_bytes(os.urandom(7), "little")
            m1, m2 = crypto.build_masks(key)
            enc_len = 0x200 + 0x30 * (trial % 7) + (trial * 13) % 31
            payload = bytes(make_mask_payload(enc_len))
            ref = crypto.decrypt_block_mask_reference(payload, m1, m2)
            fast = crypto.decrypt_block_mask(payload, m1, m2)
            self.assertEqual(ref, fast, f"trial={trial} key={key:#x} len={len(payload)}")

    def test_small_block_passthrough(self):
        """加密区 < 0x200 的块整个原样返回（游戏不解小块）。"""
        m1, m2 = crypto.build_masks(0xABCDEF)
        payload = bytes(make_mask_payload(0x1FF))
        self.assertEqual(crypto.decrypt_block_mask(payload, m1, m2), payload)
        self.assertEqual(crypto.decrypt_block_mask_reference(payload, m1, m2), payload)
        # 恰好 0x200：必须解密（且与参考实现一致）
        payload = bytes(make_mask_payload(0x200))
        self.assertEqual(crypto.decrypt_block_mask(payload, m1, m2),
                         crypto.decrypt_block_mask_reference(payload, m1, m2))

    def test_region_coverage(self):
        """解密必须覆盖 [0x40, 末尾) 的全部字节：改动区域1/区域2 任何密文字节
        都会改变对应输出。"""
        key = 0x01020304050607
        m1, m2 = crypto.build_masks(key)
        payload = bytearray(make_mask_payload(0x400))
        out1 = crypto.decrypt_block_mask(bytes(payload), m1, m2)
        for pos in (0x40, 0x3F + 0x100, 0x200, len(payload) - 1):
            mutated = bytearray(payload)
            mutated[pos] ^= 0x01
            out2 = crypto.decrypt_block_mask(bytes(mutated), m1, m2)
            self.assertNotEqual(out1, out2, f"payload[{pos:#x}] 的扰动未影响输出")


class _FakeBlock:
    """最小 Block 替身。"""

    def __init__(self, payload, frame_time):
        self.dtype = 0
        self.is_meta = False
        self.frame_time = frame_time
        self.payload = payload


class TestAesDecrypt(unittest.TestCase):
    def test_roundtrip(self):
        """用同一 CTR 参数加密合成流，解密必须逐位还原。"""
        from Crypto.Cipher import AES
        key = os.urandom(16)
        nonce = os.urandom(8)
        frame_time = 0x1234
        plain_body = os.urandom(0x300)
        counter = nonce + struct.pack(">I", frame_time) + b"\x00" * 4
        cipher = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=counter)
        payload = os.urandom(0x40) + cipher.encrypt(plain_body)

        es = crypto.decrypt_video_aes([_FakeBlock(payload, frame_time)], key, nonce)
        self.assertEqual(es, bytes(payload[:0x40]) + plain_body)

    def test_per_block_independence(self):
        """每块独立 CTR 实例：不同 frame_time 的两块互不影响。"""
        from Crypto.Cipher import AES
        key = os.urandom(16)
        nonce = os.urandom(8)

        def enc(ft, body):
            counter = nonce + struct.pack(">I", ft) + b"\x00" * 4
            c = AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=counter)
            return c.encrypt(body)

        b1 = _FakeBlock(os.urandom(0x40) + enc(1, os.urandom(0x80)), 1)
        b2 = _FakeBlock(os.urandom(0x40) + enc(2, os.urandom(0x80)), 2)
        es = crypto.decrypt_video_aes([b1, b2], key, nonce)
        self.assertEqual(len(es), 2 * (0x40 + 0x80))
        # 单独解 b1 与两块一起解的前段必须一致（块间无状态串扰）
        self.assertEqual(es[0x40:0xC0], crypto.decrypt_video_aes([b1], key, nonce)[0x40:])
        self.assertEqual(es[0x40 + 0xC0:], crypto.decrypt_video_aes([b2], key, nonce)[0x40:])


class TestAudioMask(unittest.TestCase):
    def test_pattern(self):
        m1, _ = crypto.build_masks(0x42)
        am = crypto.build_audio_mask(m1)
        for i in range(32):
            if i & 1:
                self.assertEqual(am[i], b"URUC"[(i >> 1) & 3])
            else:
                self.assertEqual(am[i], m1[i] ^ 0xFF)

    def test_chunk_region(self):
        """只处理 [0x140:]；前 0x140 字节原样；32 字节循环相位对齐。"""
        m1, _ = crypto.build_masks(0x99)
        am = crypto.build_audio_mask(m1)
        payload = bytes(range(256)) * 2 + os.urandom(0x140)  # len = 0x240
        out = crypto.decrypt_audio_chunk(payload, am)
        self.assertEqual(out[:0x140], payload[:0x140])
        for i in range(0x140, len(payload)):
            self.assertEqual(out[i], payload[i] ^ am[i & 0x1F], f"offset {i:#x}")
        # 短块（≤0x140）原样
        short = os.urandom(0x100)
        self.assertEqual(crypto.decrypt_audio_chunk(short, am), short)


class TestAdx(unittest.TestCase):
    def test_patch_cri(self):
        header = bytearray(288)
        header[0:2] = b"\x80\x00"
        struct.pack_into(">H", header, 2, 0x11C)   # miHoYo 字段值（0x11A ≠ 0x11C）
        header[0x05] = 18
        # 版权串被抹掉 → 在 0x11A 补，且字段 0x02 保持原值（实测结论）
        out, patched = adx_mod.patch_cri(bytes(header))
        self.assertTrue(patched)
        self.assertEqual(out[0x11A:0x120], b"(c)CRI")
        self.assertEqual(struct.unpack_from(">H", out, 2)[0], 0x11C)
        # 已有 → 原样
        out2, patched2 = adx_mod.patch_cri(out)
        self.assertFalse(patched2)
        self.assertEqual(out2, out)

    def test_sync_ratio_encrypted_vs_plain(self):
        def make_stream(sync_bytes):
            header = bytearray(288)
            header[0:2] = b"\x80\x00"
            struct.pack_into(">H", header, 2, 0x11C)
            header[0x05] = 18
            body = bytearray()
            for s in sync_bytes:
                frame = bytearray(18)
                frame[0] = s
                body += frame
            return bytes(header) + bytes(body)

        plain = make_stream([0] * 200)
        enc = make_stream([(i * 31 + 7) & 0xFF for i in range(200)])
        self.assertFalse(adx_mod.looks_encrypted(plain))
        self.assertTrue(adx_mod.looks_encrypted(enc))


class TestResolveMux(unittest.TestCase):
    def test_auto_matrix(self):
        self.assertEqual(resolve_mux("vp9", 0, "flac", "auto")[0], "webm")
        self.assertEqual(resolve_mux("h264", 0, "flac", "auto")[0], "mp4")
        self.assertEqual(resolve_mux("mpeg1", 0, "flac", "auto")[0], "mkv")
        # 多音轨 → MKV
        c, fmt, notes = resolve_mux("vp9", 4, "flac", "auto")
        self.assertEqual(c, "mkv")
        self.assertTrue(notes)
        # 强制纠正
        self.assertEqual(resolve_mux("h264", 0, "flac", "webm")[0], "mkv")
        c, fmt, notes = resolve_mux("mpeg1", 0, "flac", "mp4")
        self.assertEqual(c, "mkv")
        # MP4 保留 FLAC（无损优先）；裸 PCM 才降级 AAC
        c, fmt, notes = resolve_mux("h264", 2, "flac", "mp4")
        self.assertEqual((c, fmt), ("mp4", "flac"))
        self.assertEqual(notes, [])
        c, fmt, notes = resolve_mux("h264", 2, "wav", "mp4")
        self.assertEqual((c, fmt), ("mp4", "aac"))
        self.assertTrue(notes)
        # raw → 容器内无音轨
        self.assertEqual(resolve_mux("vp9", 0, "raw", "auto")[0], "webm")


if __name__ == "__main__":
    unittest.main()
