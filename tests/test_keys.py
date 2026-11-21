"""keys.py / games.py 的合成数据单元测试。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hoyo_usm import games as gmod
from hoyo_usm.keys import KeyStore, History, normalize_entry


class TestNormalize(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(normalize_entry("0000000000000000").method, "plain")
        e = normalize_entry("000000000B3E3FD5")
        self.assertEqual(e.method, "mask")
        self.assertEqual(e.key_hex, "000000000b3e3fd5")
        d = normalize_entry({"aes": "458725216E2CCBCD12961E57B85109A6", "audio": "000E104C4538BD01"})
        self.assertEqual(d.method, "aes")
        self.assertEqual(d.audio_hex, "000e104c4538bd01")

    def test_invalid_dropped(self):
        self.assertIsNone(normalize_entry("nothex"))
        self.assertIsNone(normalize_entry("123"))                      # 长度不足
        self.assertIsNone(normalize_entry({"aes": "00" * 16}))         # 全零 aes → 丢弃
        self.assertIsNone(normalize_entry({"aes": "zz"}))
        self.assertIsNone(normalize_entry(42))
        # audio 全零 = 无音频 key，条目本身有效
        d = normalize_entry({"aes": "458725216E2CCBCD12961E57B85109A6", "audio": "0000000000000000"})
        self.assertEqual(d.method, "aes")
        self.assertIsNone(d.audio_hex)


class TestKeyStore(unittest.TestCase):
    def _make(self, tmp: Path) -> KeyStore:
        prof = gmod.GAMES["zzz"]
        (tmp / "nap_keys.json").write_text(json.dumps({
            "ChallengeZero02": "000000000B3E3FD5",
            "Dup": "000000000B3E3FD6",
        }), encoding="utf-8")
        (tmp / "nap_keys_by_path.json").write_text(json.dumps({
            "_note": "test", "count": 1,
            "keys": {"Transfer/HollowLoading/Zero/Dup": "000000000AABBCCD"},
        }), encoding="utf-8")
        (tmp / "nap_history.json").write_text(json.dumps({
            "ZenlessZoneZero_Data/StreamingAssets/Video/HD/x.usm": {
                "filename": "x.usm",
                "versions": [{"version": "1.3.0", "md5": "a"}, {"version": "1.0.0", "md5": "b"}],
            },
        }), encoding="utf-8")
        return KeyStore(tmp, key_file=prof.key_file, history_file=prof.history_file,
                        by_path_file=prof.by_path_file,
                        by_path_prefixes=prof.by_path_prefixes)

    def test_by_path_beats_name(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._make(Path(td))
            hit = store.lookup("ZenlessZoneZero_Data/StreamingAssets/Video/HD/Transfer/HollowLoading/Zero/Dup.usm")
            self.assertEqual(hit.via, "path")
            self.assertEqual(hit.entry.key_hex, "000000000aabbccd")

    def test_name_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._make(Path(td))
            hit = store.lookup("ZenlessZoneZero_Data/StreamingAssets/Video/HD/ChallengeZero02.usm")
            self.assertEqual(hit.via, "name")
            self.assertEqual(hit.entry.method, "mask")

    def test_missing(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._make(Path(td))
            hit = store.lookup("ZenlessZoneZero_Data/StreamingAssets/Video/HD/Nope.usm")
            self.assertIsNone(hit.entry)
            self.assertIsNone(hit.via)

    def test_history_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            store = self._make(Path(td))
            cands = store.history_candidates(
                "ZenlessZoneZero_Data/Persistent/Video/HD/x.usm")
            self.assertIn("ZenlessZoneZero_Data/StreamingAssets/Video/HD/x.usm", cands)

    def test_history_classify_and_latest(self):
        # versions 时间正序（实测 nap_history），versions[0] = 首次出现版本
        h = History({
            "a": {"versions": [{"version": "1.0.0"}, {"version": "1.3.0"}]},   # 1.3.0 重发 = 修改
            "b": {"versions": [{"version": "1.3.0"}]},                          # 1.3.0 首现 = 新增
            "c": {"versions": [{"version": "1.0.0"}]},                          # 与 1.3.0 无关
            "d": {"versions": [{"version": "1.9.0"}, {"version": "1.10.0"}]},
        })
        self.assertEqual(h.latest_version(), "1.10.0")   # 数值比较 1.10.0 > 1.9.0
        self.assertEqual(h.classify(h.entries["a"], "1.3.0"), "modified")
        self.assertEqual(h.classify(h.entries["b"], "1.3.0"), "new")
        self.assertIsNone(h.classify(h.entries["c"], "1.3.0"))

    def test_md5_index_and_sizes(self):
        h = History({
            "P/A.usm": {"versions": [{"version": "1.0.0", "md5": "AAAA1111", "size": 100}]},
            "P/B.usm": {"versions": [{"version": "1.0.0", "md5": "bbbb2222", "size": 200},
                                     {"version": "1.1.0", "md5": "AAAA1111", "size": 100}]},
        })
        # 同一 md5 出现在两条路径（内容相同多路径发行）→ 两个都反查得到
        self.assertEqual(h.paths_by_md5("aaaa1111"), ["P/A.usm", "P/B.usm"])
        self.assertEqual(h.paths_by_md5("BBBB2222"), ["P/B.usm"])   # 大小写不敏感
        self.assertEqual(h.paths_by_md5("nope"), [])
        self.assertEqual(h.sizes(), {100, 200})


class TestGames(unittest.TestCase):
    def test_alias_and_profile(self):
        self.assertEqual(gmod.resolve_game("hk4e").id, "gi")
        self.assertEqual(gmod.resolve_game("nap").codename, "nap")
        self.assertFalse(gmod.GAMES["zzz"].has_audio)
        self.assertTrue(gmod.GAMES["gi"].has_audio)
        self.assertEqual(gmod.GAMES["gi"].audio_langs[2], "jpn")

    def test_scan_dedup_hotfix_wins(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "ZenlessZoneZero_Data/StreamingAssets/Video/HD/Sub"
            hot = root / "ZenlessZoneZero_Data/Persistent/Video/HD/Sub"
            base.mkdir(parents=True)
            hot.mkdir(parents=True)
            (base / "a.usm").write_bytes(b"0" * 100)
            (hot / "a.usm").write_bytes(b"0" * 50)
            (base / "b.usm").write_bytes(b"0" * 100)

            files = gmod.scan(root, gmod.GAMES["zzz"])
            self.assertEqual(set(files), {"Sub/a.usm", "Sub/b.usm"})
            self.assertEqual(files["Sub/a.usm"].source, "hotfix")
            self.assertEqual(files["Sub/b.usm"].source, "baseline")
            self.assertTrue(files["Sub/a.usm"].rel_root.startswith("ZenlessZoneZero_Data/Persistent"))


if __name__ == "__main__":
    unittest.main()
