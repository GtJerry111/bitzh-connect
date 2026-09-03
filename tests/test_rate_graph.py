"""波形图：样本管理、纵轴缩放纪律、None 断段、平滑路径构建。"""
import pytest


@pytest.fixture(autouse=True)
def _instant(monkeypatch):
    """动画退化为即时（reduce-motion 路径），便于断言终态。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    monkeypatch.setattr("views.rate_graph.reduce_motion", lambda: True)


@pytest.fixture
def graph(qtbot):
    from views.rate_graph import RateGraph

    g = RateGraph()
    qtbot.addWidget(g)
    g.show()
    return g


def test_append_and_clear(graph):
    graph.append_sample(100.0, 200.0)
    graph.append_sample(None, 150.0)  # 上行缺失样本
    assert len(graph._samples) == 2
    graph.clear()
    assert len(graph._samples) == 0


def test_display_max_floor_prevents_heartbeat_mountain(graph):
    """纵轴下限 8 KB/s：心跳级流量不得把图顶满（防"网速很快"假象）"""
    graph.append_sample(100.0, 200.0)
    assert graph._display_max == pytest.approx(8192.0 * 1.2)


def test_display_max_follows_peak_with_headroom(graph):
    graph.append_sample(0.0, 10 * 1024 * 1024)  # 10 MB/s 尖峰
    assert graph._display_max == pytest.approx(10 * 1024 * 1024 * 1.2)


def test_segments_break_on_none(graph):
    """None 样本处断段：两个连续区间产出两条 path，不跨缺口插值"""
    points = [10.0, 20.0, None, 30.0, 40.0, 50.0]
    segs = graph._build_segments(points, dx=5.0, x0=0.0)
    assert len(segs) == 2
    # 单点不成段
    segs = graph._build_segments([None, 42.0, None], dx=5.0, x0=0.0)
    assert segs == []


def test_paint_smoke(graph):
    """有样本时 paintEvent 不炸（offscreen 真实绘制一遍）"""
    for i in range(5):
        graph.append_sample(float(i * 100), float(i * 500))
    graph.repaint()  # 不抛异常即通过
