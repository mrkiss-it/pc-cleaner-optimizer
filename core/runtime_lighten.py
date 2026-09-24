"""
Một lần «Làm máy nhẹ hơn»: chỉ bước an toàn đã có trong app.

- Thu hồi working set RAM (MemoryOptimizer, tôn trọng whitelist/ghim).
- Xóa temp người dùng và crash dump của tài khoản này qua JunkCleaner.
- Không thùng rác, không mục cần Admin, không tắt mục khởi động.
"""

from typing import Any, Dict, Optional, Sequence, Set

from core.memory_optimizer import format_ram_report_vi

# Chỉ mục user-safe, needs_admin=False. system_temp cần Admin nên cố ý tắt.
USER_SAFE_QUICK_CLEAN: Dict[str, bool] = {
    "user_temp": True,
    "crash_dumps": True,
    "system_temp": False,
    "recycle_bin": False,
    "browser_cache": False,
    "windows_update": False,
    "app_caches": False,
}

LIGHTEN_CONFIRM_VI = (
    "Làm máy nhẹ hơn sẽ làm hai việc, rồi dừng:\n\n"
    "1. Thu hồi working set RAM bằng EmptyWorkingSet. Không tắt ứng dụng. "
    "Tiến trình bạn đã ghim trong Whitelist được bỏ qua, cùng với tiến trình hệ thống.\n"
    "2. Xóa file tạm của tài khoản này (%TEMP%) và crash dump trong LocalAppData nếu xóa được.\n\n"
    "Không làm trống thùng rác.\n"
    "Không cần quyền Administrator. File Windows không cho xóa sẽ bị bỏ qua, không tính là đã xóa.\n"
    "Không tắt ứng dụng khởi động cùng Windows.\n"
    "Không dọn cache trình duyệt, Windows Update hay toàn bộ ổ C.\n\n"
    "RAM trống có thể được Windows cấp lại ngay. Đây không phải tăng FPS."
)


def confirm_text_vi() -> str:
    return LIGHTEN_CONFIRM_VI


def run_lighten(
    whitelist: Optional[Set[str]] = None,
    *,
    cleaner: Any = None,
    ram_optimizer: Any = None,
    exclude_paths: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Chạy preset. Mỗi bước ghi riêng success để UI không gộp lỗi thành «xong hết»."""
    if cleaner is None:
        from core.cleaner import JunkCleaner
        cleaner = JunkCleaner
    if ram_optimizer is None:
        from core.memory_optimizer import MemoryOptimizer
        ram_optimizer = MemoryOptimizer

    steps = []
    clean_res: Dict[str, Any] = {}
    try:
        clean_res = cleaner.clean(
            dict(USER_SAFE_QUICK_CLEAN),
            exclude_paths=list(exclude_paths or []),
            only_keys=("user_temp", "crash_dumps"),
        ) or {}
        junk_mb = float(clean_res.get("total_freed_mb") or 0.0)
        files = int(clean_res.get("total_deleted_files") or 0)
        steps.append({
            "id": "user_temp",
            "success": True,
            "freed_mb": junk_mb,
            "deleted_files": files,
            "detail": (
                f"Đã xóa {junk_mb:.1f} MB ({files} tệp) trong temp người dùng và crash dump. "
                "Không đụng thùng rác."
            ),
        })
    except Exception as exc:
        clean_res = {}
        steps.append({
            "id": "user_temp",
            "success": False,
            "freed_mb": 0.0,
            "deleted_files": 0,
            "error": str(exc),
            "detail": f"Không xóa được temp: {exc}",
        })

    ram_res: Dict[str, Any] = {}
    try:
        ram_res = ram_optimizer.optimize_ram(whitelist=set(whitelist or set())) or {}
        steps.append({
            "id": "ram",
            "success": bool(ram_res.get("success", True)),
            "freed_mb": float(ram_res.get("freed_mb") or 0.0),
            "detail": format_ram_report_vi(ram_res),
        })
    except Exception as exc:
        ram_res = {"success": False, "freed_mb": 0.0}
        steps.append({
            "id": "ram",
            "success": False,
            "freed_mb": 0.0,
            "error": str(exc),
            "detail": f"Không thu hồi được RAM: {exc}",
        })

    failed = [step["id"] for step in steps if not step.get("success")]
    return {
        "success": not failed,
        "failed_steps": failed,
        "steps": steps,
        "clean": clean_res,
        "ram": ram_res,
        "junk_freed_mb": float(steps[0].get("freed_mb") or 0.0),
        "deleted_files": int(steps[0].get("deleted_files") or 0),
        "ram_freed_mb": float(ram_res.get("freed_mb") or 0.0),
        "recycle_emptied": False,
        "startup_changed": False,
        "needs_admin": False,
        "message_vi": format_lighten_report_vi(steps, clean_res, ram_res),
    }


def format_lighten_report_vi(steps, clean_res, ram_res) -> str:
    lines = ["Đã chạy «Làm máy nhẹ hơn».", ""]
    for step in steps:
        title = "Temp người dùng / crash dump" if step.get("id") == "user_temp" else "RAM"
        mark = "Xong" if step.get("success") else "Không xong"
        lines.append(f"{title}: {mark}")
        detail = str(step.get("detail") or "").strip()
        if detail:
            lines.append(detail)
        lines.append("")
    lines.append("Không làm trống thùng rác.")
    lines.append("Không tắt mục khởi động.")
    lines.append("Không yêu cầu Administrator cho preset này.")
    if clean_res.get("admin_skipped"):
        lines.append("Có mục cần Admin bị bỏ qua — không tính dung lượng.")
    return "\n".join(lines).rstrip() + "\n"
