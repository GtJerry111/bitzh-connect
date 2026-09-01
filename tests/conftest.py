import os
import sys
from pathlib import Path

# 无头环境跑 Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# app/ 目录加入 import 路径（项目内模块以 utils./views./common. 顶层包互相引用）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
