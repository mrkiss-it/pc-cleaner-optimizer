"""
ui/ai_copilot_widget.py – Interactive AI Copilot & System Doctor Widget (v4.5 Pro)
===================================================================================
Giao diện trò chuyện tương tác Fluent Dark Acrylic với AI Copilot:
  - Bảng chỉ số Telemetry & Điểm sức khỏe AI Health Score (0-100) thời gian thực.
  - Khung bong bóng hội thoại người dùng & trợ lý thông minh.
  - Nút bấm hành động trực tiếp 1-Click Action Buttons.
  - Các gợi ý câu hỏi nhanh (Quick Prompt Chips).
  - Tùy chọn cấu hình Gemini API hoặc dùng bộ não Offline Expert Brain.
"""
from __future__ import annotations

from typing import Optional, List, Dict, Any

from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QCursor, QFontMetrics
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QSizePolicy, QDialog,
    QCheckBox, QMessageBox, QComboBox
)

from core.ai_copilot import (
    AICopilotEngine, ChatMessage, CopilotAction, QUICK_PROMPTS, CloudAIBrain,
    DEFAULT_GEMINI_MODEL, GEMINI_KNOWN_MODELS, normalize_gemini_model,
)
from core.predictive_ai import PredictiveAIEngine, AIHealthReport, AutoPilotState


# ---------------------------------------------------------------------------
# Theme Colors
# ---------------------------------------------------------------------------
_BG           = "#0d1117"
_SURFACE      = "#161b22"
_CARD_BG      = "#1c2128"
_CARD_BORDER  = "#30363d"
_TEXT_PRIMARY = "#e6edf3"
_TEXT_MUTED   = "#8b949e"
_ACCENT_BLUE  = "#58a6ff"
_ACCENT_GREEN = "#3fb950"
_ACCENT_PURPLE = "#a371f7"


# ---------------------------------------------------------------------------
# API Key Configuration Dialog
# ---------------------------------------------------------------------------

class APIConfigDialog(QDialog):
    """Hộp thoại cấu hình Cloud Gemini API Key."""

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("⚙️ Cấu Hình Trí Tuệ Nhân Tạo (AI Engine Settings)")
        self.resize(480, 320)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {_SURFACE};
                color: {_TEXT_PRIMARY};
                font-family: 'Segoe UI', sans-serif;
            }}
            QLabel {{ color: {_TEXT_PRIMARY}; font-size: 13px; }}
            QLineEdit, QComboBox {{
                background-color: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 8px 12px;
                color: {_TEXT_PRIMARY};
                font-size: 13px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1px solid {_ACCENT_BLUE};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {_CARD_BG};
                color: {_TEXT_PRIMARY};
                selection-background-color: #21262d;
            }}
            QPushButton {{
                background-color: #21262d;
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 8px 16px;
                color: {_TEXT_PRIMARY};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #30363d;
            }}
            QCheckBox {{
                color: {_TEXT_PRIMARY};
                font-size: 13px;
            }}
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("🤖 Tùy Chọn Bộ Não AI Copilot")
        title.setFont(QFont("Segoe UI Semibold", 13, QFont.Bold))
        layout.addWidget(title)

        desc = QLabel(
            "Mặc định ứng dụng sử dụng **Offline Expert Brain** (nhanh, riêng tư, không cần mạng/key).\n"
            "Bạn có thể kích hoạt **Google Gemini Flash API** để AI đối thoại sâu hơn."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(desc)

        self.chk_cloud = QCheckBox("Kích hoạt Google Gemini API (Cloud LLM)")
        is_cloud = bool(self.config_manager.get("ai_copilot_cloud_enabled", False)) if self.config_manager else False
        self.chk_cloud.setChecked(is_cloud)
        layout.addWidget(self.chk_cloud)

        self.txt_api_key = QLineEdit()
        self.txt_api_key.setPlaceholderText("Dán mã Gemini API Key tại đây (AIzaSy...) — lưu ngoài git, trong %APPDATA%")
        self.txt_api_key.setEchoMode(QLineEdit.Password)
        key_val = str(self.config_manager.get("ai_copilot_gemini_api_key", "")) if self.config_manager else ""
        self.txt_api_key.setText(key_val)
        layout.addWidget(self.txt_api_key)

        model_row = QHBoxLayout()
        lbl_model = QLabel("Mô hình Gemini:")
        lbl_model.setStyleSheet(f"color: {_TEXT_MUTED};")
        self.combo_model = QComboBox()
        self.combo_model.setEditable(True)
        self.combo_model.setInsertPolicy(QComboBox.NoInsert)
        for mid in GEMINI_KNOWN_MODELS:
            self.combo_model.addItem(mid)
        cur_model = DEFAULT_GEMINI_MODEL
        if self.config_manager:
            cur_model = normalize_gemini_model(
                str(self.config_manager.get("ai_copilot_gemini_model", DEFAULT_GEMINI_MODEL))
            )
        idx = self.combo_model.findText(cur_model)
        if idx >= 0:
            self.combo_model.setCurrentIndex(idx)
        else:
            self.combo_model.insertItem(0, cur_model)
            self.combo_model.setCurrentIndex(0)
        self.combo_model.setToolTip(
            "gemini-flash-latest tự trỏ tới Flash mới nhất. Nếu API trả 404, 429 hoặc 503 (quá tải), "
            "ứng dụng sẽ thử các mô hình dự phòng."
        )
        model_row.addWidget(lbl_model)
        model_row.addWidget(self.combo_model, stretch=1)
        layout.addLayout(model_row)

        self.chk_autopilot = QCheckBox("Bật AI Auto-Pilot (tự bật/tắt Game Boost an toàn, có hoàn tác)")
        ap_on = bool(self.config_manager.get("ai_autopilot_enabled", True)) if self.config_manager else True
        self.chk_autopilot.setChecked(ap_on)
        layout.addWidget(self.chk_autopilot)

        mode_row = QHBoxLayout()
        lbl_mode = QLabel("Chế độ Auto-Pilot:")
        lbl_mode.setStyleSheet(f"color: {_TEXT_MUTED};")
        self.combo_ap_mode = QComboBox()
        self._ap_mode_values = ["auto", "off", "gaming", "eco", "work", "quiet", "balanced"]
        self.combo_ap_mode.addItems([
            "Tự động (theo ngữ cảnh)",
            "Tắt (chỉ đề xuất)",
            "Luôn Game Boost",
            "Luôn Tiết kiệm pin",
            "Luôn Làm việc",
            "Luôn Ban đêm",
            "Luôn Cân bằng",
        ])
        cur_mode = str(self.config_manager.get("ai_autopilot_mode", "auto")).lower() if self.config_manager else "auto"
        if cur_mode in self._ap_mode_values:
            self.combo_ap_mode.setCurrentIndex(self._ap_mode_values.index(cur_mode))
        mode_row.addWidget(lbl_mode)
        mode_row.addWidget(self.combo_ap_mode, stretch=1)
        layout.addLayout(mode_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("💾 Lưu Cài Đặt")
        btn_save.setStyleSheet(f"background-color: {_ACCENT_BLUE}; color: #ffffff; border: none;")
        btn_save.clicked.connect(self._save_settings)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    def _save_settings(self):
        if self.config_manager:
            self.config_manager.set("ai_copilot_cloud_enabled", self.chk_cloud.isChecked())
            self.config_manager.set("ai_copilot_gemini_api_key", self.txt_api_key.text().strip())
            chosen_model = normalize_gemini_model(self.combo_model.currentText())
            self.config_manager.set("ai_copilot_gemini_model", chosen_model)
            self.config_manager.set("ai_autopilot_enabled", self.chk_autopilot.isChecked())
            idx = self.combo_ap_mode.currentIndex()
            mode = self._ap_mode_values[idx] if 0 <= idx < len(self._ap_mode_values) else "auto"
            self.config_manager.set("ai_autopilot_mode", mode)
            if mode == "off":
                self.config_manager.set("ai_autopilot_enabled", False)
        self.accept()


class CopilotAskWorker(QThread):
    """Chạy AICopilotEngine.ask() ngoài UI thread (Gemini urlopen có thể tới 8s)."""
    finished_msg = pyqtSignal(object)

    def __init__(self, engine: AICopilotEngine, prompt: str, append_user: bool = False, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._prompt = prompt
        self._append_user = append_user

    def run(self):
        try:
            msg = self._engine.ask(self._prompt, append_user=self._append_user)
        except Exception as e:
            msg = e
        self.finished_msg.emit(msg)


# ---------------------------------------------------------------------------
# Chat Bubble Widget
# ---------------------------------------------------------------------------

class ChatBubbleWidget(QFrame):
    """Một bong bóng tin nhắn (người dùng hoặc trợ lý AI)."""
    action_triggered = pyqtSignal(str)   # emits action_key

    def __init__(self, message: ChatMessage, parent=None):
        super().__init__(parent)
        self.message = message
        self._build_ui()

    def _build_ui(self):
        is_user = (self.message.role == "user")
        self.setObjectName("ChatBubble")

        bg_color = "#1f293d" if is_user else _CARD_BG
        border_color = "#388bfd" if is_user else _CARD_BORDER
        align_margin = (80, 4, 12, 4) if is_user else (12, 4, 80, 4)

        self.setStyleSheet(f"""
            QFrame#ChatBubble {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 12px;
            }}
        """)

        outer_lay = QVBoxLayout(self)
        outer_lay.setContentsMargins(14, 10, 14, 12)
        outer_lay.setSpacing(6)

        # Header: Avatar & Name & Telemetry Badge
        hdr_lay = QHBoxLayout()
        hdr_lay.setSpacing(8)

        if is_user:
            lbl_name = QLabel("👤 Bạn")
            lbl_name.setFont(QFont("Segoe UI Semibold", 9, QFont.Bold))
            lbl_name.setStyleSheet("color: #58a6ff; background: transparent; border: none;")
            hdr_lay.addWidget(lbl_name)
            hdr_lay.addStretch(1)
        else:
            source_badge = " [Cloud Gemini]" if self.message.source == "cloud_gemini" else " [Offline Brain]"
            lbl_name = QLabel(f"🤖 AI Copilot & Bác Sĩ Hệ Thống{source_badge}")
            lbl_name.setFont(QFont("Segoe UI Semibold", 9, QFont.Bold))
            lbl_name.setStyleSheet(f"color: {_ACCENT_GREEN}; background: transparent; border: none;")
            hdr_lay.addWidget(lbl_name)

            if self.message.telemetry_badge:
                lbl_badge = QLabel(f"📊 {self.message.telemetry_badge}")
                lbl_badge.setFont(QFont("Segoe UI", 8))
                lbl_badge.setStyleSheet(f"color: {_TEXT_MUTED}; background: transparent; border: none;")
                hdr_lay.addWidget(lbl_badge)

            hdr_lay.addStretch(1)

        outer_lay.addLayout(hdr_lay)

        # Message Content (PlainText: Gemini/HTML must not be interpreted as Qt rich text)
        lbl_content = QLabel(self.message.content)
        lbl_content.setFont(QFont("Segoe UI", 9))
        lbl_content.setWordWrap(True)
        lbl_content.setTextFormat(Qt.PlainText)
        lbl_content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl_content.setStyleSheet(f"color: {_TEXT_PRIMARY}; background: transparent; border: none; line-height: 1.4;")
        outer_lay.addWidget(lbl_content)

        # Action Buttons (nếu là câu trả lời của AI và có actions)
        if not is_user and self.message.actions:
            actions_lay = QHBoxLayout()
            actions_lay.setSpacing(8)
            actions_lay.setContentsMargins(0, 6, 0, 0)

            for act in self.message.actions:
                btn_txt = act.label if act.label.startswith(act.icon) else f"{act.icon} {act.label}"
                btn = QPushButton(btn_txt)
                btn.setFont(QFont("Segoe UI Semibold", 9, QFont.Bold))
                btn.setCursor(QCursor(Qt.PointingHandCursor))
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2ea043);
                        color: #ffffff;
                        border: none;
                        border-radius: 6px;
                        padding: 6px 14px;
                    }}
                    QPushButton:hover {{
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2ea043, stop:1 #3fb950);
                    }}
                    QPushButton:pressed {{
                        background: #196127;
                    }}
                """)
                # Kết nối trực tiếp lambda với action_key
                btn.clicked.connect(lambda checked=False, k=act.key: self.action_triggered.emit(k))
                actions_lay.addWidget(btn)

            actions_lay.addStretch(1)
            outer_lay.addLayout(actions_lay)


# ---------------------------------------------------------------------------
# Main AI Copilot Widget
# ---------------------------------------------------------------------------

class AICopilotWidget(QWidget):
    """
    Widget Trợ Lý AI Copilot tương tác hoàn chỉnh.
    Có thể nhúng vào Tab của AIAdvisorDialog hoặc MainWindow.
    """
    action_triggered = pyqtSignal(str)   # emits action_key để MainWindow thực thi

    def __init__(self, config_manager=None, predictive_engine: Optional[PredictiveAIEngine] = None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.predictive_engine = predictive_engine
        self.copilot_engine = AICopilotEngine(
            config_manager=self.config_manager,
            predictive_engine=self.predictive_engine
        )
        self._ask_worker: Optional[CopilotAskWorker] = None
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {_BG};
                color: {_TEXT_PRIMARY};
                font-family: 'Segoe UI', sans-serif;
            }}
        """)
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(12, 10, 12, 10)
        main_lay.setSpacing(10)

        # ── 1. Header Telemetry & Health Strip ──
        header_frame = QFrame()
        header_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {_SURFACE};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
                padding: 4px;
            }}
        """)
        hdr_lay = QHBoxLayout(header_frame)
        hdr_lay.setContentsMargins(12, 6, 12, 6)
        hdr_lay.setSpacing(12)

        # Health Score Badge
        self.lbl_health_badge = QLabel("🩺 Sức Khỏe AI: 85/100 (TỐT)")
        self.lbl_health_badge.setFont(QFont("Segoe UI Semibold", 9, QFont.Bold))
        self.lbl_health_badge.setStyleSheet(f"color: {_ACCENT_GREEN}; border: none; background: transparent;")
        hdr_lay.addWidget(self.lbl_health_badge)

        # Auto-Pilot Mode Badge
        self.lbl_autopilot_badge = QLabel("⚖️ Auto-Pilot: Cân Bằng")
        self.lbl_autopilot_badge.setFont(QFont("Segoe UI Semibold", 9))
        self.lbl_autopilot_badge.setStyleSheet("color: #58a6ff; border: none; background: transparent;")
        hdr_lay.addWidget(self.lbl_autopilot_badge)

        self.lbl_busy = QLabel("")
        self.lbl_busy.setFont(QFont("Segoe UI", 8))
        self.lbl_busy.setStyleSheet("color: #e3b341; border: none; background: transparent;")
        self.lbl_busy.setWordWrap(False)
        self.lbl_busy.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hdr_lay.addWidget(self.lbl_busy, stretch=1)

        # Settings button
        btn_cfg = QPushButton("⚙️ Cấu Hình AI")
        btn_cfg.setFont(QFont("Segoe UI", 8))
        btn_cfg.setCursor(QCursor(Qt.PointingHandCursor))
        btn_cfg.setStyleSheet(f"""
            QPushButton {{
                background: #21262d;
                border: 1px solid {_CARD_BORDER};
                border-radius: 4px;
                padding: 4px 10px;
                color: {_TEXT_PRIMARY};
            }}
            QPushButton:hover {{
                background: #30363d;
            }}
        """)
        btn_cfg.clicked.connect(self._open_config_dialog)
        hdr_lay.addWidget(btn_cfg)

        main_lay.addWidget(header_frame)

        # ── 2. Scroll Area Chat Messages ──
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
            }}
            QScrollBar:vertical {{
                background: {_SURFACE};
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: #30363d;
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)

        self.chat_container = QWidget()
        self.chat_container.setStyleSheet("background: transparent;")
        self.chat_lay = QVBoxLayout(self.chat_container)
        self.chat_lay.setContentsMargins(12, 12, 12, 12)
        self.chat_lay.setSpacing(12)
        self.chat_lay.addStretch(1)

        self.scroll_area.setWidget(self.chat_container)
        main_lay.addWidget(self.scroll_area, stretch=1)

        # Render initial messages
        self._refresh_chat_display()

        # ── 3. Quick Prompt Chips Bar ──
        chips_frame = QFrame()
        chips_frame.setStyleSheet("background: transparent; border: none;")
        chips_lay = QHBoxLayout(chips_frame)
        chips_lay.setContentsMargins(0, 2, 0, 2)
        chips_lay.setSpacing(6)

        for prompt in QUICK_PROMPTS[:5]:
            chip_btn = QPushButton(prompt)
            chip_btn.setFont(QFont("Segoe UI", 8))
            chip_btn.setCursor(QCursor(Qt.PointingHandCursor))
            chip_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {_SURFACE};
                    border: 1px solid {_CARD_BORDER};
                    border-radius: 12px;
                    padding: 4px 10px;
                    color: {_TEXT_MUTED};
                }}
                QPushButton:hover {{
                    background-color: #21262d;
                    color: {_TEXT_PRIMARY};
                    border-color: {_ACCENT_BLUE};
                }}
            """)
            chip_btn.clicked.connect(lambda checked=False, p=prompt: self._send_user_text(p))
            chips_lay.addWidget(chip_btn)

        chips_lay.addStretch(1)
        main_lay.addWidget(chips_frame)

        # ── 4. Input Bar ──
        input_frame = QFrame()
        input_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {_SURFACE};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        inp_lay = QHBoxLayout(input_frame)
        inp_lay.setContentsMargins(8, 6, 8, 6)
        inp_lay.setSpacing(8)

        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("💬 Hỏi AI Copilot về tình trạng máy tính (Nhấn Enter để gửi)...")
        self.txt_input.setFont(QFont("Segoe UI", 10))
        self.txt_input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                color: {_TEXT_PRIMARY};
                padding: 4px 8px;
            }}
        """)
        self.txt_input.returnPressed.connect(self._handle_send_click)
        inp_lay.addWidget(self.txt_input, stretch=1)

        # Nút xóa lịch sử
        btn_clear = QPushButton("🗑️")
        btn_clear.setToolTip("Xóa lịch sử hội thoại")
        btn_clear.setCursor(QCursor(Qt.PointingHandCursor))
        btn_clear.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 6px 10px;
                color: {_TEXT_MUTED};
            }}
            QPushButton:hover {{
                background: #21262d;
                color: #f85149;
            }}
        """)
        btn_clear.clicked.connect(self._clear_history)
        inp_lay.addWidget(btn_clear)

        # Nút gửi
        self.btn_send = QPushButton("Gửi 🚀")
        self.btn_send.setFont(QFont("Segoe UI Semibold", 9, QFont.Bold))
        self.btn_send.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_send.setStyleSheet(f"""
            QPushButton {{
                background-color: {_ACCENT_BLUE};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                background-color: #388bfd;
            }}
        """)
        self.btn_send.clicked.connect(self._handle_send_click)
        inp_lay.addWidget(self.btn_send)

        main_lay.addWidget(input_frame)

        # Cập nhật telemetry định kỳ
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_telemetry_bar)
        self.timer.start(5000)
        self.update_telemetry_bar()

    def update_telemetry_bar(self):
        """Cập nhật thanh tiêu đề sức khỏe và Auto-Pilot."""
        if not self.predictive_engine:
            return
        try:
            report = self.predictive_engine.calculate_health_score()
            self.lbl_health_badge.setText(f"🩺 Sức Khỏe AI: {report.score}/100 ({report.grade})")
            self.lbl_health_badge.setStyleSheet(f"color: {report.grade_color}; font-weight: bold; border: none; background: transparent;")

            autopilot = self.predictive_engine.get_autopilot_state()
            self.lbl_autopilot_badge.setText(autopilot.badge_text)
            if not autopilot.is_auto_applied:
                self.lbl_autopilot_badge.setToolTip("Chỉ đề xuất — Auto-Pilot đang tắt hoặc chưa tự áp dụng.")
            else:
                self.lbl_autopilot_badge.setToolTip(autopilot.description)
        except Exception:
            pass

    def _open_config_dialog(self):
        dlg = APIConfigDialog(config_manager=self.config_manager, parent=self)
        dlg.exec_()

    def _handle_send_click(self):
        text = self.txt_input.text().strip()
        if text:
            self.txt_input.clear()
            self._send_user_text(text)

    def _set_busy(self, busy: bool, status: str = ""):
        self.txt_input.setEnabled(not busy)
        self.btn_send.setEnabled(not busy)
        self.btn_send.setText("…" if busy else "Gửi 🚀")
        if hasattr(self, "lbl_busy"):
            self._set_status_text(status if busy else "", is_error=False)

    def _set_status_text(self, text: str, is_error: bool = False):
        if not hasattr(self, "lbl_busy"):
            return
        full = (text or "").strip()
        self.lbl_busy.setToolTip(full)
        color = "#f85149" if is_error else "#e3b341"
        self.lbl_busy.setStyleSheet(f"color: {color}; border: none; background: transparent;")
        if not full:
            self.lbl_busy.setText("")
            return
        if is_error and not full.startswith("⚠️"):
            full = f"⚠️ {full}"
        metrics = QFontMetrics(self.lbl_busy.font())
        width = max(int(self.lbl_busy.width() or 0), 220)
        self.lbl_busy.setText(metrics.elidedText(full, Qt.ElideRight, width))

    def _send_user_text(self, text: str):
        if self._ask_worker and self._ask_worker.isRunning():
            return
        text = (text or "").strip()
        if not text:
            return

        self.copilot_engine.chat_history.append(ChatMessage(role="user", content=text))
        self._refresh_chat_display()
        self._set_busy(True, "⏳ Đang hỏi AI…")

        worker = CopilotAskWorker(self.copilot_engine, text, append_user=False, parent=self)
        self._ask_worker = worker
        worker.finished_msg.connect(self._on_ask_finished)
        worker.start()

    def _on_ask_finished(self, result):
        self._set_busy(False)
        if isinstance(result, Exception):
            err = ChatMessage(
                role="assistant",
                content=f"⚠️ Lỗi Copilot: {result}",
                source="offline_expert",
                telemetry_badge="Lỗi",
            )
            self.copilot_engine.chat_history.append(err)
        self._refresh_chat_display()
        if CloudAIBrain.last_error and hasattr(self, "lbl_busy"):
            # Keep a non-blocking hint if cloud failed but offline replied
            if "Cloud Gemini lỗi" in (self.copilot_engine.chat_history[-1].content if self.copilot_engine.chat_history else ""):
                hint = CloudAIBrain.last_error_short or CloudAIBrain.last_error
                self._set_status_text(hint, is_error=True)
                if CloudAIBrain.last_error:
                    self.lbl_busy.setToolTip(CloudAIBrain.last_error)

    def _refresh_chat_display(self):
        # Xóa các widget cũ trong chat_lay (trừ spacer cuối)
        while self.chat_lay.count() > 1:
            item = self.chat_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for msg in self.copilot_engine.chat_history:
            bubble = ChatBubbleWidget(msg, self.chat_container)
            bubble.action_triggered.connect(self._on_action_dispatched)
            self.chat_lay.insertWidget(self.chat_lay.count() - 1, bubble)

        # Tự cuộn xuống đáy
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        vbar = self.scroll_area.verticalScrollBar()
        vbar.setValue(vbar.maximum())

    def _on_action_dispatched(self, action_key: str):
        """Chuyển tiếp action_key lên MainWindow."""
        self.action_triggered.emit(action_key)

    def _clear_history(self):
        self.copilot_engine.clear_history()
        self._refresh_chat_display()
