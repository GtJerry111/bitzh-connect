# app/views/resource_section.py
"""校内资源入口（方案 B 胶囊按钮）。连接成功后展开，点击用默认浏览器打开。

资源仅两个（电子图书馆、统一门户），用户明确不需要自定义管理（YAGNI）。
"""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from common import theme
from common.constants import RESOURCES


class ResourceSection(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)
        row.setAlignment(Qt.AlignCenter)
        self._buttons = []
        for name, url in RESOURCES:
            btn = QPushButton(name)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumWidth(120)  # 两胶囊等宽（文字长度不一，由宽度补齐视觉平衡）
            btn.setProperty("resource_url", url)
            btn.clicked.connect(
                lambda _checked=False, u=url: QDesktopServices.openUrl(QUrl(u))
            )
            row.addWidget(btn)
            self._buttons.append(btn)
        self.setLayout(row)
        self.refresh_theme()

    def refresh_theme(self):
        """胶囊样式：BIT 绿描边，hover 轻填充（8%），pressed 加深（18%）。

        桌面端必须有 hover 反馈（"界面在听"）；瞬时动作的 press 反馈
        与动作重量匹配——点开浏览器是轻动作，不再整颗填满绿。
        """
        for btn in self._buttons:
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: {theme.semantic_color("accent")};
                    border: 1px solid {theme.semantic_color("accent")};
                    border-radius: 14px;
                    padding: 5px 14px;
                    background: transparent;
                }}
                QPushButton:hover {{
                    background-color: {theme.with_alpha("accent", 0.08)};
                }}
                QPushButton:pressed {{
                    background-color: {theme.with_alpha("accent", 0.18)};
                }}
            """)
