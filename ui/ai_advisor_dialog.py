"""
ui/ai_advisor_dialog.py – AI Smart Suggestions Dialog (v3.3 Pro)
=================================================================
Giao diện Fluent Dark hiển thị các gợi ý tối ưu từ AIAdvisor.
Hỗ trợ: filter theo priority, action dispatch, auto-refresh.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget, QFrame,
)

from core.ai_advisor import (
    AIAdvisor, Suggestion,
    PRIORITY_CRITICAL, PRIORITY_WARNING, PRIORITY_TIP,
    CATEGORY_ICONS,
)

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
_BG            = "#0d1117"
_SURFACE       = "#161b22"
_CARD_BG       = "#1c2128"
_CARD_BORDER   = "#30363d"
_TEXT_PRIMARY  = "#e6edf3"
_TEXT_MUTED    = "#8b949e"
_ACCENT_BLUE   = "#58a6ff"

_COLOR_CRITICAL = "#f85149"
_COLOR_WARNING  = "#e3b341"
_COLOR_TIP      = "#3fb950"

_PRIORITY_META = {
    PRIORITY_CRITICAL: {"label": "🔴 CRITICAL",  "color": _COLOR_CRITICAL, "tab": "🔴 Khẩn Cấp"},
    PRIORITY_WARNING:  {"label": "🟡 WARNING",   "color": _COLOR_WARNING,  "tab": "🟡 Cảnh Báo"},
    PRIORITY_TIP:      {"label": "💡 TIP",        "color": _COLOR_TIP,      "tab": "💡 Gợi Ý"},
}

_DIALOG_STYLE = f"""
QDialog {{
    background: {_BG};
    color: {_TEXT_PRIMARY};
    font-family: 'Segoe UI', sans-serif;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: {_SURFACE};
    width: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: #30363d;
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
"""


# ---------------------------------------------------------------------------
# Suggestion Card Widget
# ---------------------------------------------------------------------------

class SuggestionCard(QFrame):
    action_triggered = pyqtSignal(str)   # emits action_key

    def __init__(self, suggestion: Suggestion, parent=None):
        super().__init__(parent)
        self._sug = suggestion
        self._build()

    def _build(self):
        meta  = _PRIORITY_META.get(self._sug.priority, _PRIORITY_META[PRIORITY_TIP])
        color = meta["color"]

        self.setObjectName("SuggestionCard")
        self.setStyleSheet(f"""
            QFrame#SuggestionCard {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-left: 4px solid {color};
                border-radius: 10px;
                padding: 0px;
            }}
            QLabel {{ border: none; background: transparent; color: {_TEXT_PRIMARY}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(6)

        # ── Row 1: icon + title + priority badge ──
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        icon_lbl = QLabel(self._sug.icon)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 18))
        icon_lbl.setFixedWidth(32)
        row1.addWidget(icon_lbl)

        title_lbl = QLabel(self._sug.title)
        title_lbl.setFont(QFont("Segoe UI Semibold", 10, QFont.Bold))
        title_lbl.setStyleSheet(f"color: {_TEXT_PRIMARY}; border: none; background: transparent;")
        title_lbl.setWordWrap(True)
        row1.addWidget(title_lbl, stretch=1)

        badge = QLabel(meta["label"])
        badge.setFont(QFont("Segoe UI", 8, QFont.Bold))
        badge.setStyleSheet(f"""
            QLabel {{
                color: {color};
                background: transparent;
                border: 1px solid {color};
                border-radius: 8px;
                padding: 2px 8px;
            }}
        """)
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedHeight(22)
        row1.addWidget(badge)
        root.addLayout(row1)

        # ── Row 2: category tag + detail ──
        cat_lbl = QLabel(f"  {self._sug.category}  ")
        cat_lbl.setFont(QFont("Segoe UI", 8))
        cat_lbl.setStyleSheet(f"""
            QLabel {{
                color: {_TEXT_MUTED};
                background: {_SURFACE};
                border: 1px solid {_CARD_BORDER};
                border-radius: 4px;
                padding: 1px 4px;
            }}
        """)
        cat_lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        detail_lbl = QLabel(self._sug.detail)
        detail_lbl.setFont(QFont("Segoe UI", 9))
        detail_lbl.setStyleSheet(f"color: {_TEXT_MUTED}; border: none; background: transparent;")
        detail_lbl.setWordWrap(True)

        root.addWidget(cat_lbl)
        root.addWidget(detail_lbl)

        # ── Row 3: action button (nếu có) ──
        if self._sug.action_key:
            row3 = QHBoxLayout()
            row3.addStretch()
            btn = QPushButton(self._sug.action_label)
            btn.setFont(QFont("Segoe UI Semibold", 9, QFont.Bold))
            btn.setFixedHeight(32)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color}22;
                    color: {color};
                    border: 1px solid {color};
                    border-radius: 8px;
                    padding: 0 18px;
                }}
                QPushButton:hover {{
                    background: {color}44;
                }}
                QPushButton:pressed {{
                    background: {color}66;
                }}
            """)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda: self.action_triggered.emit(self._sug.action_key))
            row3.addWidget(btn)
            root.addLayout(row3)


# ---------------------------------------------------------------------------
# Filter Tab Button
# ---------------------------------------------------------------------------

class _TabBtn(QPushButton):
    def __init__(self, label: str, color: str, parent=None):
        super().__init__(label, parent)
        self._color = color
        self._active = False
        self.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)
        self._refresh_style()

    def set_active(self, active: bool):
        self._active = active
        self._refresh_style()

    def _refresh_style(self):
        if self._active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {self._color}33;
                    color: {self._color};
                    border: 2px solid {self._color};
                    border-radius: 8px;
                    padding: 0 14px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: #8b949e;
                    border: 1px solid #30363d;
                    border-radius: 8px;
                    padding: 0 14px;
                }}
                QPushButton:hover {{
                    background: #21262d;
                    color: {_TEXT_PRIMARY};
                }}
            """)


# ---------------------------------------------------------------------------
# Main Dialog
# ---------------------------------------------------------------------------

class AIAdvisorDialog(QDialog):
    """
    Dialog hiển thị danh sách Smart Suggestions từ AIAdvisor.

    Parameters
    ----------
    advisor : AIAdvisor
        Instance đã được feed dữ liệu từ SystemMonitorHub.
    action_dispatcher : Callable[[str], None]
        Callback để MainWindow xử lý action_key khi user click "Áp Dụng Ngay".
    """

    def __init__(
        self,
        advisor: AIAdvisor,
        action_dispatcher: Optional[Callable[[str], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._advisor     = advisor
        self._dispatcher  = action_dispatcher
        self._active_filter: Optional[str] = None   # None = ALL
        self._tab_btns: Dict[Optional[str], _TabBtn] = {}
        self._cards_container: Optional[QWidget] = None

        self.setWindowTitle("🤖 AI Smart Suggestions – PC Optimizer")
        self.setMinimumSize(720, 560)
        self.resize(800, 620)
        self.setModal(True)
        self.setStyleSheet(_DIALOG_STYLE)

        self._build_ui()
        self._refresh()

        # Auto-refresh mỗi 10 giây
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(10_000)

    # ------------------------------------------------------------------
    # UI Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──
        header = QFrame()
        header.setStyleSheet(f"background: {_SURFACE}; border-bottom: 1px solid {_CARD_BORDER};")
        header.setFixedHeight(70)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 0, 20, 0)

        icon_lbl = QLabel("🤖")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 24))
        icon_lbl.setStyleSheet("border: none; background: transparent;")

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        t1 = QLabel("AI Smart Suggestions")
        t1.setFont(QFont("Segoe UI Semibold", 13, QFont.Bold))
        t1.setStyleSheet(f"color: {_TEXT_PRIMARY}; border: none; background: transparent;")
        t2 = QLabel("Phân tích hành vi hệ thống và gợi ý tối ưu thông minh – hoàn toàn offline")
        t2.setFont(QFont("Segoe UI", 9))
        t2.setStyleSheet(f"color: {_TEXT_MUTED}; border: none; background: transparent;")
        title_col.addWidget(t1)
        title_col.addWidget(t2)

        self._badge_lbl = QLabel()
        self._badge_lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self._badge_lbl.setAlignment(Qt.AlignCenter)
        self._badge_lbl.setFixedHeight(28)
        self._badge_lbl.setFixedWidth(135)
        self._badge_lbl.setStyleSheet(f"color: {_COLOR_CRITICAL}; border: 1px solid {_COLOR_CRITICAL}; border-radius: 8px; background: transparent; padding: 0 6px;")
        self._badge_lbl.hide()

        refresh_btn = QPushButton("🔄 Làm Mới")
        refresh_btn.setFont(QFont("Segoe UI", 9))
        refresh_btn.setFixedHeight(32)
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_ACCENT_BLUE};
                border: 1px solid {_ACCENT_BLUE};
                border-radius: 8px;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background: {_ACCENT_BLUE}22; }}
        """)
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self._refresh)

        h_layout.addWidget(icon_lbl)
        h_layout.addSpacing(10)
        h_layout.addLayout(title_col, stretch=1)
        h_layout.addWidget(self._badge_lbl)
        h_layout.addSpacing(8)
        h_layout.addWidget(refresh_btn)
        root.addWidget(header)

        # ── Filter Tabs ──
        tabs_frame = QFrame()
        tabs_frame.setStyleSheet(f"background: {_SURFACE}; border-bottom: 1px solid {_CARD_BORDER};")
        tabs_layout = QHBoxLayout(tabs_frame)
        tabs_layout.setContentsMargins(20, 8, 20, 8)
        tabs_layout.setSpacing(8)

        all_btn = _TabBtn("📋 Tất Cả", _ACCENT_BLUE)
        all_btn.set_active(True)
        all_btn.clicked.connect(lambda: self._set_filter(None, all_btn))
        self._tab_btns[None] = all_btn
        tabs_layout.addWidget(all_btn)

        for prio, meta in _PRIORITY_META.items():
            btn = _TabBtn(meta["tab"], meta["color"])
            btn.clicked.connect(lambda checked=False, p=prio, b=btn: self._set_filter(p, b))
            self._tab_btns[prio] = btn
            tabs_layout.addWidget(btn)

        tabs_layout.addStretch()
        root.addWidget(tabs_frame)

        # ── Scroll area for cards ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self._scroll, stretch=1)

        # ── Footer ──
        footer = QFrame()
        footer.setStyleSheet(f"background: {_SURFACE}; border-top: 1px solid {_CARD_BORDER};")
        footer.setFixedHeight(48)
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(20, 0, 20, 0)

        self._status_lbl = QLabel("💡 Lưu ý: Phân tích dựa trên dữ liệu hệ thống thời gian thực – offline, không gửi dữ liệu ra ngoài.")
        self._status_lbl.setFont(QFont("Segoe UI", 8))
        self._status_lbl.setStyleSheet(f"color: {_TEXT_MUTED}; border: none; background: transparent;")

        close_btn = QPushButton("Đóng")
        close_btn.setFont(QFont("Segoe UI", 9))
        close_btn.setFixedSize(80, 32)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_TEXT_PRIMARY};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
            }}
            QPushButton:hover {{ background: #21262d; }}
        """)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)

        f_layout.addWidget(self._status_lbl, stretch=1)
        f_layout.addWidget(close_btn)
        root.addWidget(footer)

    # ------------------------------------------------------------------
    # Refresh & Render
    # ------------------------------------------------------------------

    def _set_filter(self, prio: Optional[str], btn: _TabBtn):
        self._active_filter = prio
        for k, b in self._tab_btns.items():
            b.set_active(k == prio)
        self._render_cards(self._advisor.get_suggestions())

    def _refresh(self):
        suggestions = self._advisor.get_suggestions()
        self._update_badge(suggestions)
        self._render_cards(suggestions)

    def _update_badge(self, suggestions: List[Suggestion]):
        critical = sum(1 for s in suggestions if s.priority == PRIORITY_CRITICAL)
        warning  = sum(1 for s in suggestions if s.priority == PRIORITY_WARNING)

        if critical > 0:
            self._badge_lbl.setText(f"⚠ {critical} Khẩn Cấp")
            self._badge_lbl.setStyleSheet(f"color: {_COLOR_CRITICAL}; border: 1px solid {_COLOR_CRITICAL}; border-radius: 8px; background: transparent; font-weight: bold; padding: 0 10px;")
            self._badge_lbl.show()
        elif warning > 0:
            self._badge_lbl.setText(f"⚡ {warning} Cảnh Báo")
            self._badge_lbl.setStyleSheet(f"color: {_COLOR_WARNING}; border: 1px solid {_COLOR_WARNING}; border-radius: 8px; background: transparent; font-weight: bold; padding: 0 10px;")
            self._badge_lbl.show()
        else:
            self._badge_lbl.hide()

    def _render_cards(self, suggestions: List[Suggestion]):
        # Filter
        if self._active_filter is not None:
            filtered = [s for s in suggestions if s.priority == self._active_filter]
        else:
            filtered = suggestions

        # Container
        container = QWidget()
        container.setStyleSheet(f"background: {_BG};")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        if not filtered:
            self._build_empty_state(layout, all_ok=not suggestions)
        else:
            for sug in filtered:
                card = SuggestionCard(sug)
                card.action_triggered.connect(self._dispatch_action)
                layout.addWidget(card)

        layout.addStretch()
        self._scroll.setWidget(container)
        self._cards_container = container

    def _build_empty_state(self, layout: QVBoxLayout, all_ok: bool = True):
        spacer = QWidget()
        spacer.setFixedHeight(60)
        layout.addWidget(spacer)

        icon = QLabel("✅" if all_ok else "🔍")
        icon.setFont(QFont("Segoe UI Emoji", 48))
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("border: none; background: transparent;")

        if all_ok:
            msg1 = QLabel("Hệ Thống Đang Hoạt Động Tốt!")
            msg2 = QLabel(
                "Không có vấn đề nào được phát hiện lúc này.\n"
                "AI Advisor sẽ tiếp tục theo dõi và thông báo khi cần."
            )
        else:
            msg1 = QLabel("Không có gợi ý ở mức này")
            msg2 = QLabel("Thử chọn tab khác để xem các gợi ý theo mức ưu tiên.")

        msg1.setFont(QFont("Segoe UI Semibold", 13, QFont.Bold))
        msg1.setAlignment(Qt.AlignCenter)
        msg1.setStyleSheet(f"color: {_TEXT_PRIMARY}; border: none; background: transparent;")

        msg2.setFont(QFont("Segoe UI", 10))
        msg2.setAlignment(Qt.AlignCenter)
        msg2.setWordWrap(True)
        msg2.setStyleSheet(f"color: {_TEXT_MUTED}; border: none; background: transparent;")

        layout.addWidget(icon)
        layout.addSpacing(12)
        layout.addWidget(msg1)
        layout.addSpacing(6)
        layout.addWidget(msg2)

    def _dispatch_action(self, action_key: str):
        """Gửi action_key tới MainWindow dispatcher."""
        if self._dispatcher:
            try:
                self._dispatcher(action_key)
            except Exception:
                pass

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
