"""
Smart Analytics Reporter - Báo cáo hiệu quả tối ưu hóa thông minh.

Phân tích lịch sử dọn dẹp từ config.json theo nhiều mốc thời gian:
  - 7 ngày qua
  - 30 ngày qua  
  - Toàn thời gian

Tính toán các chỉ số KPI và đánh giá sức khỏe hệ thống.
"""
from datetime import datetime, timedelta
from typing import Dict, Any, List
from core.logger import logger


class AnalyticsReporter:
    """
    Tạo báo cáo thống kê thông minh từ lịch sử dọn dẹp và tối ưu hóa.
    """

    TRIGGER_LABELS = {
        "manual": "Thủ công (1-Click)",
        "auto_periodic": "Tự động (Định kỳ)",
        "ram_threshold": "Tự động (Ngưỡng RAM)",
        "quick_tray": "Khay hệ thống",
        "game_boost": "Game Boost"
    }

    @staticmethod
    def generate_summary(history: List[Dict[str, Any]], days: int = None) -> Dict[str, Any]:
        """
        Tạo báo cáo tổng hợp cho khoảng thời gian được chỉ định.

        Args:
            history: Danh sách lịch sử dọn dẹp từ config_manager
            days: Số ngày cần tổng hợp (None = toàn thời gian)

        Returns:
            Dict chứa các chỉ số KPI và đánh giá sức khỏe
        """
        if not history:
            return AnalyticsReporter._empty_report(days)

        # Lọc theo khoảng thời gian
        if days is not None:
            cutoff = datetime.now() - timedelta(days=days)
            filtered = []
            for item in history:
                try:
                    ts = datetime.strptime(item.get("timestamp", ""), "%Y-%m-%d %H:%M:%S")
                    if ts >= cutoff:
                        filtered.append(item)
                except (ValueError, TypeError):
                    continue
        else:
            filtered = list(history)

        if not filtered:
            return AnalyticsReporter._empty_report(days)

        # Tính toán KPI
        total_junk_mb = sum(h.get("junk_freed_mb", 0) for h in filtered)
        total_ram_mb = sum(h.get("ram_freed_mb", 0) for h in filtered)
        total_cleanups = len(filtered)

        # Phân tích loại kích hoạt
        trigger_counts: Dict[str, int] = {}
        for item in filtered:
            trigger = item.get("trigger_type", "manual")
            trigger_counts[trigger] = trigger_counts.get(trigger, 0) + 1

        # Xác định kích hoạt phổ biến nhất
        top_trigger = max(trigger_counts, key=trigger_counts.get) if trigger_counts else "manual"
        top_trigger_label = AnalyticsReporter.TRIGGER_LABELS.get(top_trigger, top_trigger)

        # Tính tần suất trung bình (lần/ngày)
        if days and days > 0:
            cleanups_per_day = round(total_cleanups / days, 1)
        elif len(filtered) >= 2:
            try:
                first_ts = datetime.strptime(filtered[-1].get("timestamp", ""), "%Y-%m-%d %H:%M:%S")
                last_ts = datetime.strptime(filtered[0].get("timestamp", ""), "%Y-%m-%d %H:%M:%S")
                span_days = max((last_ts - first_ts).days, 1)
                cleanups_per_day = round(total_cleanups / span_days, 1)
            except Exception:
                cleanups_per_day = 0.0
        else:
            cleanups_per_day = total_cleanups

        # Đánh giá sức khỏe tổng thể
        if cleanups_per_day >= 1.0 and total_junk_mb > 50:
            health_score = "Tối Ưu 🌟"
            health_desc = "Hệ thống được bảo dưỡng thường xuyên, hiệu năng duy trì ở mức tốt nhất."
        elif cleanups_per_day >= 0.3:
            health_score = "Rất Tốt ✅"
            health_desc = "Hệ thống được dọn dẹp định kỳ tốt. Tiếp tục duy trì thói quen này."
        elif total_cleanups > 0:
            health_score = "Cần Lưu Ý ⚠️"
            health_desc = "Số lần tối ưu ít. Hãy bật dọn dẹp tự động để duy trì hiệu năng ổn định."
        else:
            health_score = "Chưa Hoạt Động 🔴"
            health_desc = "Chưa có dữ liệu trong khoảng thời gian này."

        return {
            "period_days": days,
            "total_cleanups": total_cleanups,
            "total_junk_mb": round(total_junk_mb, 1),
            "total_junk_gb": round(total_junk_mb / 1024, 2),
            "total_ram_mb": round(total_ram_mb, 1),
            "total_ram_gb": round(total_ram_mb / 1024, 2),
            "cleanups_per_day": cleanups_per_day,
            "trigger_counts": trigger_counts,
            "trigger_labels": {
                k: AnalyticsReporter.TRIGGER_LABELS.get(k, k)
                for k in trigger_counts
            },
            "top_trigger": top_trigger,
            "top_trigger_label": top_trigger_label,
            "health_score": health_score,
            "health_desc": health_desc,
            "has_data": True
        }

    @staticmethod
    def generate_report_text(config_manager) -> str:
        """
        Tạo báo cáo văn bản định dạng Markdown để xuất hoặc hiển thị.
        """
        history = config_manager.get("history", [])
        now = datetime.now()

        lines = [
            "# BÁO CÁO HIỆU QUẢ TỐI ƯU HÓA HỆ THỐNG",
            f"**PC Auto Cleaner & RAM Optimizer**  |  Ngày tạo: {now.strftime('%d/%m/%Y %H:%M')}",
            "",
            "---",
            ""
        ]

        for period_label, days in [("7 NGÀY QUA", 7), ("30 NGÀY QUA", 30), ("TOÀN THỜI GIAN", None)]:
            summary = AnalyticsReporter.generate_summary(history, days)
            lines += [
                f"## 📊 {period_label}",
                "",
                f"- **Số lần dọn dẹp**: {summary['total_cleanups']} lần",
                f"- **Dung lượng rác giải phóng**: {summary['total_junk_mb']:.1f} MB "
                f"({summary['total_junk_gb']:.2f} GB)",
                f"- **RAM đã thu hồi**: {summary['total_ram_mb']:.1f} MB "
                f"({summary['total_ram_gb']:.2f} GB)",
                f"- **Tần suất trung bình**: {summary['cleanups_per_day']} lần/ngày",
                f"- **Đánh giá sức khỏe**: {summary['health_score']}",
                ""
            ]
            if summary.get("trigger_counts"):
                lines.append("**Phân loại theo cách kích hoạt:**")
                for trigger, count in summary["trigger_counts"].items():
                    label = summary["trigger_labels"].get(trigger, trigger)
                    lines.append(f"  - {label}: {count} lần")
                lines.append("")

        lines += [
            "---",
            "",
            "*(Báo cáo được tạo tự động bởi PC Auto Cleaner & RAM Optimizer)*"
        ]

        return "\n".join(lines)

    @staticmethod
    def _empty_report(days: int = None) -> Dict[str, Any]:
        return {
            "period_days": days,
            "total_cleanups": 0,
            "total_junk_mb": 0.0,
            "total_junk_gb": 0.0,
            "total_ram_mb": 0.0,
            "total_ram_gb": 0.0,
            "cleanups_per_day": 0.0,
            "trigger_counts": {},
            "trigger_labels": {},
            "top_trigger": None,
            "top_trigger_label": "Chưa có",
            "health_score": "Chưa Hoạt Động 🔴",
            "health_desc": "Chưa có dữ liệu dọn dẹp trong khoảng thời gian này.",
            "has_data": False
        }
