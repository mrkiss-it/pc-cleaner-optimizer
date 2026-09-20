"""
core/update_installer.py – Tải asset GitHub Release và chạy bộ cài (chỉ khi user bấm Cập nhật).

- Không cần token cho release công khai (browser_download_url).
- Không cài im lặng nền; không ghi đè exe đang chạy.
- Setup wizard (PCAutoCleaner_Setup.exe) không có cờ silent — mở UI bình thường.
- Inno Setup hỗ trợ /SILENT nhưng không dùng: ghi đè khi app còn chạy là không an toàn.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.update_checker import USER_AGENT, current_app_version, GITHUB_OWNER, GITHUB_REPO

DOWNLOAD_TIMEOUT_SEC = 60.0
CHUNK_SIZE = 64 * 1024
CACHE_DIRNAME = "PCAutoCleaner"
CACHE_SUBDIR = "updates"

ProgressCb = Callable[[int, int], None]
CancelCheck = Callable[[], bool]
UrlOpen = Callable[..., Any]
PopenFn = Callable[..., Any]


@dataclass
class DownloadResult:
    ok: bool
    path: str = ""
    error: str = ""  # offline|http|http_404|http_403|disk_full|size_mismatch|sha_mismatch|cancelled|invalid|error
    message: str = ""
    bytes_written: int = 0
    expected_size: int = 0
    skipped_existing: bool = False
    http_status: int = 0


@dataclass
class LaunchResult:
    ok: bool
    message: str = ""
    action: str = ""  # installer|folder|none
    should_close: bool = False
    path: str = ""


def vietnamese_download_error(code: str, status: int = 0) -> str:
    messages = {
        "offline": "Không tải được bản cập nhật (mất mạng). Thử lại sau.",
        "http_404": "Không tìm thấy file cài trên GitHub (mã 404).",
        "http_403": "GitHub từ chối tải file (mã 403). Sẽ mở trang Releases.",
        "http": "Máy chủ GitHub trả lỗi khi tải. Thử lại sau.",
        "disk_full": "Không đủ dung lượng đĩa để lưu bản cập nhật.",
        "size_mismatch": "File tải về không khớp kích thước — có thể tải dở. Thử lại.",
        "sha_mismatch": "File tải về không khớp mã SHA. Đã hủy cài đặt.",
        "cancelled": "Đã hủy tải bản cập nhật.",
        "invalid": "Không có file cài để tải trên bản phát hành này.",
        "error": "Không tải được bản cập nhật. Thử lại sau.",
    }
    text = messages.get(code, messages["error"])
    if code == "http" and status:
        return f"Máy chủ GitHub trả lỗi {status} khi tải. Thử lại sau."
    return text


def format_bytes(n: int) -> str:
    try:
        value = max(0, int(n or 0))
    except (TypeError, ValueError):
        value = 0
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"


def parse_asset_digest(raw: str) -> Tuple[str, str]:
    """Trả về (algo, hex). Chỉ hỗ trợ SHA-256. Chuỗi lạ → ('', '')."""
    text = (raw or "").strip()
    if not text:
        return "", ""
    lower = text.lower().strip()
    hex_part = ""
    if lower.startswith("sha256:"):
        hex_part = lower.split(":", 1)[1].strip()
    elif lower.startswith("sha256-"):
        hex_part = lower.split("-", 1)[1].strip()
    elif re.fullmatch(r"[0-9a-f]{64}", lower):
        hex_part = lower
    else:
        return "", ""
    hex_part = hex_part.replace(" ", "")
    if not re.fullmatch(r"[0-9a-f]{64}", hex_part):
        return "", ""
    return "sha256", hex_part


def safe_asset_filename(name: str) -> str:
    base = os.path.basename((name or "").replace("\\", "/").strip())
    cleaned = re.sub(r"[^\w.\-()+ ]+", "_", base).strip(" ._")
    return cleaned or "PCAutoCleaner_Setup.exe"


def _safe_tag_folder(tag: str) -> str:
    text = re.sub(r"[^\w.\-]+", "_", (tag or "").strip())
    return text.strip("._") or "latest"


def update_cache_dir() -> str:
    """Thư mục cache tải: %LOCALAPPDATA%/PCAutoCleaner/updates (hoặc temp)."""
    base = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("XDG_CACHE_HOME")
        or os.environ.get("TEMP")
        or tempfile.gettempdir()
    )
    path = os.path.join(base, CACHE_DIRNAME, CACHE_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def resolve_download_path(asset_name: str, tag: str = "") -> str:
    folder = os.path.join(update_cache_dir(), _safe_tag_folder(tag))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, safe_asset_filename(asset_name))


def _is_disk_full(exc: BaseException) -> bool:
    if not isinstance(exc, OSError):
        return False
    if getattr(exc, "errno", None) in (errno.ENOSPC, errno.EFBIG):
        return True
    if getattr(exc, "winerror", None) == 112:
        return True
    msg = str(exc).lower()
    return "no space" in msg or "disk full" in msg or "not enough space" in msg


def _fail(
    code: str,
    path: str = "",
    status: int = 0,
    written: int = 0,
    expected: int = 0,
) -> DownloadResult:
    return DownloadResult(
        ok=False,
        path=path,
        error=code,
        message=vietnamese_download_error(code, status),
        bytes_written=written,
        expected_size=expected,
        http_status=status,
    )


def _sha256_file(path: str, chunk_size: int = CHUNK_SIZE) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def verify_downloaded_file(
    path: str,
    expected_size: int = 0,
    expected_digest: str = "",
) -> Tuple[bool, str]:
    """Kiểm tra file đã tải: tồn tại, size (nếu có), SHA-256 (nếu release cung cấp)."""
    if not path or not os.path.isfile(path):
        return False, "error"
    try:
        actual = os.path.getsize(path)
    except OSError:
        return False, "error"
    if actual <= 0:
        return False, "error"
    if expected_size and actual != int(expected_size):
        return False, "size_mismatch"
    algo, hexdigest = parse_asset_digest(expected_digest)
    if algo == "sha256" and hexdigest:
        try:
            if _sha256_file(path) != hexdigest:
                return False, "sha_mismatch"
        except OSError:
            return False, "error"
    return True, ""


def _download_headers() -> Dict[str, str]:
    return {
        "Accept": "application/octet-stream",
        "User-Agent": USER_AGENT.format(
            version=current_app_version(),
            owner=GITHUB_OWNER,
            repo=GITHUB_REPO,
        ),
    }


def download_release_asset(
    url: str,
    dest_path: str,
    expected_size: int = 0,
    expected_digest: str = "",
    timeout: float = DOWNLOAD_TIMEOUT_SEC,
    chunk_size: int = CHUNK_SIZE,
    progress_cb: Optional[ProgressCb] = None,
    cancel_check: Optional[CancelCheck] = None,
    urlopen: Optional[UrlOpen] = None,
) -> DownloadResult:
    """
    Tải browser_download_url vào dest_path (ghi .part rồi đổi tên).
    urlopen injectable — unit test không mạng thật.
    """
    target = (url or "").strip()
    dest = (dest_path or "").strip()
    expect = max(0, int(expected_size or 0))
    if not target or not dest:
        return _fail("invalid")

    try:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    except OSError as exc:
        return _fail("disk_full" if _is_disk_full(exc) else "error", path=dest, expected=expect)

    ok_existing, _existing_err = verify_downloaded_file(dest, expect, expected_digest)
    if ok_existing:
        size = os.path.getsize(dest)
        if progress_cb:
            try:
                progress_cb(size, expect or size)
            except Exception:
                pass
        return DownloadResult(
            ok=True,
            path=dest,
            message="Đã có file tải sẵn, bỏ qua tải lại.",
            bytes_written=size,
            expected_size=expect or size,
            skipped_existing=True,
            http_status=200,
        )

    opener = urlopen or urllib.request.urlopen
    req = urllib.request.Request(target, headers=_download_headers(), method="GET")
    part_path = dest + ".part"
    written = 0
    hasher = hashlib.sha256()
    algo, hexdigest = parse_asset_digest(expected_digest)
    header_len = 0
    total = expect

    try:
        if os.path.isfile(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass

        with opener(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            if status >= 400:
                code = "http_404" if status == 404 else ("http_403" if status == 403 else "http")
                return _fail(code, path=dest, status=status, expected=expect)

            try:
                headers = getattr(resp, "headers", None)
                if headers is not None:
                    header_len = int(headers.get("Content-Length") or headers.get("content-length") or 0)
            except (TypeError, ValueError):
                header_len = 0
            total = expect or header_len

            with open(part_path, "wb") as handle:
                while True:
                    if cancel_check and cancel_check():
                        try:
                            os.remove(part_path)
                        except OSError:
                            pass
                        return _fail("cancelled", path=dest, written=written, expected=expect)
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
                    hasher.update(chunk)
                    if progress_cb:
                        try:
                            progress_cb(written, total)
                        except Exception:
                            pass

        if written <= 0:
            try:
                os.remove(part_path)
            except OSError:
                pass
            return _fail("error", path=dest, expected=expect)

        if expect and written != expect:
            try:
                os.remove(part_path)
            except OSError:
                pass
            return _fail("size_mismatch", path=dest, written=written, expected=expect)

        if not expect and header_len and written != header_len:
            try:
                os.remove(part_path)
            except OSError:
                pass
            return _fail("size_mismatch", path=dest, written=written, expected=header_len)

        if algo == "sha256" and hexdigest and hasher.hexdigest() != hexdigest:
            try:
                os.remove(part_path)
            except OSError:
                pass
            return _fail("sha_mismatch", path=dest, written=written, expected=expect)

        os.replace(part_path, dest)
        if progress_cb:
            try:
                progress_cb(written, total or written)
            except Exception:
                pass
        return DownloadResult(
            ok=True,
            path=dest,
            message=f"Đã tải xong ({format_bytes(written)}).",
            bytes_written=written,
            expected_size=expect or written,
            http_status=200,
        )
    except urllib.error.HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        code = "http_404" if status == 404 else ("http_403" if status == 403 else "http")
        try:
            if os.path.isfile(part_path):
                os.remove(part_path)
        except OSError:
            pass
        return _fail(code, path=dest, status=status, written=written, expected=expect)
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        try:
            if os.path.isfile(part_path):
                os.remove(part_path)
        except OSError:
            pass
        return _fail("offline", path=dest, written=written, expected=expect)
    except OSError as exc:
        try:
            if os.path.isfile(part_path):
                os.remove(part_path)
        except OSError:
            pass
        return _fail(
            "disk_full" if _is_disk_full(exc) else "error",
            path=dest,
            written=written,
            expected=expect,
        )
    except Exception:
        try:
            if os.path.isfile(part_path):
                os.remove(part_path)
        except OSError:
            pass
        return _fail("error", path=dest, written=written, expected=expect)


def uses_quiet_install_flags(filename: str) -> bool:
    """
    Cờ silent chỉ an toàn khi installer hỗ trợ VÀ app không còn giữ file lock.
    Setup wizard tùy chỉnh không đọc argv silent; Inno thì /SILENT không an toàn khi app còn chạy.
    Luôn False — mở UI bộ cài.
    """
    return False


def installer_command(path: str) -> List[str]:
    """Lệnh mở bộ cài (UI thường, không silent)."""
    target = (path or "").strip()
    if not target:
        return []
    name = os.path.basename(target).lower()
    if name.endswith(".msi"):
        return ["msiexec", "/i", target]
    if name.endswith(".exe"):
        return [target]
    return []


def _open_in_file_manager(path: str) -> bool:
    try:
        if os.name == "nt" and hasattr(os, "startfile"):
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        opener = shutil.which("xdg-open") or shutil.which("open")
        if opener:
            subprocess.Popen([opener, path], close_fds=True)
            return True
    except Exception:
        return False
    return False


def _is_unsafe_zip_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[a-zA-Z]:", normalized):
        return True
    parts = [p for p in normalized.split("/") if p]
    return any(p == ".." for p in parts)


def extract_zip_safely(zip_path: str, dest_dir: str) -> Tuple[bool, str]:
    try:
        os.makedirs(dest_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if _is_unsafe_zip_name(info.filename):
                    continue
                zf.extract(info, dest_dir)
        return True, dest_dir
    except zipfile.BadZipFile:
        return False, "Tệp zip tải về bị hỏng."
    except OSError as exc:
        if _is_disk_full(exc):
            return False, vietnamese_download_error("disk_full")
        return False, "Không giải nén được bản portable."
    except Exception:
        return False, "Không giải nén được bản portable."


def find_setup_in_dir(root: str) -> str:
    if not root or not os.path.isdir(root):
        return ""
    hits: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            lower = filename.lower()
            if not lower.endswith(".exe"):
                continue
            if "uninstall" in lower:
                continue
            if "setup" in lower:
                hits.append(os.path.join(dirpath, filename))
    for path in hits:
        if os.path.basename(path).lower() == "pcautocleaner_setup.exe":
            return path
    return hits[0] if hits else ""


def _popen_detached(cmd: List[str], popen: Optional[PopenFn] = None) -> None:
    launcher = popen or subprocess.Popen
    kwargs: Dict[str, Any] = {
        "close_fds": False,
        "cwd": os.path.dirname(cmd[-1]) or None,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        flags = int(getattr(subprocess, "DETACHED_PROCESS", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        if flags:
            kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    launcher(cmd, **kwargs)


def launch_downloaded_update(
    path: str,
    popen: Optional[PopenFn] = None,
    open_folder: Optional[Callable[[str], bool]] = None,
) -> LaunchResult:
    """
    Chạy Setup.exe / MSI, hoặc giải nén zip portable.
    popen / open_folder injectable cho unit test.
    """
    target = (path or "").strip()
    if not target or not os.path.exists(target):
        return LaunchResult(ok=False, message="Không tìm thấy file đã tải.", action="none")

    lower = target.lower()
    folder_opener = open_folder or _open_in_file_manager

    if lower.endswith(".zip"):
        dest_dir = target[: -len(".zip")] + "_extracted"
        ok, detail = extract_zip_safely(target, dest_dir)
        if not ok:
            return LaunchResult(ok=False, message=detail, action="none", path=target)
        setup = find_setup_in_dir(dest_dir)
        if setup:
            return launch_downloaded_update(setup, popen=popen, open_folder=open_folder)
        if folder_opener(dest_dir):
            return LaunchResult(
                ok=True,
                message="Đã tải bản portable. Hãy giải nén/chạy từ thư mục vừa mở — ứng dụng hiện tại sẽ không tự ghi đè.",
                action="folder",
                should_close=False,
                path=dest_dir,
            )
        return LaunchResult(
            ok=True,
            message=f"Đã giải nén bản portable tại {dest_dir}.",
            action="folder",
            should_close=False,
            path=dest_dir,
        )

    cmd = installer_command(target)
    if not cmd:
        if folder_opener(os.path.dirname(target) or target):
            return LaunchResult(
                ok=True,
                message="Đã mở thư mục chứa file tải về.",
                action="folder",
                should_close=False,
                path=target,
            )
        return LaunchResult(ok=False, message="Không chạy được file đã tải.", action="none", path=target)

    try:
        _popen_detached(cmd, popen=popen)
    except Exception:
        return LaunchResult(
            ok=False,
            message="Không mở được trình cài đặt. Hãy chạy file đã tải thủ công.",
            action="none",
            path=target,
        )

    name = os.path.basename(target)
    return LaunchResult(
        ok=True,
        message=f"Đã mở trình cài đặt {name}. Hãy đóng ứng dụng để Windows ghi đè file đang chạy.",
        action="installer",
        should_close=True,
        path=target,
    )
