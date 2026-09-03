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
    """每个测试：清空应用配置 + 屏蔽启动时的真实更新检查网络请求。

    注意：清空的是测试专用命名空间（"BITZH Connect Test"）而非真实 app 配置——
    直接清真实 QSettings 会把开发机上保存的用户名/配置一并抹掉。
    config_utils 的 APP_NAME/ORG_NAME 是 from-import 绑定的模块级名称，需就地 patch。
    """
    from PySide6.QtCore import QSettings

    monkeypatch.setattr("utils.config_utils.APP_NAME", "BITZH Connect Test")
    monkeypatch.setattr("utils.config_utils.ORG_NAME", "BITZH Connect Test")
    QSettings("BITZH Connect Test", "BITZH Connect Test").clear()
    # 注意必须 patch main_window 命名空间（from-import 绑定在这里）
    monkeypatch.setattr("views.main_window.check_for_updates", lambda *a, **k: None)
