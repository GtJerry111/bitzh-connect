# app/views/direct_ip_banner.py
"""主窗口直连 IP 失败警告条。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from common import theme


class DirectIpBanner(QWidget):
    dismissed = Signal()
    open_logs = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DirectIpBanner")
        self.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 8, 7)
        row.setSpacing(8)
        self.icon = QLabel("⚠")
        self.icon.setStyleSheet(f"color: {theme.semantic_color('working')};")
        row.addWidget(self.icon, 0, Qt.AlignTop)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setFont(theme.card_title_font())
        row.addWidget(self.message, 1)
        self.logs_btn = QPushButton("查看日志")
        self.logs_btn.setFlat(True)
        self.logs_btn.setCursor(Qt.PointingHandCursor)
        self.logs_btn.clicked.connect(self.open_logs)
        row.addWidget(self.logs_btn, 0, Qt.AlignTop)
        self.close_btn = QPushButton("×")
        self.close_btn.setFlat(True)
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self._dismiss)
        row.addWidget(self.close_btn, 0, Qt.AlignTop)
        self._apply_styles()
        self.hide()

    def _apply_styles(self):
        bg = "rgba(255,246,224,0.96)" if not theme.is_dark() else "rgba(72,54,30,0.96)"
        border = theme.with_alpha("working", 0.35)
        self.setStyleSheet(
            f"#DirectIpBanner {{ background: {bg};"
            f" border: 1px solid {border}; border-radius: 8px; }}"
        )
        self.message.setStyleSheet(f"color: {theme.semantic_color('ink')};")
        self.logs_btn.setStyleSheet(
            f"color: {theme.semantic_color('working')}; font-size: 12px; border: none;"
        )
        self.close_btn.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')}; border: none;"
        )

    def show_message(self, ok: int, total: int, failed_ips: list[str]):
        if failed_ips:
            suffix = "、".join(failed_ips[:3])
            if len(failed_ips) > 3:
                suffix += " 等"
            text = (
                f"直连 IP {ok}/{total} 已生效；{suffix} 未能添加。"
                "学校 VPN 不受影响。"
            )
        else:
            text = f"直连 IP {ok}/{total} 已生效。"
        self.message.setText(text)
        self.show()

    def _dismiss(self):
        self.hide()
        self.dismissed.emit()
