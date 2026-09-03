# app/views/rate_graph.py
"""已连接态实时速率波形图（QPainter 自绘，不引入 QCharts）。

形态（设计规格定稿）：
- 双线不对称：下行 = accent 绿 2.0pt 描边 + 垂直渐变填充（主导）；
  上行 = working 赭石 1.5pt 纯描边（辅助）；上下行共用纵轴（真实比例）
- 单调三次插值（Fritsch–Carlson）：不过冲、不说谎，低速抖动被安抚成波纹
- 纵轴自适应窗口峰值 ×1.2，下限 8 KB/s（防心跳流量画成巨浪），
  缩放 250ms OutCubic 缓动（尖峰出窗骤降时曲线不"跳起"）
- 每秒滚动：clip + translate 250ms 右进左出；无网格/刻度/图例/端点圆点
- 样本三态：有值 / 0 / None（缺失段断线不插值）；clear() 清空（断连不画假连续）
- reduce-motion：滚动/缩放即时化；数据 1s 刷新本身不是装饰，不退化
"""
from collections import deque

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from common import theme
from utils.motion_utils import ANIMATION_DURATION_MS, reduce_motion

_GRAPH_HEIGHT = 64        # 控件总高（328:64 ≈ 5:1 带状比例）
_INSET_X = 2.0            # 左右留白：容纳描边半径与 RoundCap 端点
_INSET_Y = 4.0            # 上下留白：防填充/描边贴边
_MIN_SCALE = 8192.0       # 纵轴下限 8 KB/s
_HEADROOM = 1.2           # 峰值余量
_MAX_SAMPLES = 61         # 60s 窗口 + 滚动动画期间的新样本


class RateGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_GRAPH_HEIGHT)
        self._samples = deque(maxlen=_MAX_SAMPLES)  # (up, down)，B/s float 或 None
        self._display_max = _MIN_SCALE
        self._scroll_t = 1.0  # 1 = 静止；刚入样时 0→1 驱动右进左出

    # ---- 对外接口 ----

    def append_sample(self, up_bps: float | None, down_bps: float | None):
        self._samples.append((up_bps, down_bps))
        self._retarget_max()
        if reduce_motion():
            self._scroll_t = 1.0
            self.update()
            return
        # 滚动动画（身份守卫 + isValid 纪律同 animate_label_color）
        old = getattr(self, "_scroll_anim", None)
        if old is not None:
            self._scroll_anim = None
            if isValid(old):
                old.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(ANIMATION_DURATION_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._on_scroll_frame)
        self._scroll_anim = anim
        anim.start()

    def clear(self):
        """断开/重连时清空：重连后画跨断点的连续曲线是假象。"""
        self._samples.clear()
        self._retarget_max()
        self.update()

    # ---- 内部 ----

    def _on_scroll_frame(self, t):
        self._scroll_t = float(t)
        self.update()

    def _retarget_max(self):
        peak = _MIN_SCALE
        for up, down in self._samples:
            for v in (up, down):
                if v is not None:
                    peak = max(peak, v)
        target = peak * _HEADROOM
        if reduce_motion():
            self._display_max = target
            return
        old = getattr(self, "_scale_anim", None)
        if old is not None:
            self._scale_anim = None
            if isValid(old):
                old.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(ANIMATION_DURATION_MS)
        anim.setStartValue(self._display_max)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._on_scale_frame)
        self._scale_anim = anim
        anim.start()

    def _on_scale_frame(self, v):
        self._display_max = max(float(v), 1.0)
        self.update()

    def _build_segments(self, points, dx, x0):
        """像素点列 → 每段连续有效区间一个单调三次插值 path（None 处断开不插值）。

        Fritsch–Carlson：区间斜率 d_i，切线 m_i 初值取邻区间均值、
        峰/谷/平台归零、再按 a²+b²≤9 钳制——保证不过冲、保单调。
        返回 list[QPainterPath]：填充/描边各自按段闭合或绘制。
        """
        segs = []
        cur = []
        for i, v in enumerate(points):
            if v is None:
                if cur:
                    segs.append(cur)
                    cur = []
            else:
                cur.append(i)
        if cur:
            segs.append(cur)

        paths = []
        for seg in segs:
            n = len(seg)
            if n == 1:
                continue  # 单点不成线（靠后续样本连成段）
            ys = [points[i] for i in seg]
            xs = [x0 + i * dx for i in seg]
            # 区间斜率（像素坐标：y 向下为正）
            d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
            m = [0.0] * n
            m[0] = d[0]
            m[-1] = d[-1]
            for i in range(1, n - 1):
                if d[i - 1] * d[i] <= 0:
                    m[i] = 0.0
                else:
                    m[i] = (d[i - 1] + d[i]) / 2
            for i in range(n - 1):
                if d[i] == 0:
                    m[i] = m[i + 1] = 0.0
                else:
                    a = m[i] / d[i]
                    b = m[i + 1] / d[i]
                    s = a * a + b * b
                    if s > 9:
                        tau = 3.0 / (s ** 0.5)
                        m[i] = tau * a * d[i]
                        m[i + 1] = tau * b * d[i]
            path = QPainterPath()
            path.moveTo(xs[0], ys[0])
            for i in range(n - 1):
                h = xs[i + 1] - xs[i]
                path.cubicTo(
                    xs[i] + h / 3, ys[i] + m[i] * h / 3,
                    xs[i + 1] - h / 3, ys[i + 1] - m[i + 1] * h / 3,
                    xs[i + 1], ys[i + 1],
                )
            paths.append(path)
        return paths

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        plot_left = _INSET_X
        plot_w = self.width() - 2 * _INSET_X
        plot_top = _INSET_Y
        plot_h = self.height() - 2 * _INSET_Y
        plot_bottom = plot_top + plot_h

        # 基线：hairline（cosmetic pen 恒 1 物理像素）
        pen = QPen(QColor(theme.semantic_color("separator")))
        pen.setWidth(0)
        painter.setPen(pen)
        painter.drawLine(plot_left, plot_bottom, plot_left + plot_w, plot_bottom)

        n = len(self._samples)
        if n >= 2:
            # 右对齐：最新样本钉在右缘；滚动动画期间整体右移 dx×(1-t)（新点自右缘滑入）
            dx = plot_w / 60.0
            x0 = self.width() - _INSET_X - (n - 1) * dx + dx * (1 - self._scroll_t)

            def to_y(v):
                return plot_bottom - min(v / self._display_max, 1.0) * plot_h

            ups = [None if s[0] is None else to_y(s[0]) for s in self._samples]
            downs = [None if s[1] is None else to_y(s[1]) for s in self._samples]

            painter.save()
            painter.setClipRect(plot_left, plot_top, plot_w, plot_h + 2)

            down_segments = self._build_segments(downs, dx, x0)
            up_segments = self._build_segments(ups, dx, x0)

            # 下行填充：垂直渐变（锚定绘图区——低流量时整体更淡，安静退后）；
            # 逐段闭合到基线（None 缺口的段各自独立填充，不跨缺口）
            if down_segments:
                gradient = QLinearGradient(0, plot_top, 0, plot_bottom)
                top_alpha = 0.22 if theme.is_dark() else 0.16
                # 注意：QColor 不认 rgba() 字符串（那是 QSS 语法）——必须 setAlphaF
                gradient.setColorAt(0, theme.qcolor("accent", top_alpha))
                gradient.setColorAt(1, theme.qcolor("accent", 0.0))
                for seg_path in down_segments:
                    br = seg_path.boundingRect()
                    fill = QPainterPath(seg_path)
                    fill.lineTo(br.right(), plot_bottom)
                    fill.lineTo(br.left(), plot_bottom)
                    fill.closeSubpath()
                    painter.fillPath(fill, gradient)
                pen = QPen(QColor(theme.semantic_color("accent")))
                pen.setWidthF(2.0)
                pen.setJoinStyle(Qt.RoundJoin)
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                for seg_path in down_segments:
                    painter.drawPath(seg_path)

            # 上行：赭石细线，无填充
            pen = QPen(QColor(theme.semantic_color("working")))
            pen.setWidthF(1.5)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            for seg_path in up_segments:
                painter.drawPath(seg_path)

            painter.restore()

        painter.end()
