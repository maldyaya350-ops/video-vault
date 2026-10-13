"""Offscreen GUI smoke test: creator batch -> player playback through the decrypting QIODevice.

Run:  QT_QPA_PLATFORM=offscreen python tests/smoke_gui.py
Needs ffmpeg on PATH to synthesise a test clip. Results are printed; non-zero exit on failure.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VIDEOVAULT_NO_AUDIO", "1")  # headless box: no sound server to enumerate
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QIODevice, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

import vault_core as vc  # noqa: E402
from common import Settings  # noqa: E402

PW = "Smoke-Test-Pass-77!"
tmp = Path(tempfile.mkdtemp())
os.environ["XDG_DATA_HOME"] = str(tmp / "data")
failures = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        failures.append(name)


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(pred, timeout=20000, step=100):
    t0 = time.time()
    while time.time() - t0 < timeout / 1000:
        if pred():
            return True
        pump(step)
    return False


# --- synthesize a clip with an embedded subtitle track
srt = tmp / "s.srt"
srt.write_text("1\n00:00:00,200 --> 00:00:02,500\nHello subtitle\n\n")
clip = tmp / "clip.mkv"
r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-i", str(srt),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-c:s", "srt", "-t", "4", str(clip)],
                   capture_output=True, text=True)
check("ffmpeg made test clip", clip.exists() and clip.stat().st_size > 0, r.stderr.strip()[:120])

app = QApplication(sys.argv)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: print("CRITICAL dialog:", a[2:]))

# --- creator batch (vvault mode)
import creator_app  # noqa: E402

settings = Settings("smoke")
cr = creator_app.Creator(settings)
cr.show()
cr.add_paths([str(clip), str(tmp)])  # file + folder (folder contains the same clip -> de-duplicated by path)
check("table has the video once", cr.table.rowCount() == 1, str(cr.table.rowCount()))
cr.outdir.setText(str(tmp / "out"))
cr.mode.setCurrentIndex(1)
cr.pwf.pw.setText(PW)
cr.pwf.pw2.setText("different")
cr.start()
check("mismatched passwords block start", cr.worker is None)
cr.pwf.pw2.setText(PW)
cr.start()
check("worker started", cr.worker is not None)
check("worker finished", wait_for(lambda: cr.worker is None))
out = next((tmp / "out").glob("*.vvault"), None)
check("output file created", out is not None)
status = cr.table.item(0, 3).text()
check("row marked done", status in ("Done",), status)
check("password fields cleared after run", cr.pwf.pw.text() == "")
check("output size column filled", "→" in cr.table.item(0, 2).text(), cr.table.item(0, 2).text())

# --- Arabic / RTL switch doesn't crash
from common import set_language  # noqa: E402
set_language("ar")
cr.retranslate()
check("arabic strings applied", cr.btn_create.text() != "Create protected files", cr.btn_create.text())
set_language("en")
cr.retranslate()

# --- QIODevice subclass behaves like a file
import player_app  # noqa: E402

with vc.VaultReader(out) as rd:
    rd.unlock(PW)
    dev = player_app.DecryptedDevice(rd)
    check("device opens", dev.open(QIODevice.OpenModeFlag.ReadOnly))
    check("device reports size", dev.size() == clip.stat().st_size)
    check("device is random access", not dev.isSequential())
    dev.seek(1000)
    got = bytes(dev.read(4096))
    check("device read matches plaintext", got == clip.read_bytes()[1000:5096])
    dev.seek(dev.size() - 10)
    check("device tail read", bytes(dev.readAll()) == clip.read_bytes()[-10:])
    dev.close()

# --- player: unlock (dialog patched), verify, and actually play
QInputDialog.getText = staticmethod(lambda *a, **k: (PW, True))
pl = player_app.Player(Settings("smoke_player"))
pl.show()
pl.open_vault(str(out))
check("player unlocked", pl.reader is not None and pl.reader.meta.get("name") == "clip.mkv")
errs, frames = [], [0]
pl.player.errorOccurred.connect(lambda e, t: errs.append(t))
pl.video.videoSink().videoFrameChanged.connect(lambda f: frames.__setitem__(0, frames[0] + 1))
ok = wait_for(lambda: pl.player.duration() > 0 or errs, 15000)
check("media backend read the decrypted stream", pl.player.duration() > 3000, f"duration={pl.player.duration()} errors={errs[:1]}")
if pl.player.duration() > 0:
    wait_for(lambda: pl.player.position() > 800 or errs, 10000)
    check("playback advanced", pl.player.position() > 500, f"pos={pl.player.position()}")
    check("decoded video frames arrived", frames[0] > 5, f"frames={frames[0]}")
    pl.player.setPosition(2500)
    pump(800)
    check("seek works", pl.player.position() >= 2400, f"pos={pl.player.position()}")
    print("INFO subtitle tracks:", len(pl.player.subtitleTracks()), "combo items:", pl.sub_combo.count())

# --- wrong password path + attempt limit
calls = {"n": 0}


def bad(*a, **k):
    calls["n"] += 1
    return ("wrong-password-1", True)


QInputDialog.getText = staticmethod(bad)
pl2 = player_app.Player(Settings("smoke_player2"))
pl2.open_vault(str(out))
check("wrong password rejected", pl2.reader is None)
check("stops after 5 attempts", calls["n"] == 5, str(calls["n"]))
calls["n"] = 0
pl2.open_vault(str(out))
check("then locked out without prompting", calls["n"] == 0, str(calls["n"]))

pl.close()
print("\nFAILURES:" if failures else "\nALL SMOKE CHECKS PASSED", failures or "")
sys.exit(1 if failures else 0)
