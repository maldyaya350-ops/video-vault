"""Video Vault Player.

* Frozen (EXE) mode: reads the encrypted payload appended to its own executable.
* Otherwise opens a .vvault file given on the command line, dropped on the window,
  or picked with the Open button.

Video is decrypted block-by-block in memory and streamed to the media backend through a
seekable QIODevice, so no plaintext video is written to disk (unless the user accepts the
temporary-file fallback after a playback error).
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QEvent, QEventLoop, QIODevice, QLocale, QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaMetaData, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressDialog, QSlider,
                               QStyle, QToolButton, QVBoxLayout, QWidget)

import vault_core as vc
from common import (STYLE, Settings, configure_file_logging, data_dir, language, log, resource_path,
                    set_language, tr)


class DecryptedDevice(QIODevice):
    """Read-only, seekable view of the decrypted video for QMediaPlayer."""

    def __init__(self, reader: vc.VaultReader, parent=None):
        super().__init__(parent)
        self._r = reader

    def isSequential(self):
        return False

    def size(self):
        return self._r.size

    def bytesAvailable(self):
        return max(0, self._r.size - self.pos()) + super().bytesAvailable()

    def readData(self, maxlen):
        try:
            return self._r.read(self.pos(), maxlen)
        except Exception as exc:  # corrupt block etc.; end the stream rather than crash the UI thread
            log.error("Read failed at %s: %s", self.pos(), exc)
            return b""

    def writeData(self, data):
        return -1


class _NullAudio(QObject):
    """Stand-in used when the machine has no audio output device."""

    mutedChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._muted = False

    def setVolume(self, v):
        pass

    def setMuted(self, m):
        self._muted = bool(m)
        self.mutedChanged.emit(self._muted)

    def isMuted(self):
        return self._muted


class VerifyThread(QThread):
    progress = Signal(int)
    result = Signal(object)  # True / False / None (cancelled) / Exception

    def __init__(self, reader):
        super().__init__()
        self.reader = reader
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            ok = self.reader.verify(lambda f: self.progress.emit(int(f * 100)), lambda: self._cancel)
            self.result.emit(ok)
        except vc.Cancelled:
            self.result.emit(None)
        except Exception as exc:
            self.result.emit(exc)


class ClickSlider(QSlider):
    """Slider that jumps to the clicked position."""

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.maximum() > 0:
            v = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(e.position().x()), self.width())
            self.setValue(v)
            self.sliderMoved.emit(v)
        super().mousePressEvent(e)


def fmt_time(ms: int) -> str:
    s = max(0, ms // 1000)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class Player(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.reader: vc.VaultReader | None = None
        self.device: DecryptedDevice | None = None
        self.embedded = False
        self.temp_dir: str | None = None
        self.tried_temp = False
        self.setAcceptDrops(True)
        self.resize(1000, 620)
        icon = resource_path("assets/icon.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        # --- media
        self.player = QMediaPlayer(self)
        # Play silently (video only) when the machine has no audio output device, or when
        # VIDEOVAULT_NO_AUDIO=1 is set (used for headless testing without a sound server).
        if not os.environ.get("VIDEOVAULT_NO_AUDIO") and QMediaDevices.audioOutputs():
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
        else:
            log.warning("No audio output device found; playing without sound.")
            self.audio = _NullAudio(self)
        self.video = QVideoWidget()
        self.video.setStyleSheet("background:#000;")
        self.video.setMouseTracking(True)
        self.video.installEventFilter(self)
        self.player.setVideoOutput(self.video)

        self.hint = QLabel(tr("drop_vault"), self.video)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setStyleSheet("background:transparent;color:#8d93a5;font-size:16px;")
        self.subtitle = QLabel("", self.video)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet("background:rgba(0,0,0,150);color:white;font-size:20px;padding:4px 10px;border-radius:6px;")
        self.subtitle.hide()
        sink = self.video.videoSink()
        if sink is not None:
            sink.subtitleTextChanged.connect(self._on_subtitle)

        # --- controls
        self.bar = QWidget()
        self.bar.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.btn_play = QToolButton()
        self.btn_play.clicked.connect(self.toggle_play)
        self.lbl_cur = QLabel("0:00")
        self.lbl_tot = QLabel("0:00")
        self.seek = ClickSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.btn_mute = QToolButton()
        self.btn_mute.clicked.connect(self.toggle_mute)
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(80)
        self.vol.setFixedWidth(90)
        self.vol.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.audio.setVolume(0.8)
        self.sub_combo = QComboBox()
        self.sub_combo.setMinimumWidth(120)
        self.sub_combo.currentIndexChanged.connect(self._choose_subtitle)
        self.speed = QComboBox()
        for r in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            self.speed.addItem(f"{r:g}×", r)
        self.speed.setCurrentIndex(2)
        self.speed.currentIndexChanged.connect(lambda: self.player.setPlaybackRate(self.speed.currentData()))
        self.btn_full = QToolButton()
        self.btn_full.setText("⛶")
        self.btn_full.clicked.connect(self.toggle_fullscreen)
        self.btn_menu = QToolButton()
        self.btn_menu.setText("⚙")
        self.btn_menu.clicked.connect(self._show_menu)

        row = QHBoxLayout(self.bar)
        row.setContentsMargins(10, 6, 10, 8)
        for w in (self.btn_play, self.lbl_cur, self.seek, self.lbl_tot, self.btn_mute, self.vol,
                  self.sub_combo, self.speed, self.btn_full, self.btn_menu):
            row.addWidget(w, 1 if w is self.seek else 0)

        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.video, 1)
        col.addWidget(self.bar)
        self.setCentralWidget(central)

        # --- signals
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._sync_icons)
        self.player.tracksChanged.connect(self._fill_subtitles)
        self.player.errorOccurred.connect(self._on_error)
        self.audio.mutedChanged.connect(self._sync_icons)

        self.hide_timer = QTimer(self, interval=2500, singleShot=True)
        self.hide_timer.timeout.connect(self._autohide)
        atexit.register(self._cleanup_temp)
        self.retranslate()

    # ------------------------------------------------------------------ i18n / chrome
    def retranslate(self):
        self.setWindowTitle(tr("app_player") if not self.reader else self.reader.meta.get("title", tr("app_player")))
        self.hint.setText(tr("drop_vault"))
        self.btn_full.setToolTip(tr("fullscreen"))
        self.sub_combo.setToolTip(tr("subtitles"))
        self.speed.setToolTip(tr("speed"))
        self.btn_menu.setToolTip(tr("settings"))
        self._sync_icons()
        self._fill_subtitles()

    def _sync_icons(self, *_):
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("⏸" if playing else "▶")
        self.btn_play.setToolTip(tr("pause") if playing else tr("play"))
        self.btn_mute.setText("🔇" if self.audio.isMuted() else "🔊")
        self.btn_mute.setToolTip(tr("mute"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.hint.setGeometry(self.video.rect())
        w = self.video.width()
        self.subtitle.setFixedWidth(max(100, int(w * 0.8)))
        self.subtitle.adjustSize()
        self.subtitle.move((w - self.subtitle.width()) // 2, self.video.height() - self.subtitle.height() - 30)

    # ------------------------------------------------------------------ opening a vault
    def start(self, argv: list[str]):
        path = None
        if argv and Path(argv[0]).is_file() and vc.locate_payload(argv[0]):
            path = argv[0]
        elif getattr(sys, "frozen", False) and vc.locate_payload(sys.executable):
            path, self.embedded = sys.executable, True
        if path:
            self.open_vault(path)

    def open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("choose_vault"), "", "Video Vault (*.vvault *.exe);;*")
        if p:
            self.open_vault(p)

    def open_vault(self, path: str):
        self._close_vault()
        try:
            reader = vc.VaultReader(path)
        except Exception as exc:
            log.error("Open failed: %s", exc)
            QMessageBox.critical(self, tr("app_player"), tr("not_vault"))
            return self._maybe_quit()
        if not self._unlock(reader) or (self.settings.get("verify_before_play") and not self._verify(reader)):
            reader.close()
            return self._maybe_quit()
        self.reader = reader
        self.tried_temp = False
        log.info("Unlocked %s (%s bytes)", reader.meta.get("name"), reader.size)
        self.hint.hide()
        self.setWindowTitle(reader.meta.get("title", tr("app_player")))
        self.device = DecryptedDevice(reader)
        self.device.open(QIODevice.OpenModeFlag.ReadOnly)
        self.player.setSourceDevice(self.device, QUrl("file:///" + quote(reader.meta.get("name", "video.mp4"))))
        self.player.play()

    def _maybe_quit(self):
        if self.embedded:
            QTimer.singleShot(0, QApplication.quit)

    def _unlock(self, reader: vc.VaultReader) -> bool:
        guard = vc.AttemptGuard(data_dir(), reader.file_id)
        tries, note = 0, ""
        while True:
            wait = guard.lock_remaining()
            if wait:
                QMessageBox.warning(self, tr("app_player"), tr("locked", s=wait))
                return False
            pw, ok = QInputDialog.getText(self, tr("app_player"), (note + "\n" if note else "") + tr("enter_pw"),
                                          QLineEdit.EchoMode.Password)
            if not ok:
                return False
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                reader.unlock(pw)
            except vc.WrongPassword:
                guard.record_failure()
                tries += 1
                log.warning("Wrong password (%d)", tries)
                if tries >= vc.AttemptGuard.MAX_BEFORE_LOCK or guard.lock_remaining():
                    QApplication.restoreOverrideCursor()
                    QMessageBox.warning(self, tr("app_player"), tr("too_many"))
                    return False
                note = tr("wrong_pw", n=vc.AttemptGuard.MAX_BEFORE_LOCK - tries)
                continue
            except vc.VaultError as exc:
                QApplication.restoreOverrideCursor()
                QMessageBox.critical(self, tr("app_player"), f"{tr('integrity_fail')}\n\n{exc}")
                return False
            finally:
                QApplication.restoreOverrideCursor()
            guard.reset()
            return True

    def _verify(self, reader: vc.VaultReader) -> bool:
        dlg = QProgressDialog(tr("integrity_checking"), tr("cancel"), 0, 100, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(300)
        th, loop, out = VerifyThread(reader), QEventLoop(), {}
        th.progress.connect(dlg.setValue)
        th.result.connect(lambda r: (out.update(r=r), loop.quit()))
        dlg.canceled.connect(th.cancel)
        th.start()
        loop.exec()
        th.wait()
        dlg.close()
        r = out.get("r")
        if r is None or r is True:  # None = user skipped; blocks are still authenticated as they are read
            return True
        log.error("Integrity check failed: %s", r)
        QMessageBox.critical(self, tr("app_player"), tr("integrity_fail") + (f"\n\n{r}" if isinstance(r, Exception) else ""))
        return False

    def _close_vault(self):
        self.player.stop()
        self.player.setSourceDevice(None)
        if self.device:
            self.device.close()
            self.device = None
        if self.reader:
            self.reader.close()
            self.reader = None

    # ------------------------------------------------------------------ playback controls
    def toggle_play(self):
        if not self.reader:
            return self.open_dialog()
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def toggle_mute(self):
        self.audio.setMuted(not self.audio.isMuted())

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.bar.show()
            self.video.unsetCursor()
            self.hide_timer.stop()
        else:
            self.showFullScreen()
            self.hide_timer.start()

    def _autohide(self):
        if self.isFullScreen() and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.bar.hide()
            self.video.setCursor(Qt.CursorShape.BlankCursor)

    def _on_position(self, pos):
        if not self.seek.isSliderDown():
            self.seek.setValue(pos)
        self.lbl_cur.setText(fmt_time(pos))

    def _on_duration(self, dur):
        self.seek.setRange(0, dur)
        self.lbl_tot.setText(fmt_time(dur))

    def _seek_by(self, ms):
        self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + ms)))

    # ------------------------------------------------------------------ subtitles (embedded tracks)
    def _fill_subtitles(self):
        self.sub_combo.blockSignals(True)
        self.sub_combo.clear()
        self.sub_combo.addItem(tr("sub_off"), -1)
        for i, md in enumerate(self.player.subtitleTracks()):
            label = None
            try:
                label = md.stringValue(QMediaMetaData.Key.Title) or None
                lang = md.value(QMediaMetaData.Key.Language)
                if not label and lang is not None:
                    label = QLocale.languageToString(lang) if isinstance(lang, QLocale.Language) else str(lang)
            except Exception:
                pass
            self.sub_combo.addItem(label or f"{tr('subtitles')} {i + 1}", i)
        self.sub_combo.setVisible(self.sub_combo.count() > 1)
        active = self.player.activeSubtitleTrack()
        self.sub_combo.setCurrentIndex(active + 1 if 0 <= active < self.sub_combo.count() - 1 else 0)
        self.sub_combo.blockSignals(False)

    def _choose_subtitle(self):
        self.player.setActiveSubtitleTrack(self.sub_combo.currentData())
        if self.sub_combo.currentData() == -1:
            self.subtitle.hide()

    def _on_subtitle(self, text: str):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text) and self.sub_combo.currentData() != -1)
        self.subtitle.adjustSize()
        self.subtitle.move((self.video.width() - self.subtitle.width()) // 2,
                           self.video.height() - self.subtitle.height() - 30)
        self.subtitle.raise_()

    # ------------------------------------------------------------------ errors / fallback
    def _on_error(self, error, text):
        if error == QMediaPlayer.Error.NoError or not self.reader:
            return
        log.error("Playback error: %s %s", error, text)
        if not self.tried_temp:
            self.tried_temp = True
            if QMessageBox.question(self, tr("app_player"), tr("playback_error", e=text) + "\n\n" + tr("decrypt_temp")) \
                    == QMessageBox.StandardButton.Yes:
                self._play_via_temp_file()
        else:
            QMessageBox.critical(self, tr("app_player"), tr("playback_error", e=text))

    def _play_via_temp_file(self):
        self._cleanup_temp()
        self.temp_dir = tempfile.mkdtemp(prefix="vv_")
        dest = Path(self.temp_dir) / (self.reader.meta.get("name") or "video.mp4")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.reader.export_to(dest)
        finally:
            QApplication.restoreOverrideCursor()
        self.player.setSource(QUrl.fromLocalFile(str(dest)))
        self.player.play()

    def _cleanup_temp(self):
        if self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            self.temp_dir = None

    # ------------------------------------------------------------------ menu, events
    def _show_menu(self):
        m = QMenu(self)
        m.addAction(tr("open_file"), self.open_dialog)
        a = QAction(tr("verify_before"), m, checkable=True, checked=bool(self.settings.get("verify_before_play")))
        a.toggled.connect(lambda v: self.settings.set("verify_before_play", v))
        m.addAction(a)
        lang = m.addMenu(tr("language"))
        for code, name in (("en", "English"), ("ar", "العربية")):
            act = QAction(name, lang, checkable=True, checked=language() == code)
            act.triggered.connect(lambda _=False, c=code: self._set_language(c))
            lang.addAction(act)
        m.exec(self.btn_menu.mapToGlobal(self.btn_menu.rect().bottomLeft()))

    def _set_language(self, code):
        set_language(code)
        self.settings.set("language", code)
        QApplication.instance().setLayoutDirection(Qt.LayoutDirection.RightToLeft if code == "ar" else Qt.LayoutDirection.LeftToRight)
        self.bar.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.retranslate()

    def eventFilter(self, obj, ev):
        if obj is self.video:
            t = ev.type()
            if t == QEvent.Type.MouseMove and self.isFullScreen():
                self.bar.show()
                self.video.unsetCursor()
                self.hide_timer.start()
            elif t == QEvent.Type.MouseButtonDblClick:
                self.toggle_fullscreen()
                return True
            elif t == QEvent.Type.MouseButtonRelease and self.reader:
                self.toggle_play()
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        big = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if k == Qt.Key.Key_Space:
            self.toggle_play()
        elif k == Qt.Key.Key_Left:
            self._seek_by(-30000 if big else -5000)
        elif k == Qt.Key.Key_Right:
            self._seek_by(30000 if big else 5000)
        elif k == Qt.Key.Key_Up:
            self.vol.setValue(min(100, self.vol.value() + 5))
        elif k == Qt.Key.Key_Down:
            self.vol.setValue(max(0, self.vol.value() - 5))
        elif k in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_M:
            self.toggle_mute()
        else:
            super().keyPressEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p and Path(p).is_file():
                self.open_vault(p)
                break

    def closeEvent(self, e):
        self._close_vault()
        self._cleanup_temp()
        super().closeEvent(e)


def main():
    settings = Settings("player")
    set_language(settings.get("language"))
    configure_file_logging(bool(settings.get("file_log")))
    app = QApplication(sys.argv)
    app.setApplicationName("VideoVaultPlayer")
    app.setStyleSheet(STYLE)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if language() == "ar" else Qt.LayoutDirection.LeftToRight)
    win = Player(settings)
    win.show()
    QTimer.singleShot(0, lambda: win.start(sys.argv[1:]))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
