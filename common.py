"""Shared helpers for both apps: settings, logging, translations, theme."""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

APP_NAME = "VideoVault"


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource_path(rel: str) -> Path:
    """Resolve a bundled resource both from source and from a PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / rel


# --------------------------------------------------------------------------- settings
class Settings:
    DEFAULTS = {
        "language": "en",
        "save_dir": "",
        "file_log": True,
        "verify_after_create": True,
        "verify_before_play": True,
        "stub_path": "",
        "output_mode": "exe",
    }

    def __init__(self, name: str):
        self.path = data_dir() / f"{name}_settings.json"
        try:
            self._d = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self._d = {}

    def get(self, key):
        return self._d.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self._d[key] = value
        try:
            self.path.write_text(json.dumps(self._d, indent=2), "utf-8")
        except OSError:
            pass


# --------------------------------------------------------------------------- logging
log = logging.getLogger("vault")
log.setLevel(logging.INFO)
_file_handler: logging.Handler | None = None


def configure_file_logging(enabled: bool) -> None:
    """Passwords are never logged. Only file names, sizes, outcomes and error text."""
    global _file_handler
    if _file_handler is not None:
        log.removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None
    if enabled:
        _file_handler = logging.handlers.RotatingFileHandler(
            data_dir() / "vault.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
        _file_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s"))
        log.addHandler(_file_handler)


# --------------------------------------------------------------------------- translations
_lang = "en"

STR = {
    "en": {
        "app_creator": "Video Vault Creator",
        "app_player": "Video Vault Player",
        "add_files": "Add videos…",
        "remove": "Remove selected",
        "clear": "Clear list",
        "create": "Create protected files",
        "cancel": "Cancel",
        "settings": "Settings",
        "drop_hint": "Drag videos (or folders) here",
        "col_file": "Video",
        "col_orig": "Original size",
        "col_out": "Output size",
        "col_status": "Status",
        "password": "Password",
        "confirm": "Confirm password",
        "show_pw": "Show",
        "generate": "Generate strong password",
        "pw_mismatch": "Passwords do not match.",
        "pw_short": "Password must be at least 10 characters.",
        "pw_common": "That password is too common.",
        "pw_weak": "Password is too weak: use a longer one with mixed characters.",
        "s0": "Very weak", "s1": "Weak", "s2": "Fair", "s3": "Strong", "s4": "Very strong",
        "output_mode": "Output type",
        "mode_exe": "Windows program (.exe)",
        "mode_vvault": "Protected file (.vvault, needs the player)",
        "out_folder": "Save to",
        "browse": "Browse…",
        "display_title": "Program name (window title)",
        "status_wait": "Waiting",
        "status_run": "Encrypting… {p}%",
        "status_verify": "Verifying…",
        "status_ok": "Done",
        "status_fail": "Failed",
        "status_cancel": "Cancelled",
        "log": "Log",
        "change_pw_btn": "Change password of existing file…",
        "old_pw": "Current password",
        "new_pw": "New password",
        "pw_changed": "Password changed. The video itself was not touched.",
        "no_files": "Add at least one video first.",
        "no_stub": "No player program was found, so .exe output is unavailable here. Use .vvault, or build the player first (see README).",
        "language": "Language",
        "file_log": "Write a log file",
        "verify_after": "Verify each file after creating it",
        "stub_path": "Player program (.exe) to embed",
        "open_folder": "Open output folder",
        "summary": "Finished: {ok} succeeded, {fail} failed.",
        "choose_folder": "Choose output folder",
        "choose_videos": "Choose videos",
        "choose_vault": "Choose a protected file",
        "wrong_pw": "Wrong password. Attempts left: {n}",
        "wrong_pw_simple": "Wrong password.",
        "locked": "Too many failed attempts. Try again in {s} seconds.",
        "too_many": "Too many failed attempts. The program will close.",
        "enter_pw": "Enter the password to unlock this video:",
        "unlock": "Unlock",
        "integrity_checking": "Checking file integrity…",
        "integrity_fail": "Integrity check failed. The file is damaged or has been modified.",
        "open_file": "Open protected file…",
        "play": "Play", "pause": "Pause",
        "mute": "Mute", "fullscreen": "Full screen",
        "subtitles": "Subtitles", "sub_off": "Off",
        "speed": "Speed",
        "verify_before": "Check integrity before playing",
        "playback_error": "Playback error: {e}",
        "drop_vault": "Drop a protected file here, or press Open.",
        "not_vault": "This is not a Video Vault file.",
        "decrypt_temp": "Playback from memory failed on this system. Decrypt to a temporary file instead? (It is deleted when the player closes.)",
        "settings_title": "Settings",
        "restart_note": "Language changes apply immediately.",
        "sizes": "{a} → {b}",
        "log_start": "Started batch of {n} file(s), mode={m}",
        "ok_line": "OK  {name}: {a} -> {b}",
        "fail_line": "FAIL {name}: {e}",
        "mismatch_after": "Verification after creation failed.",
        "cancelled": "Cancelled by user",
        "exists_skip": "Output exists, using a numbered name.",
    },
    "ar": {
        "app_creator": "منشئ Video Vault",
        "app_player": "مشغّل Video Vault",
        "add_files": "إضافة فيديوهات…",
        "remove": "حذف المحدد",
        "clear": "مسح القائمة",
        "create": "إنشاء الملفات المحمية",
        "cancel": "إلغاء",
        "settings": "الإعدادات",
        "drop_hint": "اسحب الفيديوهات (أو المجلدات) وأفلتها هنا",
        "col_file": "الفيديو",
        "col_orig": "الحجم الأصلي",
        "col_out": "حجم الناتج",
        "col_status": "الحالة",
        "password": "كلمة المرور",
        "confirm": "تأكيد كلمة المرور",
        "show_pw": "إظهار",
        "generate": "توليد كلمة مرور قوية",
        "pw_mismatch": "كلمتا المرور غير متطابقتين.",
        "pw_short": "يجب ألا تقل كلمة المرور عن 10 أحرف.",
        "pw_common": "كلمة المرور هذه شائعة جداً.",
        "pw_weak": "كلمة المرور ضعيفة: استخدم كلمة أطول بأنواع مختلفة من الرموز.",
        "s0": "ضعيفة جداً", "s1": "ضعيفة", "s2": "مقبولة", "s3": "قوية", "s4": "قوية جداً",
        "output_mode": "نوع الناتج",
        "mode_exe": "برنامج ويندوز (.exe)",
        "mode_vvault": "ملف محمي (.vvault، يحتاج إلى المشغّل)",
        "out_folder": "مجلد الحفظ",
        "browse": "استعراض…",
        "display_title": "اسم البرنامج (عنوان النافذة)",
        "status_wait": "في الانتظار",
        "status_run": "جارٍ التشفير… {p}٪",
        "status_verify": "جارٍ التحقق…",
        "status_ok": "تم",
        "status_fail": "فشل",
        "status_cancel": "أُلغي",
        "log": "السجل",
        "change_pw_btn": "تغيير كلمة مرور ملف موجود…",
        "old_pw": "كلمة المرور الحالية",
        "new_pw": "كلمة المرور الجديدة",
        "pw_changed": "تم تغيير كلمة المرور. لم يتم المساس بالفيديو نفسه.",
        "no_files": "أضف فيديو واحداً على الأقل أولاً.",
        "no_stub": "لم يتم العثور على برنامج المشغّل، لذلك لا يتوفر ناتج .exe هنا. استخدم .vvault أو ابنِ المشغّل أولاً (راجع README).",
        "language": "اللغة",
        "file_log": "كتابة ملف سجل",
        "verify_after": "التحقق من كل ملف بعد إنشائه",
        "stub_path": "برنامج المشغّل (.exe) المراد تضمينه",
        "open_folder": "فتح مجلد الناتج",
        "summary": "اكتملت العملية: نجح {ok}، وفشل {fail}.",
        "choose_folder": "اختر مجلد الحفظ",
        "choose_videos": "اختر الفيديوهات",
        "choose_vault": "اختر ملفاً محمياً",
        "wrong_pw": "كلمة المرور خاطئة. المحاولات المتبقية: {n}",
        "wrong_pw_simple": "كلمة المرور خاطئة.",
        "locked": "محاولات فاشلة كثيرة. حاول مجدداً بعد {s} ثانية.",
        "too_many": "محاولات فاشلة كثيرة. سيُغلق البرنامج.",
        "enter_pw": "أدخل كلمة المرور لفتح هذا الفيديو:",
        "unlock": "فتح",
        "integrity_checking": "جارٍ فحص سلامة الملف…",
        "integrity_fail": "فشل فحص السلامة. الملف تالف أو تم تعديله.",
        "open_file": "فتح ملف محمي…",
        "play": "تشغيل", "pause": "إيقاف مؤقت",
        "mute": "كتم الصوت", "fullscreen": "ملء الشاشة",
        "subtitles": "الترجمة", "sub_off": "إيقاف",
        "speed": "السرعة",
        "verify_before": "فحص السلامة قبل التشغيل",
        "playback_error": "خطأ في التشغيل: {e}",
        "drop_vault": "أفلت ملفاً محمياً هنا، أو اضغط فتح.",
        "not_vault": "هذا ليس ملف Video Vault.",
        "decrypt_temp": "فشل التشغيل من الذاكرة على هذا الجهاز. هل تريد فك التشفير إلى ملف مؤقت؟ (يُحذف عند إغلاق المشغّل.)",
        "settings_title": "الإعدادات",
        "restart_note": "يتم تطبيق تغيير اللغة فوراً.",
        "sizes": "{a} ← {b}",
        "log_start": "بدء دفعة من {n} ملف، النوع={m}",
        "ok_line": "تم {name}: {a} -> {b}",
        "fail_line": "فشل {name}: {e}",
        "mismatch_after": "فشل التحقق بعد الإنشاء.",
        "cancelled": "ألغاه المستخدم",
        "exists_skip": "الملف موجود، سيتم استخدام اسم مرقّم.",
    },
}


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in STR else "en"


def language() -> str:
    return _lang


def tr(key: str, **kw) -> str:
    s = STR[_lang].get(key) or STR["en"].get(key, key)
    return s.format(**kw) if kw else s


# --------------------------------------------------------------------------- theme
STYLE = """
* { font-family: "Segoe UI", "Tahoma", "Noto Sans", sans-serif; font-size: 13px; }
QWidget { background: #14161c; color: #e6e8ee; }
QMainWindow, QDialog { background: #14161c; }
QGroupBox { border: 1px solid #2a2e3a; border-radius: 8px; margin-top: 14px; padding: 12px 10px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #8d93a5; }
QLineEdit, QComboBox, QPlainTextEdit, QTableWidget {
    background: #1c1f28; border: 1px solid #2a2e3a; border-radius: 6px; padding: 6px; selection-background-color: #3d5afe; }
QLineEdit:focus, QComboBox:focus { border-color: #5b78ff; }
QPushButton { background: #252a37; border: 1px solid #323849; border-radius: 6px; padding: 7px 14px; }
QPushButton:hover { background: #2d3345; }
QPushButton:disabled { color: #626a7e; background: #1b1e27; }
QPushButton#primary { background: #3d5afe; border-color: #3d5afe; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #5b78ff; }
QPushButton#primary:disabled { background: #2a3350; border-color: #2a3350; color: #7f89ad; }
QHeaderView::section { background: #1c1f28; color: #8d93a5; border: none; border-bottom: 1px solid #2a2e3a; padding: 6px; }
QTableWidget { gridline-color: #232734; }
QProgressBar { background: #1c1f28; border: 1px solid #2a2e3a; border-radius: 6px; text-align: center; height: 16px; }
QProgressBar::chunk { background: #3d5afe; border-radius: 5px; }
QProgressBar#strength { height: 8px; max-height: 8px; }
QSlider::groove:horizontal { height: 5px; background: #2a2e3a; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #3d5afe; border-radius: 2px; }
QSlider::handle:horizontal { background: #fff; width: 13px; margin: -5px 0; border-radius: 6px; }
QToolButton { background: transparent; border: none; padding: 6px; border-radius: 6px; font-size: 16px; }
QToolButton:hover { background: #2d3345; }
QMenu { background: #1c1f28; border: 1px solid #2a2e3a; }
QMenu::item:selected { background: #3d5afe; }
QCheckBox { spacing: 8px; }
"""
