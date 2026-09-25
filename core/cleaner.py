import os
import ctypes
import stat
import time
from ctypes import wintypes
from typing import Dict, Any, List, Callable, Optional, Sequence
from core.logger import logger
from core.c_drive_clean import (
    ADMIN_SKIP_REASON_VI,
    DEFAULT_DOWNLOADS_MIN_AGE_DAYS,
    LOCKED_REASON_VI,
    PROTECTED_REASON_VI,
    SYNC_ROOT_REASON_VI,
    TARGET_CATALOG,
    TARGET_ORDER,
    TOO_BROAD_REASON_VI,
    build_target_paths,
    clean_one_path,
    default_component_cleanup,
    default_hibernate_off,
    empty_detail,
    estimate_reclaimable,
    exclude_paths_scope,
    format_clean_report_vi,
    format_freed_vi,
    is_process_elevated,
    normalize_downloads_min_age_days,
    normalize_exclude_paths,
    _EmptyDirBudget,
    list_empty_directories,
    log_age_days_for_path,
    prune_nested_target_paths,
    read_c_drive_free_bytes,
    resolve_clean_plan,
    scan_old_files,
    scan_tree,
)

def remove_readonly(func, path, exc_info):
    """
    Xóa cờ Read-Only trên Windows khi gặp lỗi xóa tệp tạm thời
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

# Win32 Recycle Bin Structures & Flags
SHERB_NOCONFIRMATION = 0x00000001
SHERB_NOPROGRESSUI = 0x00000002
SHERB_NOSOUND = 0x00000004

class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('i64Size', ctypes.c_int64),
        ('i64NumItems', ctypes.c_int64)
    ]

class JunkCleaner:
    @staticmethod
    def is_admin() -> bool:
        """Tiến trình có đang elevated hay không. UI và lịch dọn dùng cùng một kết quả."""
        return is_process_elevated()

    @staticmethod
    def get_target_paths(environ: Optional[Dict[str, str]] = None) -> Dict[str, List[str]]:
        paths = build_target_paths(environ)
        # Giữ các khóa cũ luôn có mặt kể cả khi catalog thêm mục mới.
        for legacy in ("user_temp", "system_temp", "browser_cache", "crash_dumps", "windows_update", "app_caches"):
            paths.setdefault(legacy, [])
        return paths


    @staticmethod
    def get_recycle_bin_info() -> Dict[str, Any]:
        """
        Dung lượng thùng rác của tài khoản hiện tại.
        size_known=False khi không đọc được — không đoán 0 B là thùng trống.
        """
        unknown = {
            "size_bytes": 0,
            "size_mb": 0.0,
            "items": 0,
            "size_known": False,
            "reason": "Chưa ước lượng được dung lượng thùng rác. Vẫn có thể dọn nếu bạn bật.",
        }
        if os.name != "nt":
            return unknown
        try:
            rb = SHQUERYRBINFO()
            rb.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            res = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(rb))
            if res == 0:
                size = max(0, int(rb.i64Size))
                items = max(0, int(rb.i64NumItems))
                return {
                    "size_bytes": size,
                    "size_mb": round(size / (1024 ** 2), 2),
                    "items": items,
                    "size_known": True,
                }
        except Exception as e:
            print(f"[JunkCleaner] Error querying recycle bin: {e}")
        return unknown

    @staticmethod
    def empty_recycle_bin() -> Dict[str, Any]:
        """
        Làm trống thùng rác của người dùng hiện tại. Thất bại thì freed_bytes = 0.
        """
        if os.name != "nt":
            return {
                "success": False,
                "freed_bytes": 0,
                "freed_mb": 0.0,
                "items": 0,
                "status": "skipped",
                "reason": "Thùng rác chỉ có trên Windows — đã bỏ qua, không tính dung lượng.",
            }
        info_before = JunkCleaner.get_recycle_bin_info()
        try:
            res = ctypes.windll.shell32.SHEmptyRecycleBinW(
                None,
                None,
                SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
            )
            # 0 = S_OK. -2147418113 (E_UNEXPECTED) thường gặp khi thùng đã trống.
            if res == 0 or res == -2147418113:
                freed = max(0, int(info_before.get("size_bytes") or 0))
                return {
                    "success": True,
                    "freed_bytes": freed,
                    "freed_mb": round(freed / (1024 ** 2), 2),
                    "items": int(info_before.get("items") or 0),
                    "status": "cleaned",
                    "reason": "",
                }
        except Exception as e:
            print(f"[JunkCleaner] Error emptying recycle bin: {e}")
        return {
            "success": False,
            "freed_bytes": 0,
            "freed_mb": 0.0,
            "items": 0,
            "status": "error",
            "reason": "Không làm trống được thùng rác. Không tính dung lượng.",
        }

    @staticmethod
    def scan_directory(directory: str) -> Dict[str, Any]:
        return scan_tree(directory)

    @classmethod
    def scan(
        cls,
        enabled_targets: Dict[str, bool],
        *,
        is_admin: Optional[bool] = None,
        environ: Optional[Dict[str, str]] = None,
        downloads_min_age_days: Optional[int] = None,
        now_ts: Optional[float] = None,
        recycle_query: Optional[Callable[[], Dict[str, Any]]] = None,
        exclude_paths: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """
        Ước lượng dung lượng có thể xóa với quyền hiện tại.
        Mục cần Admin khi chưa elevated vẫn hiện kích thước nhưng không cộng vào tổng.
        """
        if is_admin is None:
            is_admin = cls.is_admin()
        target_paths = cls.get_target_paths(environ)
        days = normalize_downloads_min_age_days(
            DEFAULT_DOWNLOADS_MIN_AGE_DAYS if downloads_min_age_days is None else downloads_min_age_days
        )
        moment = time.time() if now_ts is None else float(now_ts)
        results = {
            "categories": {},
            "total_bytes": 0,
            "total_mb": 0.0,
            "total_files": 0,
            "admin_only_bytes": 0,
            "admin_only_mb": 0.0,
            "is_admin": bool(is_admin),
        }
        enabled = enabled_targets or {}
        env = os.environ if environ is None else environ
        user_profile = str(env.get("USERPROFILE", "") or "")
        system_root = str(env.get("SystemRoot", "") or env.get("SYSTEMROOT", "") or "")
        active_keys = [
            key for key in TARGET_ORDER
            if enabled.get(key, False)
            and not (TARGET_CATALOG[key]["needs_admin"] and not is_admin)
        ]
        pruned_paths = prune_nested_target_paths(target_paths, active_keys)
        empty_budget = _EmptyDirBudget()
        scope = exclude_paths_scope(exclude_paths)
        scope.__enter__()
        try:
            return cls._scan_categories(
                enabled=enabled,
                is_admin=bool(is_admin),
                target_paths=target_paths,
                pruned_paths=pruned_paths,
                days=days,
                moment=moment,
                user_profile=user_profile,
                system_root=system_root,
                recycle_query=recycle_query,
                empty_budget=empty_budget,
                results=results,
            )
        finally:
            scope.__exit__(None, None, None)

    @classmethod
    def _scan_categories(
        cls,
        *,
        enabled: Dict[str, bool],
        is_admin: bool,
        target_paths: Dict[str, List[str]],
        pruned_paths: Dict[str, List[str]],
        days: int,
        moment: float,
        user_profile: str,
        system_root: str,
        recycle_query: Optional[Callable[[], Dict[str, Any]]],
        empty_budget: _EmptyDirBudget,
        results: Dict[str, Any],
    ) -> Dict[str, Any]:
        for cat_key in TARGET_ORDER:
            if not enabled.get(cat_key, False):
                continue
            meta = TARGET_CATALOG[cat_key]
            will_skip = bool(meta["needs_admin"]) and not is_admin
            sized_paths = target_paths if will_skip else pruned_paths
            if cat_key == "recycle_bin":
                query = recycle_query or cls.get_recycle_bin_info
                try:
                    rb_info = query() or {}
                except Exception:
                    rb_info = {"size_known": False, "size_bytes": 0, "items": 0}
                known = rb_info.get("size_known")
                if known is None:
                    known = "size_bytes" in rb_info or "items" in rb_info
                if known:
                    cat_bytes = max(0, int(rb_info.get("size_bytes") or 0))
                    cat_files = max(0, int(rb_info.get("items") or 0))
                else:
                    cat_bytes = 0
                    cat_files = 0
                results["categories"][cat_key] = {
                    "name": meta["label_vi"],
                    "size_bytes": cat_bytes,
                    "size_mb": round(cat_bytes / (1024 ** 2), 2),
                    "file_count": cat_files,
                    "needs_admin": bool(meta["needs_admin"]),
                    "will_skip": will_skip,
                    "scope": meta["scope"],
                    "risk": meta["risk"],
                    "size_unknown": not bool(known),
                }
                if will_skip:
                    results["admin_only_bytes"] += cat_bytes
                elif known:
                    results["total_bytes"] += cat_bytes
                    results["total_files"] += cat_files
                continue
            elif meta["clean_mode"] == "old_files":
                cat_bytes = 0
                cat_files = 0
                for path in sized_paths.get(cat_key, []):
                    stat_info = scan_old_files(path, days, moment, user_profile=user_profile)
                    cat_bytes += stat_info["size_bytes"]
                    cat_files += stat_info["file_count"]
            elif meta["clean_mode"] == "empty_dirs":
                cat_bytes = 0
                cat_files = 0
                for path in sized_paths.get(cat_key, []):
                    cat_files += len(list_empty_directories(
                        path,
                        budget=empty_budget,
                        user_profile=user_profile,
                        system_root=system_root,
                    ))
            else:
                cat_bytes = 0
                cat_files = 0
                for path in sized_paths.get(cat_key, []):
                    log_days = log_age_days_for_path(cat_key, path)
                    if log_days > 0:
                        stat_info = scan_old_files(path, log_days, moment, user_profile=user_profile)
                    else:
                        stat_info = scan_tree(path)
                    cat_bytes += stat_info["size_bytes"]
                    cat_files += stat_info["file_count"]

            results["categories"][cat_key] = {
                "name": meta["label_vi"],
                "size_bytes": cat_bytes,
                "size_mb": round(cat_bytes / (1024 ** 2), 2),
                "file_count": cat_files,
                "needs_admin": bool(meta["needs_admin"]),
                "will_skip": will_skip,
                "scope": meta["scope"],
                "risk": meta["risk"],
            }
            if will_skip:
                results["admin_only_bytes"] += cat_bytes
            else:
                results["total_bytes"] += cat_bytes
                results["total_files"] += cat_files

        results["total_mb"] = round(results["total_bytes"] / (1024 ** 2), 2)
        results["admin_only_mb"] = round(results["admin_only_bytes"] / (1024 ** 2), 2)
        return results

    @classmethod
    def estimate_deep(
        cls,
        enabled_targets: Dict[str, bool],
        *,
        is_admin: Optional[bool] = None,
        environ: Optional[Dict[str, str]] = None,
        downloads_min_age_days: Optional[int] = None,
        now_ts: Optional[float] = None,
        recycle_query: Optional[Callable[[], Dict[str, Any]]] = None,
        deep_user_safe: bool = True,
        deep_admin: bool = False,
        exclude_paths: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Quét xem trước cho «Dọn ổ C» hoặc «Dọn sâu (cần Admin)». Không xóa tệp."""
        if is_admin is None:
            is_admin = cls.is_admin()
        plan = resolve_clean_plan(
            enabled_targets,
            is_admin=bool(is_admin),
            deep_user_safe=bool(deep_user_safe),
            deep_admin=bool(deep_admin),
        )
        recycle_info = None
        if plan["to_run"].get("recycle_bin"):
            query = recycle_query or cls.get_recycle_bin_info
            try:
                recycle_info = query() or {}
            except Exception:
                recycle_info = {"size_known": False, "size_bytes": 0, "items": 0}
            if recycle_info.get("size_known") is None and not (
                "size_bytes" in recycle_info or "items" in recycle_info or "file_count" in recycle_info
            ):
                recycle_info = dict(recycle_info)
                recycle_info["size_known"] = False
        return estimate_reclaimable(
            enabled_targets,
            is_admin=bool(is_admin),
            deep_user_safe=bool(deep_user_safe),
            deep_admin=bool(deep_admin),
            environ=environ,
            downloads_min_age_days=downloads_min_age_days,
            now_ts=now_ts,
            recycle_info=recycle_info,
            exclude_paths=exclude_paths,
        )

    @classmethod
    def _apply_recycle_result(cls, res: Dict[str, Any]) -> Dict[str, Any]:
        """Chỉ cộng byte khi Windows báo thành công. Payload thất bại không được tin freed_bytes."""
        if res.get("success"):
            freed = max(0, int(res.get("freed_bytes") or 0))
            items = max(0, int(res.get("items") or 0))
            status = "cleaned" if freed or items else "empty"
            return empty_detail(
                "recycle_bin",
                status=status,
                reason="",
                freed_bytes=freed,
                deleted_files=items,
            )
        status = "skipped" if res.get("status") == "skipped" else "error"
        return empty_detail(
            "recycle_bin",
            status=status,
            reason=str(res.get("reason") or "Không làm trống được thùng rác. Không tính dung lượng."),
            freed_bytes=0,
            deleted_files=0,
        )

    @staticmethod
    def _apply_special_clean(key: str, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """DISM và ngủ đông không đi qua xóa tệp. DISM luôn tính 0 B."""
        payload = raw or {}
        skipped = bool(payload.get("skipped"))
        success = bool(payload.get("success"))
        reason = str(payload.get("reason") or "")
        if key == "component_cleanup":
            freed = 0
        else:
            freed = max(0, int(payload.get("freed_bytes") or 0))
        if skipped or not success:
            freed = 0
            status = "skipped" if skipped else "error"
            if not reason:
                reason = ADMIN_SKIP_REASON_VI if skipped else "Không chạy được. Không tính dung lượng."
        elif key == "component_cleanup":
            status = "cleaned"
        else:
            status = "cleaned" if freed else "empty"
        return empty_detail(key, status=status, reason=reason, freed_bytes=freed)

    @classmethod
    def clean(
        cls,
        enabled_targets: Dict[str, bool],
        progress_callback: Optional[Callable[[str, int], None]] = None,
        *,
        is_admin: Optional[bool] = None,
        deep_user_safe: bool = False,
        deep_admin: bool = False,
        downloads_min_age_days: Optional[int] = None,
        environ: Optional[Dict[str, str]] = None,
        now_ts: Optional[float] = None,
        recycle_empty: Optional[Callable[[], Dict[str, Any]]] = None,
        disk_free_bytes: Optional[Callable[[], Optional[int]]] = None,
        component_cleanup: Optional[Callable[[], Dict[str, Any]]] = None,
        hibernate_off: Optional[Callable[..., Dict[str, Any]]] = None,
        only_keys: Optional[Sequence[str]] = None,
        exclude_paths: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """
        Dọn các mục được chọn. Mục cần Admin bị bỏ qua khi chưa elevated.
        total_freed_bytes chỉ gồm byte đã xóa thật.
        """
        if is_admin is None:
            is_admin = cls.is_admin()
        plan = resolve_clean_plan(
            enabled_targets,
            is_admin=bool(is_admin),
            deep_user_safe=deep_user_safe,
            deep_admin=deep_admin,
            only_keys=only_keys,
        )
        target_paths = cls.get_target_paths(environ)
        env = os.environ if environ is None else environ
        user_profile = str(env.get("USERPROFILE", "") or "")
        system_root = str(env.get("SystemRoot", "") or env.get("SYSTEMROOT", "") or "")
        days = normalize_downloads_min_age_days(
            DEFAULT_DOWNLOADS_MIN_AGE_DAYS if downloads_min_age_days is None else downloads_min_age_days
        )
        moment = time.time() if now_ts is None else float(now_ts)
        scope = exclude_paths_scope(normalize_exclude_paths(exclude_paths))
        scope.__enter__()
        try:
            return cls._clean_planned(
                plan=plan,
                target_paths=target_paths,
                user_profile=user_profile,
                system_root=system_root,
                days=days,
                moment=moment,
                progress_callback=progress_callback,
                is_admin=bool(is_admin),
                deep_user_safe=bool(deep_user_safe),
                deep_admin=bool(deep_admin),
                environ=environ,
                recycle_empty=recycle_empty,
                disk_free_bytes=disk_free_bytes,
                component_cleanup=component_cleanup,
                hibernate_off=hibernate_off,
            )
        finally:
            scope.__exit__(None, None, None)

    @classmethod
    def _clean_planned(
        cls,
        *,
        plan: Dict[str, Any],
        target_paths: Dict[str, List[str]],
        user_profile: str,
        system_root: str,
        days: int,
        moment: float,
        progress_callback: Optional[Callable[[str, int], None]],
        is_admin: bool,
        deep_user_safe: bool,
        deep_admin: bool,
        environ: Optional[Dict[str, str]],
        recycle_empty: Optional[Callable[[], Dict[str, Any]]],
        disk_free_bytes: Optional[Callable[[], Optional[int]]],
        component_cleanup: Optional[Callable[[], Dict[str, Any]]],
        hibernate_off: Optional[Callable[..., Dict[str, Any]]],
    ) -> Dict[str, Any]:
        details: Dict[str, Any] = {}
        detail_order: List[str] = []
        total_freed_bytes = 0
        total_deleted_files = 0
        free_before = None
        track_free = bool(deep_user_safe or deep_admin)
        if track_free:
            reader = disk_free_bytes or read_c_drive_free_bytes
            try:
                free_before = reader()
            except Exception:
                free_before = None

        for skipped in plan["skipped"]:
            key = skipped["key"]
            details[key] = empty_detail(key, status="skipped", reason=skipped["reason"], freed_bytes=0)
            detail_order.append(key)

        runnable = [key for key in TARGET_ORDER if plan["to_run"].get(key)]
        pruned_paths = prune_nested_target_paths(target_paths, runnable)
        pct_step = 80 // max(1, len(runnable))
        current_pct = 8

        for cat_key in runnable:
            meta = TARGET_CATALOG[cat_key]
            if progress_callback:
                progress_callback(f"Đang dọn {meta['label_vi']}...", current_pct)
            try:
                if cat_key == "recycle_bin":
                    runner = recycle_empty or cls.empty_recycle_bin
                    raw = runner() or {}
                    detail = cls._apply_recycle_result(raw)
                elif meta["clean_mode"] == "component_cleanup":
                    runner = component_cleanup or default_component_cleanup
                    detail = cls._apply_special_clean(cat_key, runner() or {})
                elif meta["clean_mode"] == "hibernate":
                    runner = hibernate_off or default_hibernate_off
                    try:
                        raw = runner(environ)
                    except TypeError:
                        raw = runner()
                    detail = cls._apply_special_clean(cat_key, raw or {})
                else:
                    agg = {
                        "freed_bytes": 0,
                        "deleted_files": 0,
                        "skipped_locked": 0,
                        "errors": 0,
                        "protected": 0,
                        "too_broad": 0,
                        "sync_root": 0,
                    }
                    for path in pruned_paths.get(cat_key, []):
                        log_days = log_age_days_for_path(cat_key, path)
                        part = clean_one_path(
                            path,
                            clean_mode="old_files" if log_days > 0 else meta["clean_mode"],
                            min_age_days=log_days if log_days > 0 else days,
                            now_ts=moment,
                            user_profile=user_profile,
                            system_root=system_root,
                        )
                        for field in agg:
                            agg[field] += int(part.get(field) or 0)
                    reason = ""
                    status = "cleaned"
                    if agg["protected"]:
                        status = "error" if agg["freed_bytes"] <= 0 else "cleaned"
                        reason = PROTECTED_REASON_VI
                    elif agg["sync_root"] and agg["freed_bytes"] <= 0:
                        status = "error"
                        reason = SYNC_ROOT_REASON_VI
                    elif agg["too_broad"] and agg["freed_bytes"] <= 0:
                        status = "error"
                        reason = TOO_BROAD_REASON_VI
                    elif meta.get("clean_mode") == "empty_dirs" and agg["deleted_files"] > 0:
                        status = "cleaned"
                        reason = f"Đã xóa {agg['deleted_files']} thư mục trống (0 B)."
                        if agg["skipped_locked"]:
                            reason += f" Bỏ qua {agg['skipped_locked']} thư mục chưa xóa được."
                    elif agg["freed_bytes"] <= 0 and agg["skipped_locked"] <= 0 and agg["errors"] <= 0:
                        status = "empty"
                    elif agg["skipped_locked"]:
                        reason = LOCKED_REASON_VI
                    detail = empty_detail(
                        cat_key,
                        status=status,
                        reason=reason,
                        freed_bytes=agg["freed_bytes"],
                        deleted_files=agg["deleted_files"],
                        skipped_locked=agg["skipped_locked"],
                        errors=agg["errors"],
                    )
            except Exception as exc:
                logger.warning(f"[JunkCleaner] Lỗi khi dọn {cat_key}: {exc}")
                detail = empty_detail(
                    cat_key,
                    status="error",
                    reason=f"Lỗi khi dọn mục này. Không tính dung lượng. ({exc})",
                    freed_bytes=0,
                )
            details[cat_key] = detail
            detail_order.append(cat_key)
            total_freed_bytes += int(detail.get("freed_bytes") or 0)
            total_deleted_files += int(detail.get("deleted_files") or 0)
            current_pct += pct_step

        if progress_callback:
            progress_callback("Hoàn tất dọn dẹp!", 100)

        free_after = None
        if track_free:
            reader = disk_free_bytes or read_c_drive_free_bytes
            try:
                free_after = reader()
            except Exception:
                free_after = None

        freed_mb = round(total_freed_bytes / (1024 ** 2), 2)
        skipped_names = [item.get("name") or item.get("key") for item in plan["skipped"]]
        logger.info(
            f"[JunkCleaner] Hoàn tất dọn dẹp: Đã xóa {total_deleted_files} files, "
            f"giải phóng {format_freed_vi(total_freed_bytes)} ({total_freed_bytes} bytes). "
            f"Bỏ qua: {skipped_names or 'không'}."
        )
        result = {
            "total_freed_bytes": total_freed_bytes,
            "total_freed_mb": freed_mb,
            "freed_label_vi": format_freed_vi(total_freed_bytes),
            "total_deleted_files": total_deleted_files,
            "details": details,
            "detail_order": detail_order,
            "skipped": plan["skipped"],
            "is_admin": bool(is_admin),
            "deep_user_safe": bool(deep_user_safe),
            "deep_admin": bool(deep_admin),
            "free_bytes_before": free_before,
            "free_bytes_after": free_after,
            "free_bytes_delta": (
                int(free_after) - int(free_before)
                if free_before is not None and free_after is not None
                else None
            ),
        }
        result["report_vi"] = format_clean_report_vi(result)
        return result


# ==============================================================================
# LARGE FILE SCANNER & MANAGER (Giai đoạn 1)
# ==============================================================================

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]

FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040        # Move to Recycle Bin (cho phép Ctrl+Z)
FOF_NOCONFIRMATION = 0x0010   # Không hiện popup Windows xác nhận
FOF_SILENT = 0x0004           # Không hiện progress dialog Windows

def format_file_size(size_bytes: int) -> str:
    """Định dạng kích thước file sang GB, MB hoặc KB dễ đọc"""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"

class LargeFileScanner:
    """
    Quét và quản lý các file có dung lượng lớn (>100MB, >500MB, >1GB)
    Hỗ trợ xóa an toàn vào Thùng Rác (Recycle Bin) qua Win32 API.
    """

    @staticmethod
    def get_default_scan_locations() -> List[str]:
        user_profile = os.environ.get("USERPROFILE", "")
        locs = []
        if user_profile:
            for folder in ["Downloads", "Documents", "Desktop", "Videos", "Music", "Pictures"]:
                p = os.path.join(user_profile, folder)
                if os.path.exists(p):
                    locs.append(p)
        return locs

    @staticmethod
    def scan_large_files(
        root_paths: Optional[List[str]] = None,
        min_size_mb: int = 100,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> List[Dict[str, Any]]:
        """
        Quét đệ quy tìm các file có kích thước >= min_size_mb.
        Bỏ qua các thư mục hệ thống và rác nội bộ (.git, .venv, $Recycle.Bin, node_modules, AppData).
        """
        from datetime import datetime

        if root_paths is None or len(root_paths) == 0:
            root_paths = LargeFileScanner.get_default_scan_locations()

        min_bytes = min_size_mb * 1024 * 1024
        results = []

        ignore_dirs = {
            "$recycle.bin", "system volume information", ".git", 
            ".venv", "node_modules", "appdata", "__pycache__", ".vscode"
        }

        total_roots = len(root_paths)
        for idx, base_dir in enumerate(root_paths):
            if cancel_check and cancel_check():
                break

            if not os.path.exists(base_dir):
                continue

            pct_base = int((idx / max(1, total_roots)) * 90)
            if progress_callback:
                progress_callback(f"Đang quét thư mục: {os.path.basename(base_dir)}...", pct_base)

            try:
                for root, dirs, files in os.walk(base_dir):
                    if cancel_check and cancel_check():
                        break

                    # Loại trừ các thư mục nhạy cảm hoặc nội bộ
                    dirs[:] = [d for d in dirs if d.lower() not in ignore_dirs and not d.startswith("$")]

                    for f in files:
                        try:
                            f_path = os.path.join(root, f)
                            if os.path.islink(f_path):
                                continue

                            f_size = os.path.getsize(f_path)
                            if f_size >= min_bytes:
                                mtime = os.path.getmtime(f_path)
                                mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                                ext = os.path.splitext(f)[1].lower()

                                results.append({
                                    "filename": f,
                                    "path": f_path,
                                    "directory": root,
                                    "size_bytes": f_size,
                                    "size_mb": round(f_size / (1024 ** 2), 2),
                                    "size_formatted": format_file_size(f_size),
                                    "modified": mtime_str,
                                    "mtime": mtime,
                                    "extension": ext if ext else "(Không đuôi)"
                                })
                        except (OSError, PermissionError):
                            continue
            except Exception as e:
                logger.warning(f"[LargeFileScanner] Lỗi quét tại {base_dir}: {e}")

        # Sắp xếp giảm dần theo kích thước file (file lớn nhất đứng đầu)
        results.sort(key=lambda x: x["size_bytes"], reverse=True)

        if progress_callback:
            progress_callback(f"Quét hoàn tất: Tìm thấy {len(results)} file lớn!", 100)

        logger.info(f"[LargeFileScanner] Đã quét xong, tìm thấy {len(results)} file >= {min_size_mb} MB.")
        return results

    @staticmethod
    def send_to_recycle_bin(filepath: str) -> Dict[str, Any]:
        """
        Di chuyển file an toàn vào Thùng Rác Windows (Recycle Bin) qua Win32 SHFileOperationW.
        Người dùng có thể khôi phục lại (Ctrl+Z) bất cứ lúc nào.
        """
        if not os.path.exists(filepath):
            return {"success": False, "error": "File không tồn tại trên đĩa"}

        try:
            # SHFileOperationW yêu cầu chuỗi kết thúc bằng 2 ký tự NULL (\0\0)
            abs_path = os.path.abspath(filepath) + "\0\0"
            file_op = SHFILEOPSTRUCTW()
            file_op.hwnd = None
            file_op.wFunc = FO_DELETE
            file_op.pFrom = abs_path
            file_op.pTo = None
            file_op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
            file_op.fAnyOperationsAborted = False
            file_op.hNameMappings = None
            file_op.lpszProgressTitle = None

            res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(file_op))
            if res == 0 and not file_op.fAnyOperationsAborted:
                logger.info(f"[LargeFileScanner] Đã chuyển an toàn vào Thùng rác: {filepath}")
                return {"success": True, "error": None}
            else:
                err_msg = f"Mã lỗi Win32: {res} (aborted={file_op.fAnyOperationsAborted})"
                logger.error(f"[LargeFileScanner] Không thể xóa file {filepath}: {err_msg}")
                return {"success": False, "error": err_msg}
        except Exception as e:
            logger.error(f"[LargeFileScanner] Lỗi ngoại lệ khi xóa file {filepath}: {e}")
            return {"success": False, "error": str(e)}

