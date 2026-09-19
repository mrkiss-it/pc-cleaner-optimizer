"""
Disk Space Analyzer - Phân tích và trực quan hóa không gian lưu trữ ổ đĩa.

Quét nhanh cây thư mục bằng os.scandir (tốc độ cao) trong QThread để không làm đơ UI.
Phân loại tệp thành 8 nhóm chính và tổng hợp dữ liệu cho biểu đồ thanh màu sắc.
"""
import os
import threading
from typing import Dict, Any, List, Optional, Callable
from PyQt5.QtCore import QObject, pyqtSignal, QThread
from core.logger import logger


# Phân loại tệp theo phần mở rộng
FILE_CATEGORIES = {
    "Video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp", ".ts"},
    "Nén & Ảnh đĩa": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".img", ".vmdk", ".vhd"},
    "Cài đặt & Thực thi": {".exe", ".msi", ".apk", ".dmg", ".pkg", ".deb", ".rpm"},
    "Tài liệu": {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".odt", ".txt"},
    "Âm thanh": {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".wma"},
    "Hình ảnh": {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".raw", ".psd", ".ai", ".svg"},
    "Lập trình": {".py", ".js", ".ts", ".cpp", ".c", ".java", ".go", ".rs", ".html", ".css",
                  ".json", ".xml", ".yaml", ".sql", ".sh", ".bat"},
    "Khác": set()
}

# Màu sắc cho từng danh mục (hex CSS)
CATEGORY_COLORS = {
    "Video": "#f43f5e",
    "Nén & Ảnh đĩa": "#f59e0b",
    "Cài đặt & Thực thi": "#8b5cf6",
    "Tài liệu": "#3b82f6",
    "Âm thanh": "#10b981",
    "Hình ảnh": "#ec4899",
    "Lập trình": "#06b6d4",
    "Khác": "#64748b"
}


def _classify_file(ext: str) -> str:
    ext_lower = ext.lower()
    for category, exts in FILE_CATEGORIES.items():
        if category == "Khác":
            continue
        if ext_lower in exts:
            return category
    return "Khác"


class ScanWorker(QThread):
    """QThread thực hiện quét ổ đĩa không block GUI."""
    progress = pyqtSignal(int, str)           # (percent, current_path)
    scan_finished = pyqtSignal(dict)          # Kết quả phân tích hoàn chỉnh
    error_occurred = pyqtSignal(str)

    def __init__(self, root_paths: List[str], min_file_size_mb: float = 0.0):
        super().__init__()
        self.root_paths = root_paths
        self.min_file_size_mb = min_file_size_mb
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            result = self._scan_all()
            self.scan_finished.emit(result)
        except Exception as e:
            self.error_occurred.emit(str(e))

    def _scan_all(self) -> Dict[str, Any]:
        # Thực hiện quét đệ quy qua _do_scan
        category_sizes_final, top_files_final, total_bytes_final, file_count_final, dir_sizes_final = \
            self._do_scan(self.root_paths)

        total_mb = total_bytes_final / (1024 ** 2)

        # Tính top thư mục
        sorted_dirs = sorted(dir_sizes_final.items(), key=lambda x: x[1], reverse=True)[:15]
        top_dirs_result = [
            {
                "path": d,
                "name": os.path.basename(d) or d,
                "size_mb": round(sz / (1024 ** 2), 1),
                "size_gb": round(sz / (1024 ** 3), 2),
                "percent": round(sz / max(total_bytes_final, 1) * 100, 1)
            }
            for d, sz in sorted_dirs
        ]

        # Tỷ lệ % các danh mục
        categories_result = {}
        for cat, size_b in category_sizes_final.items():
            size_mb = size_b / (1024 ** 2)
            categories_result[cat] = {
                "size_mb": round(size_mb, 1),
                "size_gb": round(size_mb / 1024, 2),
                "percent": round(size_b / max(total_bytes_final, 1) * 100, 1),
                "color": CATEGORY_COLORS.get(cat, "#64748b")
            }

        # Top tệp lớn nhất
        top_files_result = sorted(top_files_final, key=lambda x: x["size_bytes"], reverse=True)[:50]
        for f in top_files_result:
            f["size_mb"] = round(f["size_bytes"] / (1024 ** 2), 1)
            f["size_gb"] = round(f["size_bytes"] / (1024 ** 3), 2)
            f.pop("size_bytes", None)

        return {
            "total_mb": round(total_mb, 1),
            "total_gb": round(total_mb / 1024, 2),
            "file_count": file_count_final,
            "categories": categories_result,
            "top_files": top_files_result,
            "top_dirs": top_dirs_result,
            "scanned_paths": self.root_paths
        }

    def _do_scan(self, root_paths: List[str]):
        """Thực hiện quét đệ quy thực sự."""
        category_sizes: Dict[str, float] = {cat: 0.0 for cat in FILE_CATEGORIES}
        top_files: List[Dict[str, Any]] = []
        dir_sizes: Dict[str, float] = {}
        total_bytes = 0
        file_count = 0

        skip_dirs = {
            "__pycache__", ".git", "node_modules", "$RECYCLE.BIN",
            "System Volume Information", "Windows", "ProgramData"
        }

        def walk(path: str, depth: int = 0):
            nonlocal total_bytes, file_count
            if self._stop_requested:
                return
            if depth > 8:
                return
            try:
                dir_total = 0
                with os.scandir(path) as it:
                    for entry in it:
                        if self._stop_requested:
                            return
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name in skip_dirs:
                                    continue
                                walk(entry.path, depth + 1)
                                dir_total += dir_sizes.get(entry.path, 0)
                            elif entry.is_file(follow_symlinks=False):
                                size = entry.stat().st_size
                                ext = os.path.splitext(entry.name)[1]
                                cat = _classify_file(ext)
                                category_sizes[cat] = category_sizes.get(cat, 0) + size
                                total_bytes += size
                                file_count += 1
                                dir_total += size

                                size_mb = size / (1024 ** 2)
                                if size_mb >= max(self.min_file_size_mb, 5.0):
                                    top_files.append({
                                        "name": entry.name,
                                        "path": entry.path,
                                        "category": cat,
                                        "size_bytes": size,
                                        "modified": entry.stat().st_mtime
                                    })
                        except (PermissionError, OSError):
                            continue
                dir_sizes[path] = dir_total
            except (PermissionError, OSError, NotADirectoryError):
                pass

        for root in root_paths:
            if os.path.exists(root):
                self.progress.emit(5, f"Đang quét: {root}")
                walk(root)
                self.progress.emit(90, f"Hoàn tất: {root}")

        self.progress.emit(100, "Phân tích hoàn tất!")
        return category_sizes, top_files, total_bytes, file_count, dir_sizes


class DiskAnalyzer:
    """
    API tĩnh để bắt đầu quét phân tích ổ đĩa.
    Trả về ScanWorker (QThread) để caller kết nối signals.
    """

    @staticmethod
    def get_default_scan_paths() -> List[str]:
        """Danh sách đường dẫn quét mặc định (thư mục người dùng)."""
        user = os.path.expanduser("~")
        paths = []
        for sub in ["Downloads", "Desktop", "Documents", "Videos", "Music", "Pictures", "AppData\\Local"]:
            p = os.path.join(user, sub)
            if os.path.exists(p):
                paths.append(p)
        return paths

    @staticmethod
    def get_drive_paths() -> List[Dict[str, str]]:
        """Lấy danh sách các ổ đĩa có trên hệ thống."""
        drives = []
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            path = f"{letter}:\\"
            if os.path.exists(path):
                try:
                    total, used, free = os.popen(
                        f'wmic logicaldisk where "DeviceID=\\"{letter}:\\"" get Size,FreeSpace /value'
                    ), 0, 0
                    drives.append({"letter": letter, "path": path, "label": f"Ổ {letter}:"})
                except Exception:
                    drives.append({"letter": letter, "path": path, "label": f"Ổ {letter}:"})
        return drives

    @staticmethod
    def create_worker(root_paths: List[str], min_file_size_mb: float = 0.0) -> ScanWorker:
        """Tạo và trả về ScanWorker để gọi worker.start() và kết nối signals."""
        return ScanWorker(root_paths, min_file_size_mb)
