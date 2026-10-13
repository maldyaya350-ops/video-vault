"""Video Vault Creator: encrypt one or many videos into password-protected programs/files."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

import vault_core as vc
from common import (STYLE, Settings, configure_file_logging, language, log, resource_path, set_language, tr)

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".3gp"}
STRENGTH_COLORS = ["#e5484d", "#f08a24", "#e5c13a", "#46a758", "#2bb5a0"]
PW_ERRORS = {"short": "pw_short", "common": "pw_common", "weak": "pw_weak"}


# --------------------------------------------------------------------------- helpers
def find_stub(settings: Settings) -> Path | None:
    custom = settings.get("stub_path")
    if custom and Path(custom).is_file():
        return Path(custom)
    here = Path(__file__).resolve().parent
    for name in ("VideoVaultPlayer.exe", "VideoVaultPlayer"):
        for base in (resource_path(""), Path(sys.executable).parent, here, here / "dist"):
            if (base / name).is_file():
                return base / name
    return None


def collect_videos(paths) -> list[Path]:
    found: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            found += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in VIDEO_EXTS)
        elif p.is_file():
            found.append(p)
    return found


def unique_path(outdir: Path, stem: str, ext: str) -> Path:
    p = outdir / f"{stem}_protected{ext}"
    n = 1
    while p.exists():
        p = outdir / f"{stem}_protected ({n}){ext}"
        n += 1
    return p


def default_save_dir() -> str:
    v = Path.home() / "Videos"
    return str(v if v.is_dir() else Path.home())


class LogBridge(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: LogBridge):
        super().__init__()
        self.bridge = bridge
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        self.bridge.message.emit(self.format(record))


# --------------------------------------------------------------------------- widgets
class DropTable(QTableWidget):
    dropped = Signal(list)

    def __init__(self):
        super().__init__(0, 4)
        self.hint = ""
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.rowCount() == 0:
            p = QPainter(self.viewport())
            p.setPen(QColor("#626a7e"))
            p.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, self.hint)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        self.dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()


class PasswordFields(QWidget):
    """Password + confirmation + strength meter + generator."""

    def __init__(self):
        super().__init__()
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_cb = QCheckBox()
        self.gen_btn = QPushButton()
        self.meter = QProgressBar()
        self.meter.setObjectName("strength")
        self.meter.setRange(0, 4)
        self.meter.setTextVisible(False)
        self.meter_lbl = QLabel()
        self.l1, self.l2 = QLabel(), QLabel()
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(self.pw, 1)
        row.addWidget(self.show_cb)
        form.addRow(self.l1, row)
        form.addRow(self.l2, self.pw2)
        mrow = QHBoxLayout()
        mrow.addWidget(self.meter, 1)
        mrow.addWidget(self.meter_lbl)
        form.addRow("", mrow)
        form.addRow("", self.gen_btn)
        self.show_cb.toggled.connect(self._toggle)
        self.gen_btn.clicked.connect(self._generate)
        self.pw.textChanged.connect(self.update_meter)
        self.retranslate()
        self.update_meter()

    def retranslate(self):
        self.l1.setText(tr("password"))
        self.l2.setText(tr("confirm"))
        self.show_cb.setText(tr("show_pw"))
        self.gen_btn.setText(tr("generate"))
        self.update_meter()

    def _toggle(self, on):
        mode = QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        self.pw.setEchoMode(mode)
        self.pw2.setEchoMode(mode)

    def _generate(self):
        p = vc.generate_password()
        self.pw.setText(p)
        self.pw2.setText(p)
        self.show_cb.setChecked(True)

    def update_meter(self):
        score, _ = vc.password_strength(self.pw.text())
        self.meter.setValue(score if self.pw.text() else 0)
        color = STRENGTH_COLORS[score]
        self.meter.setStyleSheet(f"QProgressBar#strength::chunk{{background:{color};border-radius:4px;}}")
        self.meter_lbl.setText(tr(f"s{score}") if self.pw.text() else "")

    def error(self) -> str | None:
        """Return a translated problem description, or None if the password is acceptable."""
        code = vc.validate_password(self.pw.text())
        if code:
            return tr(PW_ERRORS[code])
        if self.pw.text() != self.pw2.text():
            return tr("pw_mismatch")
        return None

    def clear(self):
        self.pw.clear()
        self.pw2.clear()
        self.show_cb.setChecked(False)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("settings_title"))
        self.setMinimumWidth(520)
        self.lang = QComboBox()
        self.lang.addItem("English", "en")
        self.lang.addItem("العربية", "ar")
        self.lang.setCurrentIndex(0 if language() == "en" else 1)
        self.save_dir = QLineEdit(settings.get("save_dir") or "")
        self.stub = QLineEdit(settings.get("stub_path") or "")
        self.file_log = QCheckBox(tr("file_log"))
        self.file_log.setChecked(bool(settings.get("file_log")))
        self.verify = QCheckBox(tr("verify_after"))
        self.verify.setChecked(bool(settings.get("verify_after_create")))

        def with_browse(edit, cb):
            w = QWidget()
            r = QHBoxLayout(w)
            r.setContentsMargins(0, 0, 0, 0)
            b = QPushButton(tr("browse"))
            b.clicked.connect(cb)
            r.addWidget(edit, 1)
            r.addWidget(b)
            return w

        form = QFormLayout()
        form.addRow(tr("language"), self.lang)
        form.addRow(tr("out_folder"), with_browse(self.save_dir, self._pick_dir))
        form.addRow(tr("stub_path"), with_browse(self.stub, self._pick_stub))
        form.addRow("", self.file_log)
        form.addRow("", self.verify)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("choose_folder"), self.save_dir.text())
        if d:
            self.save_dir.setText(d)

    def _pick_stub(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("stub_path"), self.stub.text(), "Programs (*.exe);;*")
        if f:
            self.stub.setText(f)

    def apply(self):
        s = self.settings
        s.set("language", self.lang.currentData())
        s.set("save_dir", self.save_dir.text().strip())
        s.set("stub_path", self.stub.text().strip())
        s.set("file_log", self.file_log.isChecked())
        s.set("verify_after_create", self.verify.isChecked())


class ChangePasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("change_pw_btn"))
        self.setMinimumWidth(460)
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        browse = QPushButton(tr("browse"))
        browse.clicked.connect(self._pick)
        self.old = QLineEdit()
        self.old.setEchoMode(QLineEdit.EchoMode.Password)
        self.new = PasswordFields()
        self.new.l1.setText(tr("new_pw"))
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        form = QFormLayout()
        form.addRow(tr("choose_vault"), row)
        form.addRow(tr("old_pw"), self.old)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.new)
        lay.addWidget(buttons)

    def _pick(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("choose_vault"), "", "Video Vault (*.vvault *.exe);;*")
        if f:
            self.path.setText(f)

    def _ok(self):
        if not self.path.text():
            return
        err = self.new.error()
        if err:
            return QMessageBox.warning(self, tr("change_pw_btn"), err)
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            vc.change_password(self.path.text(), self.old.text(), self.new.pw.text())
        except vc.WrongPassword:
            QApplication.restoreOverrideCursor()
            return QMessageBox.warning(self, tr("change_pw_btn"), tr("wrong_pw_simple"))
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            log.error("Change password failed: %s", exc)
            return QMessageBox.critical(self, tr("change_pw_btn"), str(exc))
        QApplication.restoreOverrideCursor()
        log.info("Password changed for %s", Path(self.path.text()).name)
        QMessageBox.information(self, tr("change_pw_btn"), tr("pw_changed"))
        self.accept()


# --------------------------------------------------------------------------- worker
class Worker(QThread):
    progress = Signal(int, int)           # row, percent
    state = Signal(int, str, str, int)    # row, state, message, output size
    finished_all = Signal()

    def __init__(self, jobs, password, mode, stub, outdir, title, verify):
        super().__init__()
        self.jobs, self.password, self.mode, self.stub = jobs, password, mode, stub
        self.outdir, self.title, self.verify = outdir, title, verify
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        log.info(tr("log_start", n=len(self.jobs), m=self.mode))
        ext = ".exe" if self.mode == "exe" else ".vvault"
        for row, src in self.jobs:
            if self._cancel:
                self.state.emit(row, "cancel", "", 0)
                continue
            dst = None
            try:
                dst = unique_path(self.outdir, src.stem, ext)
                last = [-1]

                def on_progress(f, r=row):
                    pct = int(f * 100)
                    if pct != last[0]:
                        last[0] = pct
                        self.progress.emit(r, pct)

                info = vc.create_vault(src, dst, self.password, stub=self.stub if self.mode == "exe" else None,
                                       title=self.title or src.stem, progress=on_progress,
                                       should_cancel=lambda: self._cancel)
                if self.verify:
                    self.state.emit(row, "verify", "", 0)
                    with vc.VaultReader(dst) as rd:
                        rd.unlock(self.password)
                        if not rd.verify(should_cancel=lambda: self._cancel):
                            raise vc.VaultError(tr("mismatch_after"))
                self.state.emit(row, "ok", "", info["output_size"])
                log.info(tr("ok_line", name=src.name, a=vc.human_size(info["input_size"]),
                            b=vc.human_size(info["output_size"])))
            except vc.Cancelled:
                self.state.emit(row, "cancel", "", 0)
                log.info(tr("cancelled") + f": {src.name}")
                self._discard(dst)
            except Exception as exc:
                self.state.emit(row, "fail", str(exc), 0)
                log.error(tr("fail_line", name=src.name, e=exc))
                self._discard(dst)
        self.password = ""
        self.finished_all.emit()

    @staticmethod
    def _discard(dst):
        try:
            if dst and dst.exists():
                dst.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- main window
class Creator(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.worker: Worker | None = None
        self.stub = find_stub(settings)
        self.resize(980, 760)
        icon = resource_path("assets/icon.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        # list
        self.table = DropTable()
        self.table.dropped.connect(lambda paths: self.add_paths(paths))
        self.btn_add, self.btn_remove, self.btn_clear = QPushButton(), QPushButton(), QPushButton()
        self.btn_add.clicked.connect(self.pick_files)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(lambda: self.table.setRowCount(0))
        list_buttons = QHBoxLayout()
        for b in (self.btn_add, self.btn_remove, self.btn_clear):
            list_buttons.addWidget(b)
        list_buttons.addStretch(1)
        self.g_files = QGroupBox()
        fl = QVBoxLayout(self.g_files)
        fl.addWidget(self.table, 1)
        fl.addLayout(list_buttons)

        # password
        self.pwf = PasswordFields()
        self.g_pw = QGroupBox()
        QVBoxLayout(self.g_pw).addWidget(self.pwf)

        # output
        self.mode = QComboBox()
        self.mode.currentIndexChanged.connect(lambda: self.settings.set("output_mode", self.mode.currentData()))
        self.outdir = QLineEdit(settings.get("save_dir") or default_save_dir())
        self.btn_browse = QPushButton()
        self.btn_browse.clicked.connect(self.pick_outdir)
        self.title = QLineEdit()
        self.l_mode, self.l_out, self.l_title = QLabel(), QLabel(), QLabel()
        self.g_out = QGroupBox()
        of = QFormLayout(self.g_out)
        of.addRow(self.l_mode, self.mode)
        orow = QHBoxLayout()
        orow.addWidget(self.outdir, 1)
        orow.addWidget(self.btn_browse)
        of.addRow(self.l_out, orow)
        of.addRow(self.l_title, self.title)

        mid = QHBoxLayout()
        mid.addWidget(self.g_pw, 1)
        mid.addWidget(self.g_out, 1)

        # actions
        self.overall = QProgressBar()
        self.btn_create, self.btn_cancel = QPushButton(), QPushButton()
        self.btn_create.setObjectName("primary")
        self.btn_create.clicked.connect(self.start)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.setEnabled(False)
        self.btn_change = QPushButton()
        self.btn_change.clicked.connect(lambda: ChangePasswordDialog(self).exec())
        self.btn_open = QPushButton()
        self.btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.outdir.text())))
        self.btn_settings = QPushButton()
        self.btn_settings.clicked.connect(self.open_settings)
        self.log_cb = QCheckBox()
        self.log_cb.toggled.connect(lambda v: self.logview.setVisible(v))
        actions = QHBoxLayout()
        actions.addWidget(self.btn_change)
        actions.addWidget(self.btn_open)
        actions.addWidget(self.btn_settings)
        actions.addWidget(self.log_cb)
        actions.addStretch(1)
        actions.addWidget(self.btn_cancel)
        actions.addWidget(self.btn_create)

        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setMaximumBlockCount(2000)
        self.logview.setFixedHeight(130)
        self.logview.hide()
        self.bridge = LogBridge()
        self.bridge.message.connect(self.logview.appendPlainText)
        handler = QtLogHandler(self.bridge)
        log.addHandler(handler)

        central = QWidget()
        col = QVBoxLayout(central)
        col.addWidget(self.g_files, 1)
        col.addLayout(mid)
        col.addWidget(self.overall)
        col.addLayout(actions)
        col.addWidget(self.logview)
        self.setCentralWidget(central)
        self.setAcceptDrops(True)
        self.retranslate()

    # ------------------------------------------------------------------ i18n
    def retranslate(self):
        self.setWindowTitle(tr("app_creator"))
        self.g_files.setTitle(tr("col_file"))
        self.table.hint = tr("drop_hint")
        self.table.setHorizontalHeaderLabels([tr("col_file"), tr("col_orig"), tr("col_out"), tr("col_status")])
        self.btn_add.setText(tr("add_files"))
        self.btn_remove.setText(tr("remove"))
        self.btn_clear.setText(tr("clear"))
        self.g_pw.setTitle(tr("password"))
        self.pwf.retranslate()
        self.g_out.setTitle(tr("output_mode"))
        current = self.settings.get("output_mode")
        self.mode.blockSignals(True)
        self.mode.clear()
        self.mode.addItem(tr("mode_exe"), "exe")
        self.mode.addItem(tr("mode_vvault"), "vvault")
        self.mode.setCurrentIndex(0 if current != "vvault" else 1)
        self.mode.blockSignals(False)
        self.l_mode.setText(tr("output_mode"))
        self.l_out.setText(tr("out_folder"))
        self.l_title.setText(tr("display_title"))
        self.btn_browse.setText(tr("browse"))
        self.btn_create.setText(tr("create"))
        self.btn_cancel.setText(tr("cancel"))
        self.btn_change.setText(tr("change_pw_btn"))
        self.btn_open.setText(tr("open_folder"))
        self.btn_settings.setText(tr("settings"))
        self.log_cb.setText(tr("log"))
        for r in range(self.table.rowCount()):
            self._render_status(r)
        self.table.viewport().update()

    # ------------------------------------------------------------------ list management
    def pick_files(self):
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, tr("choose_videos"), "", f"Video ({exts});;*")
        self.add_paths(files)

    def add_paths(self, paths):
        if self.worker:
            return
        existing = {self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount())}
        for p in collect_videos(paths):
            key = str(p)
            if key in existing:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            name = QTableWidgetItem(p.name)
            name.setData(Qt.ItemDataRole.UserRole, key)
            name.setToolTip(key)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(vc.human_size(p.stat().st_size)))
            self.table.setItem(r, 2, QTableWidgetItem("—"))
            status = QTableWidgetItem()
            status.setData(Qt.ItemDataRole.UserRole, ("wait", 0, ""))
            self.table.setItem(r, 3, status)
            self._render_status(r)
            existing.add(key)

    def remove_selected(self):
        if self.worker:
            return
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, tr("choose_folder"), self.outdir.text())
        if d:
            self.outdir.setText(d)

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            dlg.apply()
            set_language(self.settings.get("language"))
            QApplication.instance().setLayoutDirection(
                Qt.LayoutDirection.RightToLeft if language() == "ar" else Qt.LayoutDirection.LeftToRight)
            configure_file_logging(bool(self.settings.get("file_log")))
            if self.settings.get("save_dir"):
                self.outdir.setText(self.settings.get("save_dir"))
            self.stub = find_stub(self.settings)
            self.retranslate()

    # ------------------------------------------------------------------ status rendering
    def _render_status(self, row):
        item = self.table.item(row, 3)
        state, pct, msg = item.data(Qt.ItemDataRole.UserRole)
        text = {
            "wait": tr("status_wait"), "run": tr("status_run", p=pct), "verify": tr("status_verify"),
            "ok": tr("status_ok"), "fail": tr("status_fail"), "cancel": tr("status_cancel"),
        }[state]
        item.setText(text)
        item.setToolTip(msg)
        item.setForeground(QColor({"ok": "#46a758", "fail": "#e5484d", "cancel": "#f08a24"}.get(state, "#e6e8ee")))

    def _set_state(self, row, state, msg="", out_size=0):
        self.table.item(row, 3).setData(Qt.ItemDataRole.UserRole, (state, 100 if state == "ok" else 0, msg))
        self._render_status(row)
        if state == "ok":
            self.table.item(row, 2).setText(self.table.item(row, 1).text() + "  →  " + vc.human_size(out_size))
        self._update_overall()

    def _on_progress(self, row, pct):
        self.table.item(row, 3).setData(Qt.ItemDataRole.UserRole, ("run", pct, ""))
        self._render_status(row)
        self._update_overall(pct)

    def _update_overall(self, current_pct=0):
        total = self.table.rowCount()
        done = sum(1 for r in range(total)
                   if self.table.item(r, 3).data(Qt.ItemDataRole.UserRole)[0] in ("ok", "fail", "cancel"))
        if total:
            self.overall.setValue(int((done * 100 + (current_pct if done < total else 0)) / total))

    # ------------------------------------------------------------------ run
    def start(self):
        if self.table.rowCount() == 0:
            return QMessageBox.information(self, tr("app_creator"), tr("no_files"))
        err = self.pwf.error()
        if err:
            return QMessageBox.warning(self, tr("app_creator"), err)
        mode = self.mode.currentData()
        if mode == "exe" and not self.stub:
            return QMessageBox.warning(self, tr("app_creator"), tr("no_stub"))
        outdir = Path(self.outdir.text().strip())
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return QMessageBox.critical(self, tr("app_creator"), str(exc))
        jobs = []
        for r in range(self.table.rowCount()):
            jobs.append((r, Path(self.table.item(r, 0).data(Qt.ItemDataRole.UserRole))))
            self._set_state(r, "wait")
            self.table.item(r, 2).setText("—")
        self.overall.setValue(0)
        self._busy(True)
        self.worker = Worker(jobs, self.pwf.pw.text(), mode, self.stub, outdir, self.title.text().strip(),
                             bool(self.settings.get("verify_after_create")))
        self.worker.progress.connect(self._on_progress)
        self.worker.state.connect(self._set_state)
        self.worker.finished_all.connect(self._finished)
        self.worker.start()

    def cancel(self):
        if self.worker:
            self.worker.cancel()

    def _finished(self):
        states = [self.table.item(r, 3).data(Qt.ItemDataRole.UserRole)[0] for r in range(self.table.rowCount())]
        ok, fail = states.count("ok"), states.count("fail")
        self.worker.wait()
        self.worker = None
        self.pwf.clear()
        self.overall.setValue(100 if ok and not fail else self.overall.value())
        self._busy(False)
        log.info(tr("summary", ok=ok, fail=fail))
        QMessageBox.information(self, tr("app_creator"), tr("summary", ok=ok, fail=fail))

    def _busy(self, busy: bool):
        for w in (self.btn_create, self.btn_add, self.btn_remove, self.btn_clear, self.btn_change,
                  self.btn_settings, self.pwf, self.g_out):
            w.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)

    # ------------------------------------------------------------------ events
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def closeEvent(self, e):
        if self.worker:
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(e)


def main():
    settings = Settings("creator")
    set_language(settings.get("language"))
    configure_file_logging(bool(settings.get("file_log")))
    app = QApplication(sys.argv)
    app.setApplicationName("VideoVaultCreator")
    app.setStyleSheet(STYLE)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if language() == "ar" else Qt.LayoutDirection.LeftToRight)
    win = Creator(settings)
    win.show()
    win.add_paths(sys.argv[1:])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
