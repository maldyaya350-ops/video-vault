import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vault_core as vc  # noqa: E402

PW = "Correct-Horse-9!"


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "clip.mp4"
        self.data = os.urandom(vc.CHUNK * 2 + 12345)  # 3 chunks, last partial
        self.src.write_bytes(self.data)
        self.dst = self.tmp / "clip.vvault"

    def make(self, **kw):
        return vc.create_vault(self.src, self.dst, PW, **kw)

    def test_roundtrip_and_no_plaintext_password(self):
        info = self.make()
        raw = self.dst.read_bytes()
        self.assertNotIn(PW.encode(), raw)
        self.assertNotIn(b"clip.mp4", raw)  # metadata is encrypted too
        self.assertGreater(info["output_size"], info["input_size"])
        with vc.VaultReader(self.dst) as r:
            meta = r.unlock(PW)
            self.assertEqual(meta["name"], "clip.mp4")
            self.assertEqual(r.read(0, r.size), self.data)
            self.assertTrue(r.verify())

    def test_seek_across_chunk_boundaries(self):
        self.make()
        with vc.VaultReader(self.dst) as r:
            r.unlock(PW)
            for pos, n in [(vc.CHUNK - 10, 50), (vc.CHUNK * 2 - 1, 5000), (len(self.data) - 7, 100), (5, 1)]:
                self.assertEqual(r.read(pos, n), self.data[pos:pos + n])
            self.assertEqual(r.read(len(self.data), 10), b"")

    def test_wrong_password(self):
        self.make()
        with vc.VaultReader(self.dst) as r:
            with self.assertRaises(vc.WrongPassword):
                r.unlock("wrong-password-1")

    def test_tampered_chunk_detected(self):
        self.make()
        raw = bytearray(self.dst.read_bytes())
        raw[vc.HEADER_SIZE + 100] ^= 1
        self.dst.write_bytes(raw)
        with vc.VaultReader(self.dst) as r:
            r.unlock(PW)
            with self.assertRaises(vc.CorruptVault):
                r.verify()

    def test_truncation_detected(self):
        self.make()
        raw = self.dst.read_bytes()
        self.dst.write_bytes(raw[:-1000])
        with vc.VaultReader(self.dst) as r:
            with self.assertRaises(vc.CorruptVault):
                r.unlock(PW)

    def test_exe_mode_trailer(self):
        stub = self.tmp / "stub.exe"
        stub.write_bytes(b"MZ" + os.urandom(5000))
        out = self.tmp / "clip.exe"
        vc.create_vault(self.src, out, PW, stub=stub)
        self.assertEqual(out.read_bytes()[:5002], stub.read_bytes())
        self.assertEqual(vc.locate_payload(out)[0], 5002)
        with vc.VaultReader(out) as r:
            r.unlock(PW)
            self.assertEqual(r.read(0, r.size), self.data)

    def test_change_password_rewrites_only_header(self):
        self.make()
        before = self.dst.read_bytes()
        vc.change_password(self.dst, PW, "Another-Pass-42#")
        after = self.dst.read_bytes()
        self.assertEqual(before[vc.HEADER_SIZE:], after[vc.HEADER_SIZE:])
        self.assertNotEqual(before[:vc.HEADER_SIZE], after[:vc.HEADER_SIZE])
        with vc.VaultReader(self.dst) as r:
            with self.assertRaises(vc.WrongPassword):
                r.unlock(PW)
            r.unlock("Another-Pass-42#")
            self.assertTrue(r.verify())
        with self.assertRaises(vc.WrongPassword):
            vc.change_password(self.dst, PW, "x" * 12)

    def test_cancel_cleans_up(self):
        with self.assertRaises(vc.Cancelled):
            vc.create_vault(self.src, self.dst, PW, should_cancel=lambda: True)
        self.assertFalse(self.dst.exists())
        self.assertFalse(Path(str(self.dst) + ".part").exists())

    def test_unicode_password(self):
        pw = "كلمة-سر-قوية-٢٠٢٦!"
        vc.create_vault(self.src, self.dst, pw)
        with vc.VaultReader(self.dst) as r:
            r.unlock(pw)

    def test_password_policy(self):
        self.assertEqual(vc.validate_password("short1!"), "short")
        self.assertEqual(vc.validate_password("password123"), "common")
        self.assertEqual(vc.validate_password("aaaaaaaaaaaa"), "weak")
        self.assertIsNone(vc.validate_password(PW))
        for _ in range(20):
            self.assertIsNone(vc.validate_password(vc.generate_password()))

    def test_attempt_guard(self):
        g = vc.AttemptGuard(self.tmp, "abc")
        for _ in range(4):
            g.record_failure()
        self.assertEqual(g.lock_remaining(), 0)
        g.record_failure()
        self.assertGreater(g.lock_remaining(), 0)
        g.reset()
        self.assertEqual(g.lock_remaining(), 0)
        self.assertEqual(g.failures(), 0)


if __name__ == "__main__":
    unittest.main()
