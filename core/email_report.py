"""
Local SMTP email reports.

The app aggregates numbers already on this PC and sends them with the
standard library. There is no mail relay owned by the app. The SMTP
password stays in the user secrets file and is never written to config.json,
logs, or the message body.
"""
from __future__ import annotations

import html
import logging
import re
import smtplib
import socket
import sys
from datetime import datetime, time, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Callable, Dict, List, Optional, Sequence

PASSWORD_KEY = "email_report_smtp_password"
FREQUENCIES = ("off", "daily", "every_3_days", "weekly")
DEFAULT_FREQUENCY = "weekly"
RETRY_COOLDOWN_SEC = 30 * 60
SMTP_TIMEOUT_SEC = 20

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_log = logging.getLogger("pc_cleaner.email_report")


def normalize_frequency(value: Any) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "tat": "off",
        "tắt": "off",
        "none": "off",
        "disabled": "off",
        "hang ngay": "daily",
        "hằng ngày": "daily",
        "day": "daily",
        "3": "every_3_days",
        "3d": "every_3_days",
        "every3days": "every_3_days",
        "moi 3 ngay": "every_3_days",
        "mỗi 3 ngày": "every_3_days",
        "hang tuan": "weekly",
        "hằng tuần": "weekly",
        "week": "weekly",
    }
    raw = aliases.get(raw, raw)
    if raw in FREQUENCIES:
        return raw
    return DEFAULT_FREQUENCY


def parse_local_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        stamp = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", ""))
        except ValueError:
            return None
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone().replace(tzinfo=None)
    return stamp.replace(microsecond=0)


def preferred_clock(hour: Any, minute: Any) -> time:
    try:
        h = int(hour)
    except (TypeError, ValueError):
        h = 8
    try:
        m = int(minute)
    except (TypeError, ValueError):
        m = 0
    return time(min(23, max(0, h)), min(59, max(0, m)))


def _iso_week(stamp: datetime) -> tuple:
    iso = stamp.isocalendar()
    return (int(iso[0]), int(iso[1]))


def _iso(stamp: datetime) -> str:
    return stamp.replace(microsecond=0).isoformat(timespec="seconds")


def looks_like_email(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > 254:
        return False
    return _EMAIL_RE.fullmatch(text) is not None


def clean_host(value: Any) -> str:
    host = str(value or "").strip()
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host, flags=re.IGNORECASE)
    host = host.split("/")[0].strip()
    return host


def _as_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return 0
    if port < 1 or port > 65535:
        return 0
    return port


def read_settings(config_manager: Any) -> Dict[str, Any]:
    getter = getattr(config_manager, "get", None)
    data = config_manager if isinstance(config_manager, dict) else None

    def g(key: str, default: Any = None) -> Any:
        if getter is not None:
            return getter(key, default)
        if data is not None:
            return data.get(key, default)
        return default

    return {
        "enabled": bool(g("email_report_enabled", False)),
        "to": str(g("email_report_to", "") or "").strip(),
        "frequency": normalize_frequency(g("email_report_frequency", DEFAULT_FREQUENCY)),
        "hour": preferred_clock(g("email_report_send_hour", 8), 0).hour,
        "minute": preferred_clock(0, g("email_report_send_minute", 0)).minute,
        "host": clean_host(g("email_report_smtp_host", "")),
        "port": _as_port(g("email_report_smtp_port", 587)) or 0,
        "username": str(g("email_report_smtp_username", "") or "").strip(),
        "password": str(g(PASSWORD_KEY, "") or ""),
        "use_tls": bool(g("email_report_smtp_use_tls", True)),
        "use_ssl": bool(g("email_report_smtp_use_ssl", False)),
        "from_name": str(g("email_report_from_name", "") or "").strip(),
        "from_address": str(g("email_report_from_address", "") or "").strip(),
        "last_sent_at": str(g("email_report_last_sent_at", "") or ""),
        "last_attempt_at": str(g("email_report_last_attempt_at", "") or ""),
        "last_error": str(g("email_report_last_error", "") or ""),
    }


def credentials_ready(settings: Dict[str, Any]) -> bool:
    if not looks_like_email(settings.get("to")):
        return False
    if not str(settings.get("host") or "").strip():
        return False
    if _as_port(settings.get("port")) <= 0:
        return False
    if not str(settings.get("username") or "").strip():
        return False
    if not str(settings.get("password") or "").strip():
        return False
    from_addr = str(settings.get("from_address") or "").strip()
    if from_addr and not looks_like_email(from_addr):
        return False
    return True


def frequency_window_already_sent(
    last_sent: Optional[datetime],
    now: datetime,
    frequency: str,
) -> bool:
    """True when a successful send already covers this frequency window."""
    if last_sent is None:
        return False
    freq = normalize_frequency(frequency)
    if freq == "off":
        return True
    if freq == "daily":
        return last_sent.date() == now.date()
    if freq == "every_3_days":
        return (now.date() - last_sent.date()).days < 3
    return _iso_week(last_sent) == _iso_week(now)


def send_clock_reached(
    now: datetime,
    preferred: time,
    last_sent: Optional[datetime],
    frequency: str,
) -> bool:
    freq = normalize_frequency(frequency)
    if freq == "off":
        return False
    if freq == "every_3_days" and last_sent is not None:
        due_date = last_sent.date() + timedelta(days=3)
        if now.date() > due_date:
            return True
        if now.date() == due_date:
            return now.time() >= preferred
        return False
    return now.time() >= preferred


def report_is_due(settings: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Whether a scheduled send should leave this PC now.

    Disabled, incomplete SMTP, frequency off, a send already in this window,
    a clock time that has not arrived, or a recent failed attempt all return
    False. Nothing is logged.
    """
    if not settings.get("enabled"):
        return False
    if not credentials_ready(settings):
        return False
    freq = normalize_frequency(settings.get("frequency"))
    if freq == "off":
        return False
    stamp = now or datetime.now()
    last = parse_local_dt(settings.get("last_sent_at"))
    if frequency_window_already_sent(last, stamp, freq):
        return False
    if not send_clock_reached(stamp, preferred_clock(settings.get("hour"), settings.get("minute")), last, freq):
        return False
    attempt = parse_local_dt(settings.get("last_attempt_at"))
    if attempt is not None:
        elapsed = (stamp - attempt).total_seconds()
        if 0 <= elapsed < RETRY_COOLDOWN_SEC:
            return False
    return True


def scheduled_report_due(config_manager: Any, now: Optional[datetime] = None) -> bool:
    return report_is_due(read_settings(config_manager), now=now or datetime.now())


def validate_for_test(settings: Dict[str, Any]) -> str:
    """Vietnamese reason a manual test must not be sent. Empty means OK."""
    if not settings.get("enabled"):
        return "Báo cáo email đang tắt. Hãy bật rồi thử lại."
    if not looks_like_email(settings.get("to")):
        return "Địa chỉ email nhận chưa hợp lệ."
    if not str(settings.get("host") or "").strip():
        return "Chưa nhập máy chủ SMTP."
    if _as_port(settings.get("port")) <= 0:
        return "Cổng SMTP không hợp lệ."
    if not str(settings.get("username") or "").strip():
        return "Chưa nhập tên đăng nhập SMTP."
    if not str(settings.get("password") or "").strip():
        return "Chưa có mật khẩu SMTP. Nhập mật khẩu ứng dụng rồi thử lại."
    from_addr = str(settings.get("from_address") or "").strip()
    if from_addr and not looks_like_email(from_addr):
        return "Địa chỉ người gửi chưa hợp lệ."
    return ""


def classify_smtp_error(exc: BaseException) -> str:
    """Map an SMTP failure to Vietnamese. Never includes the server payload."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "SMTP từ chối đăng nhập. Kiểm tra tên đăng nhập và mật khẩu ứng dụng."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "Máy chủ từ chối địa chỉ email nhận. Kiểm tra hộp thư người nhận."
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "Máy chủ từ chối địa chỉ gửi. Kiểm tra tên đăng nhập hoặc địa chỉ From."
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "Hết thời gian chờ kết nối SMTP. Kiểm tra mạng, máy chủ và cổng."
    if isinstance(exc, socket.gaierror):
        return "Không phân giải được tên máy chủ SMTP. Kiểm tra địa chỉ host."
    if isinstance(exc, smtplib.SMTPConnectError):
        return "Không kết nối được máy chủ SMTP. Kiểm tra host, cổng và mạng."
    if isinstance(exc, ConnectionRefusedError):
        return "Máy chủ SMTP từ chối kết nối. Kiểm tra cổng và tường lửa."
    if isinstance(exc, OSError):
        return "Lỗi mạng khi gửi thư. Kiểm tra kết nối và cấu hình SMTP."
    if isinstance(exc, smtplib.SMTPException):
        return "Gửi thư SMTP không thành công. Kiểm tra lại cấu hình."
    return "Không gửi được thư. Thử lại sau."


def _strip_secrets(text: str, extra: Sequence[str] = ()) -> str:
    raw = str(text or "")
    try:
        from core.companion_diary import configured_secret_values, redact_sensitive
        raw = redact_sensitive(raw)
        values = list(configured_secret_values())
    except Exception:
        values = []
    values.extend(str(item) for item in extra if item)
    for secret in sorted({v.strip() for v in values if v and len(str(v).strip()) >= 4}, key=len, reverse=True):
        if secret in raw:
            raw = raw.replace(secret, "[redacted]")
    return raw


def _fmt_num(value: Any, digits: int = 1) -> Optional[str]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:
        return None
    if abs(num - round(num)) < 0.05:
        return str(int(round(num)))
    return f"{num:.{digits}f}"


def _machine_lines(snapshots: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(snapshots, dict):
        return []
    lines: List[str] = []
    disk = snapshots.get("disk") if isinstance(snapshots.get("disk"), dict) else None
    if disk is not None:
        total = _fmt_num(disk.get("total_gb"))
        free = _fmt_num(disk.get("free_gb"))
        used = _fmt_num(disk.get("percent"))
        try:
            total_raw = float(disk.get("total_gb") or 0)
        except (TypeError, ValueError):
            total_raw = 0
        if total and total_raw > 0 and free is not None:
            drive = str(disk.get("drive") or "ổ đĩa").strip() or "ổ đĩa"
            piece = f"{drive}: còn {free} GB trống / {total} GB"
            if used is not None:
                piece += f" (đã dùng {used}%)"
            lines.append(piece + ".")
    ram = snapshots.get("ram") if isinstance(snapshots.get("ram"), dict) else None
    if ram is not None:
        used_gb = _fmt_num(ram.get("used_gb"))
        total_gb = _fmt_num(ram.get("total_gb"))
        percent = _fmt_num(ram.get("percent"))
        try:
            total_raw = float(ram.get("total_gb") or 0)
        except (TypeError, ValueError):
            total_raw = 0
        if used_gb and total_gb and total_raw > 0:
            piece = f"RAM đang dùng {used_gb} / {total_gb} GB"
            if percent is not None:
                piece += f" ({percent}%)"
            lines.append(piece + ".")
    net = snapshots.get("network") if isinstance(snapshots.get("network"), dict) else None
    if net is not None:
        measured = bool(net.get("ping_measured"))
        try:
            ping = float(net.get("ping_ms"))
        except (TypeError, ValueError):
            ping = -1.0
        if measured and ping > 0:
            ping_txt = _fmt_num(ping) or str(ping)
            lines.append(f"Độ trễ TCP: {ping_txt} ms.")
        adapter = str(net.get("adapter") or "").strip()
        if adapter:
            lines.append(f"Card mạng: {adapter}.")
        try:
            down_bps = float(net.get("down_bps") or 0)
            up_bps = float(net.get("up_bps") or 0)
        except (TypeError, ValueError):
            down_bps = up_bps = 0.0
        if down_bps > 0 or up_bps > 0:
            down = str(net.get("down_speed_str") or "").strip() or f"{down_bps:.0f} B/s"
            up = str(net.get("up_speed_str") or "").strip() or f"{up_bps:.0f} B/s"
            lines.append(f"Tốc độ lúc đo: xuống {down}, lên {up}.")
    thermal = snapshots.get("thermal") if isinstance(snapshots.get("thermal"), dict) else None
    if thermal is not None and thermal.get("available") and thermal.get("hottest_celsius") is not None:
        hottest = _fmt_num(thermal.get("hottest_celsius"))
        if hottest is not None:
            label = str(thermal.get("hottest_label") or "").strip()
            status = str(thermal.get("status_label") or "").strip()
            piece = f"Nhiệt cao nhất đo được: {hottest}°C"
            if label:
                piece += f" ({label})"
            if status:
                piece += f" — {status}"
            lines.append(piece + ".")
    wifi = snapshots.get("wifi") if isinstance(snapshots.get("wifi"), dict) else None
    if wifi is not None and wifi.get("is_wifi"):
        bits = []
        ssid = str(wifi.get("ssid") or "").strip()
        signal = str(wifi.get("signal") or "").strip()
        cause = str(wifi.get("cause_label") or "").strip()
        if ssid:
            bits.append(f"SSID {ssid}")
        if signal:
            bits.append(f"tín hiệu {signal}")
        try:
            mbps = float(wifi.get("link_mbps") or 0)
        except (TypeError, ValueError):
            mbps = 0.0
        if mbps > 0:
            bits.append(f"liên kết {_fmt_num(mbps) or mbps} Mbps")
        if cause:
            bits.append(cause)
        if bits:
            lines.append("Wi-Fi: " + ", ".join(bits) + ".")
    return lines


def collect_live_snapshots() -> Dict[str, Any]:
    """Read monitors already on this PC. Missing probes are omitted."""
    out: Dict[str, Any] = {}
    try:
        from core.system_monitor import SystemMonitor
        disk = SystemMonitor.get_disk_info("C:\\")
        try:
            total = float((disk or {}).get("total_gb") or 0)
        except (TypeError, ValueError):
            total = 0
        if total <= 0:
            disk = SystemMonitor.get_disk_info("/")
            try:
                total = float((disk or {}).get("total_gb") or 0)
            except (TypeError, ValueError):
                total = 0
        if total > 0 and isinstance(disk, dict):
            out["disk"] = disk
        ram = SystemMonitor.get_ram_info()
        try:
            ram_total = float((ram or {}).get("total_gb") or 0)
        except (TypeError, ValueError):
            ram_total = 0
        if ram_total > 0 and isinstance(ram, dict):
            out["ram"] = ram
        net = SystemMonitor.get_network_info()
        if isinstance(net, dict):
            useful = bool(net.get("ping_measured")) or bool(str(net.get("adapter") or "").strip())
            try:
                useful = useful or float(net.get("down_bps") or 0) > 0 or float(net.get("up_bps") or 0) > 0
            except (TypeError, ValueError):
                pass
            if useful:
                out["network"] = net
    except Exception:
        pass
    try:
        from core.thermal_monitor import peek_cached_snapshot
        snap = peek_cached_snapshot()
        if isinstance(snap, dict) and snap.get("available") and snap.get("hottest_celsius") is not None:
            out["thermal"] = snap
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            from core.wifi_recovery import WifiRecovery
            wifi = WifiRecovery.detect_wifi_instability(include_events=False)
            if isinstance(wifi, dict) and wifi.get("is_wifi"):
                out["wifi"] = wifi
        except Exception:
            pass
    return out


def _weekly_digest_lines(base_dir: Optional[str]) -> List[str]:
    try:
        from core.companion_reflection import WEEKLY_MARKER, load_reflection
        text = load_reflection(base_dir)
    except Exception:
        return []
    if WEEKLY_MARKER not in text:
        return []
    block = (WEEKLY_MARKER + text.split(WEEKLY_MARKER, 1)[1]).split("\n\n", 1)[0].strip()
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    joined = " ".join(lines)
    if "chưa có diễn biến" in joined and "Trong tuần" not in joined:
        return []
    return lines[:8]


def _diary_counts(events: Sequence[Dict[str, Any]], now: datetime) -> Dict[str, int]:
    rough = 0
    try:
        from core.companion_moment import machine_stress_active
        for offset in range(7):
            day = (now - timedelta(days=offset)).replace(hour=12, minute=0, second=0, microsecond=0)
            if machine_stress_active(list(events), day):
                rough += 1
    except Exception:
        rough = 0
    try:
        from core.companion_diary import event_weight
    except Exception:
        def event_weight(item: Dict[str, Any]) -> int:
            return 1
    started = 0
    ended = 0
    for item in events:
        kind = str(item.get("kind") or "")
        weight = event_weight(item)
        if kind == "focus_mode":
            started += weight
        elif kind == "focus_end":
            ended += weight
    return {"rough_days": rough, "focus_started": started, "focus_ended": ended}


def _companion_lines(base_dir: Optional[str], now: datetime) -> List[str]:
    lines: List[str] = []
    model_counts = False
    try:
        from core.companion_learning import load_daily_model, weekly_learn_line
        learned = weekly_learn_line(now=now, base_dir=base_dir)
        if learned:
            lines.append(learned)
        model = load_daily_model(base_dir)
        learned_on = parse_local_dt(str(model.get("date") or "") + "T12:00:00")
        fresh = learned_on is not None and (now.date() - learned_on.date()).days <= 7
        rough = int(model.get("rough_days") or 0) if fresh else 0
        focus = int(model.get("focus_sessions") or 0) if fresh else 0
        if rough > 0 or focus > 0:
            bits = []
            if rough > 0:
                bits.append(f"{rough} ngày hơi nặng")
            if focus > 0:
                bits.append(f"{focus} lần Trước thi / họp")
            lines.append("Sổ học đã lưu trên máy này: " + ", ".join(bits) + ".")
            model_counts = True
    except Exception:
        model_counts = False
    digest = _weekly_digest_lines(base_dir)
    if digest:
        lines.append("Tóm tắt tuần đã ghi:")
        lines.extend(digest)
    events: List[Dict[str, Any]] = []
    try:
        from core.companion_diary import format_digest, recent_events
        events = recent_events(days=7, limit=0, base_dir=base_dir, now=now)
        if events and not digest:
            bullet_text = format_digest(events, limit=4, now=now)
            if bullet_text and "còn trống" not in bullet_text:
                lines.append("Nhật ký gần đây:")
                lines.extend(bullet_text.splitlines())
    except Exception:
        events = []
    if events and not model_counts:
        counts = _diary_counts(events, now)
        if counts["rough_days"] > 0:
            lines.append(
                f"Ngày máy nặng (ít nhất hai nhóm cảnh báo cùng ngày): {counts['rough_days']}."
            )
        focus_bits = []
        if counts["focus_started"] > 0:
            focus_bits.append(f"{counts['focus_started']} lần bật")
        if counts["focus_ended"] > 0:
            focus_bits.append(f"{counts['focus_ended']} phiên đã kết thúc")
        if focus_bits:
            lines.append("Trước thi / họp: " + ", ".join(focus_bits) + ".")
    try:
        from core.companion_skills import load_skills
        titles = []
        for skill in load_skills(base_dir)[:4]:
            title = str(getattr(skill, "title", "") or "").strip()
            if title and title not in titles:
                titles.append(title)
        if titles:
            lines.append("Đã ghi nhận trên máy này: " + "; ".join(titles) + ".")
    except Exception:
        pass
    return lines


def build_report(
    *,
    now: Optional[datetime] = None,
    snapshots: Optional[Dict[str, Any]] = None,
    base_dir: Optional[str] = None,
    redact_values: Sequence[str] = (),
    app_version: str = "",
) -> Dict[str, Any]:
    """Plain text + simple HTML. Sections with no data are left out."""
    stamp = now or datetime.now()
    if snapshots is None:
        snapshots = collect_live_snapshots()
    sections: List[Dict[str, Any]] = []
    machine = _machine_lines(snapshots)
    if machine:
        sections.append({"title": "Máy lúc gửi", "lines": machine})
    companion = _companion_lines(base_dir, stamp)
    if companion:
        sections.append({"title": "Ghi nhận trên máy này", "lines": companion})
    version = str(app_version or "").strip()
    if not version:
        try:
            from app_meta import APP_VERSION
            version = str(APP_VERSION or "").strip()
        except Exception:
            version = ""
    intro = f"Báo cáo lúc {stamp.strftime('%H:%M %d/%m/%Y')} (giờ máy)."
    if version:
        intro += f" PC Auto Cleaner & Optimizer {version}."
    footer = "Thư gửi từ ứng dụng trên máy này, không qua máy chủ mail của ứng dụng."
    if not sections:
        sections.append({
            "title": "Máy lúc gửi",
            "lines": ["Chưa có số liệu đo được trên máy này để đưa vào báo cáo."],
        })
    intro = _strip_secrets(intro, redact_values)
    footer = _strip_secrets(footer, redact_values)
    for section in sections:
        section["title"] = _strip_secrets(section["title"], redact_values)
        section["lines"] = [_strip_secrets(str(line), redact_values) for line in section["lines"]]
    text_parts = [intro, ""]
    for section in sections:
        text_parts.append(section["title"])
        text_parts.extend(section["lines"])
        text_parts.append("")
    text_parts.append(footer)
    text = "\n".join(text_parts).strip() + "\n"
    html_parts = [
        "<!DOCTYPE html><html><body style=\"font-family:sans-serif;font-size:14px;color:#0f172a\">",
        f"<p>{html.escape(intro)}</p>",
    ]
    for section in sections:
        html_parts.append(f"<h3>{html.escape(section['title'])}</h3>")
        items = []
        paragraphs = []
        for line in section["lines"]:
            raw_line = str(line)
            if raw_line.startswith("- "):
                items.append(f"<li>{html.escape(raw_line[2:])}</li>")
            else:
                if items:
                    paragraphs.append("<ul>" + "".join(items) + "</ul>")
                    items = []
                paragraphs.append(f"<p>{html.escape(raw_line)}</p>")
        if items:
            paragraphs.append("<ul>" + "".join(items) + "</ul>")
        html_parts.extend(paragraphs)
    html_parts.append(f"<p>{html.escape(footer)}</p></body></html>")
    html_body = "".join(html_parts)
    subject = f"Báo cáo máy tính {stamp.strftime('%d/%m/%Y %H:%M')}"
    return {
        "subject": _strip_secrets(subject, redact_values),
        "text": text,
        "html": html_body,
        "sections": sections,
    }


def build_test_content(*, now: Optional[datetime] = None) -> Dict[str, str]:
    stamp = now or datetime.now()
    text = (
        "Đây là thư thử từ PC Auto Cleaner & Optimizer trên máy này.\n"
        f"Gửi lúc {stamp.strftime('%H:%M %d/%m/%Y')} (giờ máy).\n"
        "Nếu bạn nhận được thư, cấu hình SMTP đã dùng được.\n"
        "Mật khẩu chỉ nằm trên máy này; ứng dụng không có máy chủ mail riêng.\n"
    )
    body = (
        "<!DOCTYPE html><html><body style=\"font-family:sans-serif;font-size:14px\">"
        f"<p>{html.escape(text).replace(chr(10), '<br>')}</p></body></html>"
    )
    return {
        "subject": "Thử gửi báo cáo — PC Auto Cleaner",
        "text": text,
        "html": body,
    }


def build_message(settings: Dict[str, Any], *, subject: str, text: str, html_body: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    from_addr = str(settings.get("from_address") or settings.get("username") or "").strip()
    name = str(settings.get("from_name") or "").strip()
    msg["From"] = formataddr((name, from_addr)) if name else from_addr
    msg["To"] = str(settings.get("to") or "").strip()
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    return msg


def send_smtp_message(
    settings: Dict[str, Any],
    message: EmailMessage,
    *,
    smtp_factory: Optional[Callable] = None,
    smtp_ssl_factory: Optional[Callable] = None,
    timeout: float = SMTP_TIMEOUT_SEC,
) -> None:
    host = str(settings.get("host") or "").strip()
    port = _as_port(settings.get("port"))
    use_ssl = bool(settings.get("use_ssl"))
    use_tls = bool(settings.get("use_tls")) and not use_ssl
    factory_ssl = smtp_ssl_factory or smtplib.SMTP_SSL
    factory = smtp_factory or smtplib.SMTP
    if use_ssl:
        client = factory_ssl(host, port, timeout=timeout)
    else:
        client = factory(host, port, timeout=timeout)
    try:
        client.ehlo()
        if use_tls:
            client.starttls()
            client.ehlo()
        username = str(settings.get("username") or "")
        password = str(settings.get("password") or "")
        if username:
            client.login(username, password)
        client.send_message(message)
    finally:
        try:
            client.quit()
        except Exception:
            try:
                client.close()
            except Exception:
                pass


def _mask_email(value: str) -> str:
    text = str(value or "").strip()
    if "@" not in text:
        return "người nhận"
    local, _, domain = text.partition("@")
    if len(local) <= 1:
        hidden = "*"
    else:
        hidden = local[0] + "***"
    return hidden + "@" + domain


def _safe_message(message: str, password: str) -> str:
    text = str(message or "").strip()
    secret = str(password or "")
    if secret and len(secret) >= 4 and secret in text:
        text = text.replace(secret, "")
    return text.strip() or "Không gửi được thư. Thử lại sau."


def _persist(config_manager: Any, key: str, value: Any) -> None:
    if hasattr(config_manager, "config") and hasattr(config_manager, "save_config"):
        config_manager.config[key] = value
        config_manager.save_config()
        return
    if hasattr(config_manager, "set"):
        config_manager.set(key, value)


def _result(ok: bool, message_vi: str, *, skipped: bool = False) -> Dict[str, Any]:
    return {"ok": ok, "skipped": skipped, "message_vi": message_vi}


def send_test_email(
    config_manager: Any,
    *,
    now: Optional[datetime] = None,
    smtp_factory: Optional[Callable] = None,
    smtp_ssl_factory: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Send a short test now. Does not consume the scheduled window."""
    settings = read_settings(config_manager)
    problem = validate_for_test(settings)
    if problem:
        return _result(False, problem)
    stamp = now or datetime.now()
    content = build_test_content(now=stamp)
    message = build_message(
        settings,
        subject=content["subject"],
        text=content["text"],
        html_body=content["html"],
    )
    try:
        send_smtp_message(
            settings,
            message,
            smtp_factory=smtp_factory,
            smtp_ssl_factory=smtp_ssl_factory,
        )
    except Exception as exc:
        msg = _safe_message(classify_smtp_error(exc), settings.get("password") or "")
        _log.info("email test failed for %s: %s", _mask_email(settings.get("to") or ""), msg)
        return _result(False, msg)
    _log.info("email test sent to %s", _mask_email(settings.get("to") or ""))
    return _result(True, "Đã gửi thư thử. Kiểm tra hộp thư đến (và thư rác).")


def send_scheduled_report(
    config_manager: Any,
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    snapshots: Optional[Dict[str, Any]] = None,
    smtp_factory: Optional[Callable] = None,
    smtp_ssl_factory: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Send one report if the frequency window is open. Quiet when it is not."""
    stamp = now or datetime.now()
    settings = read_settings(config_manager)
    if not report_is_due(settings, now=stamp):
        return _result(False, "", skipped=True)
    _persist(config_manager, "email_report_last_attempt_at", _iso(stamp))
    try:
        report = build_report(
            now=stamp,
            snapshots=snapshots,
            base_dir=base_dir,
            redact_values=[settings.get("password") or ""],
        )
        message = build_message(
            settings,
            subject=report["subject"],
            text=report["text"],
            html_body=report["html"],
        )
        send_smtp_message(
            settings,
            message,
            smtp_factory=smtp_factory,
            smtp_ssl_factory=smtp_ssl_factory,
        )
    except Exception as exc:
        msg = _safe_message(classify_smtp_error(exc), settings.get("password") or "")
        _persist(config_manager, "email_report_last_error", msg)
        _log.info("email report failed for %s: %s", _mask_email(settings.get("to") or ""), msg)
        return _result(False, msg)
    _persist(config_manager, "email_report_last_sent_at", _iso(stamp))
    _persist(config_manager, "email_report_last_error", "")
    _log.info("email report sent to %s", _mask_email(settings.get("to") or ""))
    return _result(True, "Đã gửi báo cáo qua email.")
