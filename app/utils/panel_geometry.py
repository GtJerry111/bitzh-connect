"""菜单栏面板定位：图标下缘居中，夹紧在屏幕可用区域内（纯函数，与平台解耦）。"""
from PySide6.QtCore import QRect, QSize

_EDGE_MARGIN = 8      # 面板与屏幕左右边缘的最小间距
_ICON_GAP = 4         # 面板顶边与图标（菜单栏）下缘的间距
_FALLBACK_MARGIN = 12  # 图标坐标失效时退化到屏幕右上角的右边距


def _left_for_right_edge(right: int, width: int, margin: int) -> int:
    """由期望的右边界反推左边界。

    QRect.right() 是闭区间（right == left + width - 1），所以要 +1 补偿，
    否则实际右边距会比 margin 多 1 像素。
    """
    return right - margin - width + 1


def panel_geometry(icon_rect, screen_rect: QRect, panel_size: QSize) -> QRect:
    """计算面板在全局屏幕坐标中的位置。

    icon_rect: 状态栏图标的全局 QRect；为 None（图标被刘海/拥挤挤出）时
    退化到屏幕右上角。screen_rect: 该屏 availableGeometry。
    """
    w, h = panel_size.width(), panel_size.height()
    if icon_rect is None or icon_rect.isNull() or icon_rect.isEmpty():
        x = _left_for_right_edge(screen_rect.right(), w, _FALLBACK_MARGIN)
        return QRect(x, screen_rect.top() + _ICON_GAP, w, h)
    # QRect 的中心也是闭区间，偏移量取 (w - 1) // 2 才能与图标中心对齐
    x = icon_rect.center().x() - (w - 1) // 2
    x = max(screen_rect.left() + _EDGE_MARGIN,
            min(x, _left_for_right_edge(screen_rect.right(), w, _EDGE_MARGIN)))
    y = icon_rect.bottom() + _ICON_GAP
    return QRect(x, y, w, h)
