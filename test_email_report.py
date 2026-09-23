"""
Email report MVP: content, frequency window, secret storage, mocked SMTP.

No network. SMTP is a fake client. Companion files stay in a temp directory.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import smtplib
import socket
import sys
import tempfile
import types
from datetime import datetime, timedelta

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if "winreg" not in sys.modules:
        winreg = types.ModuleType("winreg")
        winreg.HKEY_CURRENT_USER = 1
        winreg.HKEY_LOCAL_MACHINE = 2
        winreg.KEY_READ = 0
        winreg.KEY_WRITE = 0
        winreg.KEY_SET_VALUE = 0
        winreg.REG_DWORD = 4
        winreg.REG_SZ = 1
        winreg.KEY_WOW64_64KEY = 0x0100

        def _missing(*_a, **_k):
            raise FileNotFoundError("winreg stub")

        winreg.OpenKey = _missing
        winreg.CreateKey = _missing
        winreg.CloseKey = lambda *_a, **_k: None
        winreg.QueryValueEx = _missing
        winreg.SetValueEx = _missing
        winreg.DeleteValue = _missing
        winreg.EnumKey = _missing
        winreg.error = OSError
        sys.modules["winreg"] = winreg

from app_meta import APP_VERSION
from config_manager import DEFAULT_CONFIG, SECRET_KEYS, ConfigManager
from core.companion_diary import make_event, write_events
from core.companion_learning import save_daily_model
from core.companion_reflection import save_reflection
from core.companion_skills import save_skill
from core.email_report import (
    PASSWORD_KEY,
    frequency_window_already_sent,
    build_report,
    report_is_due,
    send_scheduled_report,
    send_test_email,
)

NOW = datetime(2026, 9, 23, 9, 0, 0)
SECRET = "SuperSecretSmtp9"


def _ready(**overrides):
    data = {
        "enabled": True,
        "to": "ban@example.com",
        "frequency": "weekly",
        "hour": 8,
        "minute": 0,
        "host": "smtp.example.com",
        "port": 587,
        "username": "ban@example.com",
        "password": SECRET,
        "use_tls": True,
        "use_ssl": False,
        "from_name": "PC Cleaner",
        "from_address": "",
        "last_sent_at": "",
        "last_attempt_at": "",
        "last_error": "",
    }
    data.update(overrides)
    return data


class MemCfg:
    def __init__(self, **overrides):
        self.data = {
            "email_report_enabled": True,
            "email_report_to": "ban@example.com",
            "email_report_frequency": "weekly",
            "email_report_send_hour": 8,
            "email_report_send_minute": 0,
            "email_report_smtp_host": "smtp.example.com",
            "email_report_smtp_port": 587,
            "email_report_smtp_username": "ban@example.com",
            "email_report_smtp_password": SECRET,
            "email_report_smtp_use_tls": True,
            "email_report_smtp_use_ssl": False,
            "email_report_from_name": "PC Cleaner",
            "email_report_from_address": "",
            "email_report_last_sent_at": "",
            "email_report_last_attempt_at": "",
            "email_report_last_error": "",
        }
        self.data.update(overrides)
        self.config = self.data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save_config(self):
        return True


class FakeSMTP:
    instances = []

    def __init__(self, host, port=0, timeout=None, **_kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged = None
        self.sent = []
        self.quit_called = False
        FakeSMTP.instances.append(self)

    def ehlo(self):
        return None

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged = (user, password)

    def send_message(self, message):
        self.sent.append(message)

    def quit(self):
        self.quit_called = True

    def close(self):
        return None


class FakeSSL:
    instances = []

    def __init__(self, host, port=0, timeout=None, **_kwargs):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.logged = None
        self.sent = []
        FakeSSL.instances.append(self)

    def ehlo(self):
        return None

    def starttls(self):
        raise AssertionError("SSL session must not call STARTTLS")

    def login(self, user, password):
        self.logged = (user, password)

    def send_message(self, message):
        self.sent.append(message)

    def quit(self):
        return None

    def close(self):
        return None


class AuthFailSMTP(FakeSMTP):
    def login(self, user, password):
        raise smtplib.SMTPAuthenticationError(535, f"reject {password}".encode())


class TimeoutSMTP(FakeSMTP):
    def __init__(self, host, port=0, timeout=None, **kwargs):
        raise TimeoutError(f"timed out {SECRET}")


class LookupSMTP(FakeSMTP):
    def __init__(self, host, port=0, timeout=None, **kwargs):
        raise socket.gaierror(f"dns {SECRET}")


def _capture_logs():
    logger = logging.getLogger("pc_cleaner.email_report")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    records = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _Handler()
    logger.addHandler(handler)
    return logger, handler, records


def test_defaults_are_off_and_password_is_secret():
    assert APP_VERSION == "3.8.6"
    assert DEFAULT_CONFIG["email_report_enabled"] is False
    assert DEFAULT_CONFIG["email_report_frequency"] == "weekly"
    assert DEFAULT_CONFIG["email_report_send_hour"] == 8
    assert PASSWORD_KEY in SECRET_KEYS
    assert PASSWORD_KEY not in DEFAULT_CONFIG
    assert "email_report_smtp_password" not in json.dumps(DEFAULT_CONFIG)


def test_report_uses_only_supplied_data():
    root = tempfile.mkdtemp(prefix="email-report-empty-")
    empty = build_report(now=NOW, snapshots={}, base_dir=root)
    assert "Chưa có số liệu" in empty["text"]
    assert "°C" not in empty["text"]
    assert "RAM" not in empty["text"]
    assert "Wi-Fi" not in empty["text"]
    assert "3.8.6" in empty["text"]
    assert "không qua máy chủ mail" in empty["text"]

    filled = build_report(
        now=NOW,
        base_dir=root,
        snapshots={
            "disk": {"drive": "C:", "total_gb": 256, "free_gb": 120.5, "percent": 53},
            "ram": {"used_gb": 8.2, "total_gb": 16, "percent": 51},
            "network": {
                "ping_ms": 24,
                "ping_measured": True,
                "adapter": "Ethernet",
                "down_bps": 0,
                "up_bps": 0,
            },
            "thermal": {
                "available": True,
                "hottest_celsius": 67,
                "hottest_label": "CPU Package",
                "status_label": "ổn",
            },
            "wifi": {
                "is_wifi": True,
                "ssid": "<img>",
                "signal": "80%",
                "link_mbps": 144,
                "cause_label": "ổn định",
            },
        },
        redact_values=[SECRET],
    )
    text = filled["text"]
    assert "120.5 GB" in text
    assert "8.2 / 16 GB" in text
    assert "24 ms" in text
    assert "Ethernet" in text
    assert "67°C" in text
    assert "CPU Package" in text
    assert "80%" in text
    assert "&lt;img&gt;" in filled["html"]
    assert "<img>" not in filled["html"]
    assert SECRET not in text

    hidden = build_report(
        now=NOW,
        base_dir=root,
        snapshots={
            "disk": {"drive": "C:", "total_gb": 0, "free_gb": 0, "percent": 0},
            "network": {"ping_ms": -1, "ping_measured": False, "adapter": "", "down_bps": 0, "up_bps": 0},
            "thermal": {"available": False, "hottest_celsius": None},
            "wifi": {"is_wifi": False, "ssid": "Nope"},
        },
    )
    assert "Nope" not in hidden["text"]
    assert "°C" not in hidden["text"]
    assert "Độ trễ" not in hidden["text"]


def test_companion_sections_come_from_local_files():
    root = tempfile.mkdtemp(prefix="email-report-diary-")
    write_events([
        make_event("wifi_weak", "Wi-Fi yếu", now=datetime(2026, 9, 23, 10, 0, 0), outcome="warn"),
        make_event("thermal_warn", "Nhiệt cao", now=datetime(2026, 9, 23, 11, 0, 0), outcome="warn"),
        make_event("focus_end", "Kết thúc buổi học", now=datetime(2026, 9, 22, 9, 0, 0), outcome="neutral"),
    ], base_dir=root)
    save_reflection(
        "Tóm tắt tuần: tuần 39 (đến 23/09), chỉ số liệu máy này.\nTrong tuần: Wi-Fi yếu 1, nhiệt cao 1.",
        source="weekly",
        base_dir=root,
        now=NOW,
    )
    assert save_skill("wifi_weak", base_dir=root) is not None
    report = build_report(now=NOW, snapshots={}, base_dir=root)
    text = report["text"]
    assert "Trong tuần: Wi-Fi yếu 1" in text
    assert "Ngày máy nặng" in text
    assert "phiên đã kết thúc" in text
    assert "Wi-Fi yếu" in text
    assert "°C" not in text

    quiet = tempfile.mkdtemp(prefix="email-report-quiet-")
    save_reflection(
        "Tóm tắt tuần: tuần này chưa có diễn biến mới trên máy này.",
        source="weekly",
        base_dir=quiet,
        now=NOW,
    )
    quiet_report = build_report(now=NOW, snapshots={}, base_dir=quiet)
    assert "chưa có diễn biến" not in quiet_report["text"]
    assert "Ngày máy nặng" not in quiet_report["text"]

    learned = tempfile.mkdtemp(prefix="email-report-learn-")
    save_daily_model({
        "date": "2026-09-23",
        "summary_vi": "Hôm nay học được: Wi-Fi hay gặp buổi sáng.",
        "rough_days": 2,
        "focus_sessions": 3,
    }, base_dir=learned)
    learned_report = build_report(now=NOW, snapshots={}, base_dir=learned)
    assert "Wi-Fi hay gặp buổi sáng" in learned_report["text"]
    assert "2 ngày hơi nặng" in learned_report["text"]
    assert "3 lần Trước thi / họp" in learned_report["text"]


def test_frequency_window_and_retry_cooldown():
    base = _ready()
    assert report_is_due(base, now=NOW) is True
    assert report_is_due(_ready(enabled=False), now=NOW) is False
    assert report_is_due(_ready(frequency="off"), now=NOW) is False
    assert report_is_due(_ready(password=""), now=NOW) is False
    assert report_is_due(_ready(to="khong-phai-email"), now=NOW) is False
    assert report_is_due(base, now=NOW.replace(hour=7, minute=59)) is False

    same_week = datetime(2026, 9, 21, 8, 5, 0)
    assert frequency_window_already_sent(same_week, NOW, "weekly") is True
    assert report_is_due(_ready(last_sent_at=same_week.isoformat()), now=NOW) is False
    previous_week = datetime(2026, 9, 16, 8, 5, 0)
    assert frequency_window_already_sent(previous_week, NOW, "weekly") is False
    assert report_is_due(_ready(last_sent_at=previous_week.isoformat()), now=NOW) is True

    daily_now = datetime(2026, 9, 24, 8, 0, 0)
    assert report_is_due(
        _ready(frequency="daily", last_sent_at="2026-09-23T08:05:00"),
        now=datetime(2026, 9, 23, 18, 0, 0),
    ) is False
    assert report_is_due(
        _ready(frequency="daily", last_sent_at="2026-09-23T08:05:00"),
        now=datetime(2026, 9, 24, 7, 59, 0),
    ) is False
    assert report_is_due(
        _ready(frequency="daily", last_sent_at="2026-09-23T08:05:00"),
        now=daily_now,
    ) is True

    assert report_is_due(
        _ready(frequency="every_3_days", last_sent_at="2026-09-20T09:00:00"),
        now=datetime(2026, 9, 22, 12, 0, 0),
    ) is False
    assert report_is_due(
        _ready(frequency="every_3_days", last_sent_at="2026-09-20T09:00:00"),
        now=datetime(2026, 9, 23, 7, 0, 0),
    ) is False
    assert report_is_due(
        _ready(frequency="every_3_days", last_sent_at="2026-09-20T09:00:00"),
        now=datetime(2026, 9, 23, 8, 0, 0),
    ) is True
    assert report_is_due(
        _ready(frequency="every_3_days", last_sent_at="2026-09-20T09:00:00"),
        now=datetime(2026, 9, 24, 1, 0, 0),
    ) is True

    attempt = NOW - timedelta(minutes=10)
    assert report_is_due(_ready(last_attempt_at=attempt.isoformat()), now=NOW) is False
    assert report_is_due(
        _ready(last_attempt_at=(NOW - timedelta(minutes=31)).isoformat()),
        now=NOW,
    ) is True


def test_scheduled_send_is_idempotent_and_mocks_smtp():
    FakeSMTP.instances = []
    logger, handler, records = _capture_logs()
    try:
        cfg = MemCfg()
        root = tempfile.mkdtemp(prefix="email-report-send-")
        first = send_scheduled_report(
            cfg,
            now=NOW,
            base_dir=root,
            snapshots={"ram": {"used_gb": 4, "total_gb": 8, "percent": 50}},
            smtp_factory=FakeSMTP,
            smtp_ssl_factory=FakeSSL,
        )
        assert first["ok"] is True
        assert len(FakeSMTP.instances) == 1
        client = FakeSMTP.instances[0]
        assert client.started_tls is True
        assert client.logged == ("ban@example.com", SECRET)
        assert client.sent and client.quit_called is True
        message = client.sent[0]
        assert SECRET not in str(message)
        assert "4 / 8 GB" in message.get_body(preferencelist=("plain",)).get_content()
        assert cfg.get("email_report_last_sent_at").startswith("2026-09-23T09:00:00")
        second = send_scheduled_report(
            cfg,
            now=NOW + timedelta(hours=2),
            base_dir=root,
            snapshots={},
            smtp_factory=FakeSMTP,
            smtp_ssl_factory=FakeSSL,
        )
        assert second["skipped"] is True
        assert len(FakeSMTP.instances) == 1
        assert SECRET not in "\n".join(records)

        off = MemCfg(email_report_enabled=False, email_report_last_sent_at="")
        skipped = send_scheduled_report(
            off, now=NOW, snapshots={}, smtp_factory=FakeSMTP, smtp_ssl_factory=FakeSSL,
        )
        assert skipped["skipped"] is True
        assert len(FakeSMTP.instances) == 1
    finally:
        logger.removeHandler(handler)


def test_smtp_errors_are_vietnamese_and_hide_the_password():
    logger, handler, records = _capture_logs()
    try:
        cfg = MemCfg()
        auth = send_test_email(cfg, now=NOW, smtp_factory=AuthFailSMTP)
        assert auth["ok"] is False
        assert "đăng nhập" in auth["message_vi"]
        assert SECRET not in auth["message_vi"]
        assert cfg.get("email_report_last_sent_at") == ""

        timeout = send_test_email(cfg, now=NOW, smtp_factory=TimeoutSMTP)
        assert "thời gian chờ" in timeout["message_vi"]
        assert SECRET not in timeout["message_vi"]

        lookup = send_test_email(cfg, now=NOW, smtp_factory=LookupSMTP)
        assert "máy chủ SMTP" in lookup["message_vi"]
        assert SECRET not in lookup["message_vi"]
        assert SECRET not in "\n".join(records)

        disabled = send_test_email(MemCfg(email_report_enabled=False), now=NOW, smtp_factory=FakeSMTP)
        assert disabled["ok"] is False
        assert "tắt" in disabled["message_vi"]

        bad = send_test_email(MemCfg(email_report_to="khong-phai-email"), now=NOW, smtp_factory=FakeSMTP)
        assert "chưa hợp lệ" in bad["message_vi"]
    finally:
        logger.removeHandler(handler)


def test_ssl_uses_smtp_ssl_and_failure_does_not_consume_the_window():
    FakeSSL.instances = []
    FakeSMTP.instances = []
    cfg = MemCfg(email_report_smtp_use_ssl=True, email_report_smtp_use_tls=False, email_report_smtp_port=465)
    result = send_scheduled_report(
        cfg, now=NOW, snapshots={}, smtp_factory=FakeSMTP, smtp_ssl_factory=FakeSSL,
    )
    assert result["ok"] is True
    assert len(FakeSSL.instances) == 1
    assert FakeSSL.instances[0].port == 465
    assert len(FakeSMTP.instances) == 0

    failed = MemCfg()
    first = send_scheduled_report(
        failed, now=NOW, snapshots={}, smtp_factory=AuthFailSMTP, smtp_ssl_factory=FakeSSL,
    )
    assert first["ok"] is False
    assert failed.get("email_report_last_sent_at") == ""
    assert "đăng nhập" in failed.get("email_report_last_error")
    assert SECRET not in failed.get("email_report_last_error")
    again = send_scheduled_report(
        failed, now=NOW + timedelta(minutes=5), snapshots={}, smtp_factory=FakeSMTP, smtp_ssl_factory=FakeSSL,
    )
    assert again["skipped"] is True
    later = send_scheduled_report(
        failed,
        now=NOW + timedelta(minutes=31),
        snapshots={},
        smtp_factory=FakeSMTP,
        smtp_ssl_factory=FakeSSL,
    )
    assert later["ok"] is True
    assert failed.get("email_report_last_sent_at").startswith("2026-09-23T09:31:00")


def test_password_stays_out_of_config_and_companion_export():
    previous = os.environ.get("PCAUTOCLEANER_SECRETS_PATH")
    cfg_fd, cfg_path = tempfile.mkstemp(suffix=".json")
    sec_fd, sec_path = tempfile.mkstemp(suffix=".json")
    os.close(cfg_fd)
    os.close(sec_fd)
    os.environ["PCAUTOCLEANER_SECRETS_PATH"] = sec_path
    try:
        with open(cfg_path, "w", encoding="utf-8") as handle:
            json.dump({PASSWORD_KEY: SECRET, "email_report_enabled": False}, handle)
        cfg = ConfigManager(config_path=cfg_path)
        assert cfg.get(PASSWORD_KEY) == SECRET
        with open(cfg_path, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        assert PASSWORD_KEY not in stored
        assert SECRET not in json.dumps(stored)
        with open(sec_path, "r", encoding="utf-8") as handle:
            secrets = json.load(handle)
        assert secrets.get(PASSWORD_KEY) == SECRET
        cfg.set("email_report_to", "ban@example.com")
        with open(cfg_path, "r", encoding="utf-8") as handle:
            blob = handle.read()
        assert SECRET not in blob
        cfg.set(PASSWORD_KEY, "")
        assert cfg.get(PASSWORD_KEY, "") == ""
        with open(sec_path, "r", encoding="utf-8") as handle:
            cleared = json.load(handle)
        assert PASSWORD_KEY not in cleared

        cfg.set(PASSWORD_KEY, SECRET)
        from core.companion import _redact_tree, export_companion_memory
        from core.companion_diary import diary_path
        root = tempfile.mkdtemp(prefix="email-report-export-")
        os.makedirs(root, exist_ok=True)
        with open(diary_path(root), "w", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "ts": "2026-09-23T10:00:00",
                "kind": "chat_note",
                "summary": f"ghi chú có {SECRET}",
                "metrics": {},
                "source": "test",
                "outcome": "neutral",
                "tags": ["morning"],
            }, ensure_ascii=False) + "\n")
        with open(os.path.join(root, "so_tay.txt"), "w", encoding="utf-8") as handle:
            handle.write(f"Sổ tay {SECRET}")
        cleaned = _redact_tree({
            PASSWORD_KEY: SECRET,
            "note": f"hello {SECRET}",
        })
        assert PASSWORD_KEY not in cleaned
        assert SECRET not in json.dumps(cleaned)
        exported_path = os.path.join(root, "export.json")
        exported = export_companion_memory(exported_path, base_dir=root)
        assert exported.get("ok") is True
        with open(exported_path, "r", encoding="utf-8") as handle:
            blob = handle.read()
        assert SECRET not in blob
        assert PASSWORD_KEY not in blob
    finally:
        if previous is None:
            os.environ.pop("PCAUTOCLEANER_SECRETS_PATH", None)
        else:
            os.environ["PCAUTOCLEANER_SECRETS_PATH"] = previous
        for path in (cfg_path, sec_path):
            try:
                os.remove(path)
            except OSError:
                pass


def test_scheduler_hooks_the_report_and_settings_ui_exists():
    from core.scheduler import BackgroundScheduler
    source = inspect.getsource(BackgroundScheduler._tick)
    assert "_maybe_send_email_report" in source
    assert inspect.getsource(BackgroundScheduler._maybe_send_email_report)

    from PyQt5.QtWidgets import QApplication, QLabel, QLineEdit
    previous_secrets = os.environ.get("PCAUTOCLEANER_SECRETS_PATH")
    previous_companion = os.environ.get("PCAUTOCLEANER_COMPANION_DIR")
    cfg_fd, cfg_path = tempfile.mkstemp(suffix=".json")
    sec_fd, sec_path = tempfile.mkstemp(suffix=".json")
    os.close(cfg_fd)
    os.close(sec_fd)
    companion = tempfile.mkdtemp(prefix="email-report-ui-")
    os.environ["PCAUTOCLEANER_SECRETS_PATH"] = sec_path
    os.environ["PCAUTOCLEANER_COMPANION_DIR"] = companion
    win = None
    try:
        with open(cfg_path, "w", encoding="utf-8") as handle:
            handle.write("{}")
        cfg = ConfigManager(config_path=cfg_path)
        app = QApplication.instance() or QApplication([])
        from ui.main_window import MainWindow
        win = MainWindow(cfg)
        assert win.chk_email_report.isChecked() is False
        assert win.btn_email_test.text() == "Gửi thử"
        assert win.combo_email_freq.currentText() == "Hằng tuần"
        assert win.spin_email_hour.value() == 8
        assert win.spin_email_minute.value() == 0
        assert win.edit_smtp_password.echoMode() == QLineEdit.Password
        labels = "\n".join(label.text() for label in win.findChildren(QLabel))
        assert "máy này" in labels
        assert "máy chủ mail" in labels
        win.chk_email_report.setChecked(True)
        win.edit_email_to.setText("ban@example.com")
        win.edit_smtp_host.setText("smtp.example.com")
        win.edit_smtp_user.setText("ban@example.com")
        win.edit_smtp_password.setText(SECRET)
        win._save_email_report_settings()
        with open(cfg_path, "r", encoding="utf-8") as handle:
            blob = handle.read()
        assert SECRET not in blob
        assert PASSWORD_KEY not in blob
        assert cfg.get(PASSWORD_KEY) == SECRET
        assert cfg.get("email_report_enabled") is True
        assert cfg.get("email_report_frequency") == "weekly"
        app.processEvents()
    finally:
        if win is not None:
            win.close()
        if previous_secrets is None:
            os.environ.pop("PCAUTOCLEANER_SECRETS_PATH", None)
        else:
            os.environ["PCAUTOCLEANER_SECRETS_PATH"] = previous_secrets
        if previous_companion is None:
            os.environ.pop("PCAUTOCLEANER_COMPANION_DIR", None)
        else:
            os.environ["PCAUTOCLEANER_COMPANION_DIR"] = previous_companion


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("email report tests passed")
