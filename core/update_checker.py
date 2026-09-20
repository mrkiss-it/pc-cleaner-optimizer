"""
core/update_checker.py – Kiểm tra bản GitHub Release mới (không cài im lặng).

- Gọi GitHub Releases API công khai (không bắt buộc token).
- So sánh tag/version với phiên bản đang chạy.
- Cache kết quả + ETag để tôn trọng rate limit.
- Lỗi 403 / offline / JSON hỏng: thất bại im lặng.
- Chọn asset tải (Setup.exe / zip) kèm size + digest; UI chỉ tải khi người dùng bấm Cập nhật.
- Không ghi đè file .exe đang chạy từ đây — luồng cài nằm ở core/update_installer.py.
"""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app_meta import (
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
    PREFERRED_SETUP_ASSET,
)

GITHUB_API_LATEST = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
GITHUB_RELEASES_PAGE = "https://github.com/{owner}/{repo}/releases"
GITHUB_RELEASES_LATEST_PAGE = "https://github.com/{owner}/{repo}/releases/latest"

DEFAULT_TIMEOUT_SEC = 8.0
DEFAULT_CACHE_TTL_SEC = 6 * 3600  # 6 giờ
USER_AGENT = "PCAutoCleaner/{version} (+https://github.com/{owner}/{repo})"

# Tên asset ưu tiên (không phân biệt hoa thường), theo thứ tự.
ASSET_NAME_PRIORITY = (
    PREFERRED_SETUP_ASSET.lower(),
    "pcautocleaner_setup.exe",
    "pcautocleaner-setup.exe",
    "setup.exe",
)

ENV_APP_VERSION = "PCAUTOCLEANER_APP_VERSION"
ENV_GITHUB_OWNER = "PCAUTOCLEANER_GITHUB_OWNER"
ENV_GITHUB_REPO = "PCAUTOCLEANER_GITHUB_REPO"
ENV_GITHUB_TOKEN = "PCAUTOCLEANER_GITHUB_TOKEN"
ENV_MOCK_JSON = "PCAUTOCLEANER_UPDATE_MOCK_JSON"
ENV_FORCE_NEWER = "PCAUTOCLEANER_UPDATE_FORCE_NEWER"
ENV_SKIP_CHECK = "PCAUTOCLEANER_SKIP_UPDATE_CHECK"

_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:[-_+.]?(.*))?$")
_NUM_IN_TEXT_RE = re.compile(r"(\d+(?:\.\d+)*)")


@dataclass
class FetchResult:
    status: int = 0
    body: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    error: str = ""  # "offline" | "error" | ""


@dataclass(frozen=True)
class AssetPick:
    """Kết quả chọn file trên GitHub Release. name rỗng = chỉ có trang web, không phải file."""
    url: str
    name: str
    size: int = 0
    digest: str = ""


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    version: str
    name: str
    html_url: str
    download_url: str
    asset_name: str
    notes: str
    notes_snippet: str
    is_prerelease: bool = False
    asset_size: int = 0
    asset_digest: str = ""


@dataclass
class UpdateCheckResult:
    ok: bool
    update_available: bool
    current_version: str
    latest: Optional[ReleaseInfo] = None
    message: str = ""
    from_cache: bool = False
    quiet_failure: bool = False
    http_status: int = 0


HttpGet = Callable[[str, Dict[str, str], float], FetchResult]


def current_app_version(fallback: str = APP_VERSION) -> str:
    """Phiên bản đang chạy: env PCAUTOCLEANER_APP_VERSION rồi hằng APP_VERSION."""
    env = os.environ.get(ENV_APP_VERSION, "").strip()
    return env or (fallback or APP_VERSION)


def resolve_repo(
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    cfg = config or {}
    resolved_owner = (
        (owner or "").strip()
        or os.environ.get(ENV_GITHUB_OWNER, "").strip()
        or str(cfg.get("github_owner") or "").strip()
        or GITHUB_OWNER
    )
    resolved_repo = (
        (repo or "").strip()
        or os.environ.get(ENV_GITHUB_REPO, "").strip()
        or str(cfg.get("github_repo") or "").strip()
        or GITHUB_REPO
    )
    return resolved_owner, resolved_repo


def parse_version(raw: str) -> Tuple[Tuple[int, ...], str]:
    """
    Tách 'v3.7.0', '3.7', '3.8.0-beta', 'v3.7.0 Pro' thành ((3,7,0), suffix).
    Chuỗi rỗng / không đọc được → ((0,), '').
    """
    text = (raw or "").strip()
    if not text:
        return (0,), ""
    if text[0] in "vV":
        text = text[1:].lstrip()
    text = text.split()[0].strip()
    if not text:
        return (0,), ""

    match = _VERSION_RE.match(text)
    if not match:
        found = _NUM_IN_TEXT_RE.search(text)
        if not found:
            return (0,), text.lower()
        nums = tuple(int(p) for p in found.group(1).split(".") if p != "")
        return (nums or (0,)), ""

    nums = tuple(int(p) for p in match.group(1).split(".") if p != "")
    suffix = (match.group(2) or "").strip().lower()
    return (nums or (0,)), suffix


def _pad_numeric(left: Tuple[int, ...], right: Tuple[int, ...]) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
    n = max(len(left), len(right), 1)
    return left + (0,) * (n - len(left)), right + (0,) * (n - len(right))


def compare_versions(left: str, right: str) -> int:
    """
    So sánh hai chuỗi phiên bản.
    Trả về -1 nếu left < right, 0 nếu bằng, 1 nếu left > right.
    Bản phát hành (không hậu tố) mới hơn bản pre-release cùng số.
    """
    left_nums, left_suffix = parse_version(left)
    right_nums, right_suffix = parse_version(right)
    left_nums, right_nums = _pad_numeric(left_nums, right_nums)
    if left_nums < right_nums:
        return -1
    if left_nums > right_nums:
        return 1
    if not left_suffix and not right_suffix:
        return 0
    if not left_suffix:
        return 1
    if not right_suffix:
        return -1
    if left_suffix < right_suffix:
        return -1
    if left_suffix > right_suffix:
        return 1
    return 0


def is_newer(latest: str, current: str) -> bool:
    return compare_versions(latest, current) > 0


def snippet_release_notes(body: str, limit: int = 220) -> str:
    if not body or not str(body).strip():
        return "Xem ghi chú phát hành trên GitHub."
    text = str(body).replace("\r\n", "\n").strip()
    pieces: List[str] = []
    for line in text.split("\n"):
        cleaned = line.strip().lstrip("#").strip()
        if cleaned.startswith("```"):
            continue
        if cleaned:
            pieces.append(cleaned)
        if len(" ".join(pieces)) >= limit:
            break
    joined = " ".join(pieces).strip()
    if not joined:
        return "Xem ghi chú phát hành trên GitHub."
    if len(joined) > limit:
        return joined[: max(0, limit - 1)].rstrip() + "…"
    return joined


_DOWNLOADABLE_EXTS = (".exe", ".msi", ".zip")


def is_downloadable_asset(asset_name: str, url: str = "") -> bool:
    """
    True khi đây là file cài/portable công khai (browser_download_url), không phải trang HTML.
    Không dùng URL API GitHub (có thể cần token).
    """
    name = (asset_name or "").strip()
    if not name:
        return False
    lower = name.lower()
    if "uninstall" in lower:
        return False
    if not lower.endswith(_DOWNLOADABLE_EXTS):
        return False
    u = (url or "").strip()
    if not u:
        return False
    ul = u.lower()
    if ul.startswith("https://api.github.com/") or ul.startswith("http://api.github.com/"):
        return False
    if "/releases/download/" in ul:
        return True
    if "/releases/tag/" in ul or ul.rstrip("/").endswith("/releases") or "/releases/latest" in ul:
        return False
    return True


def pick_download_asset_info(
    assets: Optional[List[Dict[str, Any]]],
    html_url: str = "",
    releases_page: str = "",
) -> AssetPick:
    """
    Chọn file tải: ưu tiên PCAutoCleaner_Setup.exe, rồi .exe/.msi/.zip.
    Chỉ lấy browser_download_url (release công khai, không cần token).
    Không có asset → trang Releases; name rỗng.
    """
    fallback = html_url or releases_page
    empty = AssetPick(url=fallback, name="", size=0, digest="")
    items = [a for a in (assets or []) if isinstance(a, dict)]
    if not items:
        return empty

    named: List[Tuple[str, str, int, str]] = []
    for item in items:
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        if not (name and url):
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        digest = str(item.get("digest") or "").strip()
        named.append((name, url, max(0, size), digest))

    if not named:
        return empty

    by_lower = {name.lower(): (name, url, size, digest) for name, url, size, digest in named}

    def _pick(name: str, url: str, size: int, digest: str) -> AssetPick:
        return AssetPick(url=url, name=name, size=size, digest=digest)

    for preferred in ASSET_NAME_PRIORITY:
        hit = by_lower.get(preferred)
        if hit:
            return _pick(*hit)

    for name, url, size, digest in named:
        lower = name.lower()
        if "uninstall" in lower:
            continue
        if lower.endswith(".exe") and "setup" in lower:
            return _pick(name, url, size, digest)

    for name, url, size, digest in named:
        lower = name.lower()
        if "uninstall" in lower:
            continue
        if lower.endswith(".exe"):
            return _pick(name, url, size, digest)

    for name, url, size, digest in named:
        lower = name.lower()
        if lower.endswith(".msi") or lower.endswith(".zip"):
            return _pick(name, url, size, digest)

    return empty


def pick_download_asset(
    assets: Optional[List[Dict[str, Any]]],
    html_url: str = "",
    releases_page: str = "",
) -> Tuple[str, str]:
    """
    Chọn URL tải: ưu tiên PCAutoCleaner_Setup.exe, rồi .exe/.msi/.zip.
    Không có asset → trang Releases (html_url hoặc trang danh sách).
    Trả về (url, asset_name). asset_name rỗng nghĩa là mở trang web, không phải file.
    """
    picked = pick_download_asset_info(assets, html_url=html_url, releases_page=releases_page)
    return picked.url, picked.name


def parse_release_payload(
    data: Dict[str, Any],
    current_version: str = "",
    owner: str = GITHUB_OWNER,
    repo: str = GITHUB_REPO,
) -> Optional[ReleaseInfo]:
    if not isinstance(data, dict) or data.get("draft"):
        return None
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None
    html_url = str(data.get("html_url") or "").strip() or GITHUB_RELEASES_LATEST_PAGE.format(
        owner=owner, repo=repo
    )
    notes = str(data.get("body") or "")
    picked = pick_download_asset_info(
        data.get("assets") if isinstance(data.get("assets"), list) else [],
        html_url=html_url,
        releases_page=GITHUB_RELEASES_PAGE.format(owner=owner, repo=repo),
    )
    version = parse_version(tag)[0]
    version_str = ".".join(str(n) for n in version) if version else tag.lstrip("vV")
    return ReleaseInfo(
        tag=tag,
        version=version_str,
        name=str(data.get("name") or tag).strip() or tag,
        html_url=html_url,
        download_url=picked.url or html_url,
        asset_name=picked.name,
        notes=notes,
        notes_snippet=snippet_release_notes(notes),
        is_prerelease=bool(data.get("prerelease")),
        asset_size=int(picked.size or 0),
        asset_digest=picked.digest,
    )


def default_http_get(url: str, headers: Dict[str, str], timeout: float = DEFAULT_TIMEOUT_SEC) -> FetchResult:
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            body = raw.decode("utf-8", errors="replace") if raw else ""
            hdrs = {str(k).lower(): str(v) for k, v in (resp.headers.items() if resp.headers else [])}
            return FetchResult(status=int(getattr(resp, "status", 200) or 200), body=body, headers=hdrs)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            raw = exc.read()
            body = raw.decode("utf-8", errors="replace") if raw else ""
        except Exception:
            body = ""
        hdrs = {}
        try:
            if exc.headers:
                hdrs = {str(k).lower(): str(v) for k, v in exc.headers.items()}
        except Exception:
            hdrs = {}
        return FetchResult(status=int(exc.code or 0), body=body, headers=hdrs, error="http")
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        return FetchResult(status=0, body="", error="offline")
    except Exception:
        return FetchResult(status=0, body="", error="error")


def _build_headers(etag: str = "", owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO) -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT.format(version=current_app_version(), owner=owner, repo=repo),
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get(ENV_GITHUB_TOKEN, "").strip() or os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if etag:
        headers["If-None-Match"] = etag
    return headers


def _load_mock_payload() -> Optional[Dict[str, Any]]:
    path = os.environ.get(ENV_MOCK_JSON, "").strip()
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _quiet_fail(
    current_version: str,
    status: int = 0,
    from_cache: bool = False,
    message: str = "",
) -> UpdateCheckResult:
    return UpdateCheckResult(
        ok=False,
        update_available=False,
        current_version=current_version,
        latest=None,
        message=message,
        from_cache=from_cache,
        quiet_failure=True,
        http_status=status,
    )


def _result_from_payload(
    payload: Dict[str, Any],
    current_version: str,
    owner: str,
    repo: str,
    from_cache: bool,
    http_status: int,
) -> UpdateCheckResult:
    info = parse_release_payload(payload, current_version, owner=owner, repo=repo)
    if info is None:
        return _quiet_fail(current_version, status=http_status, from_cache=from_cache)

    force_newer = os.environ.get(ENV_FORCE_NEWER, "").strip().lower() in ("1", "true", "yes")
    newer = True if force_newer else is_newer(info.tag, current_version)
    if info.is_prerelease and not newer:
        # Pre-release không mới hơn bản đang chạy → không hiện nút cập nhật.
        newer = False

    if newer:
        asset_hint = (
            f" Tải {info.asset_name}."
            if info.asset_name
            else " Mở trang Releases (chưa có file cài)."
        )
        message = (
            f"Có bản mới {info.tag} (đang dùng v{current_version}).{asset_hint}"
        )
    else:
        message = f"Bạn đang dùng phiên bản mới nhất (v{current_version})."

    return UpdateCheckResult(
        ok=True,
        update_available=newer,
        current_version=current_version,
        latest=info,
        message=message,
        from_cache=from_cache,
        quiet_failure=False,
        http_status=http_status,
    )


def check_for_update(
    current_version: Optional[str] = None,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    cache: Optional[Dict[str, Any]] = None,
    http_get: Optional[HttpGet] = None,
    now_ts: Optional[float] = None,
    ttl_sec: Optional[float] = None,
    force: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    config: Optional[Dict[str, Any]] = None,
) -> UpdateCheckResult:
    """
    Kiểm tra GitHub Releases/latest.

    cache (được cập nhật tại chỗ):
      last_check_ts, etag, payload (dict JSON lần 200 gần nhất)

    http_get: injectable cho unit test — không mạng thật khi truyền mock.
    """
    import time

    version = current_app_version(current_version or APP_VERSION)
    owner, repo = resolve_repo(owner, repo, config)
    store = cache if cache is not None else {}
    ttl = DEFAULT_CACHE_TTL_SEC if ttl_sec is None else max(0.0, float(ttl_sec))
    now = time.time() if now_ts is None else float(now_ts)
    fetcher = http_get or default_http_get

    if os.environ.get(ENV_SKIP_CHECK, "").strip().lower() in ("1", "true", "yes"):
        return _quiet_fail(version)

    mock_payload = _load_mock_payload()
    if mock_payload is not None:
        store["last_check_ts"] = now
        store["payload"] = mock_payload
        return _result_from_payload(mock_payload, version, owner, repo, from_cache=False, http_status=200)

    last_ts = float(store.get("last_check_ts") or 0.0)
    cached_payload = store.get("payload")
    if (
        not force
        and ttl > 0
        and last_ts > 0
        and (now - last_ts) < ttl
        and isinstance(cached_payload, dict)
    ):
        return _result_from_payload(
            cached_payload, version, owner, repo, from_cache=True, http_status=int(store.get("http_status") or 200)
        )

    url = GITHUB_API_LATEST.format(owner=owner, repo=repo)
    etag = str(store.get("etag") or "").strip()
    headers = _build_headers(etag=etag, owner=owner, repo=repo)
    fetched = fetcher(url, headers, timeout)
    status = int(fetched.status or 0)

    if fetched.error == "offline" or status == 0:
        return _quiet_fail(version, status=0)

    if status == 304 and isinstance(cached_payload, dict):
        store["last_check_ts"] = now
        return _result_from_payload(cached_payload, version, owner, repo, from_cache=True, http_status=304)

    if status == 404:
        return _quiet_fail(
            version,
            status=404,
            message="Chưa có bản phát hành trên GitHub.",
        )
    if status in (403, 429) or status >= 500:
        return _quiet_fail(version, status=status)

    if status != 200:
        return _quiet_fail(version, status=status)

    try:
        payload = json.loads(fetched.body or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return _quiet_fail(version, status=status)

    if not isinstance(payload, dict):
        return _quiet_fail(version, status=status)

    new_etag = fetched.headers.get("etag") or fetched.headers.get("ETag") or ""
    store["last_check_ts"] = now
    store["etag"] = str(new_etag).strip()
    store["payload"] = payload
    store["http_status"] = 200
    return _result_from_payload(payload, version, owner, repo, from_cache=False, http_status=200)


def cache_from_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = config or {}
    payload = cfg.get("cached_release_payload")
    return {
        "last_check_ts": float(cfg.get("last_update_check_ts") or 0.0),
        "etag": str(cfg.get("last_update_check_etag") or ""),
        "payload": payload if isinstance(payload, dict) else None,
        "http_status": int(cfg.get("last_update_check_status") or 0),
    }


def apply_cache_to_config(config_manager: Any, cache: Dict[str, Any]) -> None:
    """Ghi cache kiểm tra cập nhật một lần (tránh save_config lặp)."""
    if config_manager is None:
        return
    try:
        cfg = getattr(config_manager, "config", None)
        if not isinstance(cfg, dict):
            return
        cfg["last_update_check_ts"] = float(cache.get("last_check_ts") or 0.0)
        cfg["last_update_check_etag"] = str(cache.get("etag") or "")
        payload = cache.get("payload")
        cfg["cached_release_payload"] = payload if isinstance(payload, dict) else {}
        cfg["last_update_check_status"] = int(cache.get("http_status") or 0)
        if hasattr(config_manager, "save_config"):
            config_manager.save_config()
    except Exception:
        pass
