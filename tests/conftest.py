import os
import sys
from pathlib import Path

# 无头环境跑 Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# app/ 目录加入 import 路径（项目内模块以 utils./views./common. 顶层包互相引用）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import pytest


@pytest.fixture(autouse=True)
def _isolate_app(monkeypatch):
    """每个测试：清空应用配置 + 屏蔽启动时的真实更新检查网络请求。"""
    from PySide6.QtCore import QSettings

    from common.constants import APP_NAME, ORG_NAME

    QSettings(ORG_NAME, APP_NAME).clear()
    # 注意必须 patch main_window 命名空间（from-import 绑定在这里）
    monkeypatch.setattr("views.main_window.check_for_updates", lambda *a, **k: None)
