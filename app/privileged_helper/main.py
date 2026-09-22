"""特权 helper 可执行入口（Nuitka 单独打包为 bitzh-helper）。

以 root 常驻运行，由 LaunchDaemon 管理；安装者 uid 通过命令行传入，
用于 socket 权限与 peer 校验（默认 0，即仅 root，属保守兜底）。
"""
import os
import sys

# 源码树中 main.py 位于 app/privileged_helper/；把 app/ 加入 path 以 import 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from privileged_helper.server import HelperServer  # noqa: E402


def _parse_allowed_uid(argv) -> int:
    # 支持：bitzh-helper --allowed-uid 501
    if "--allowed-uid" in argv:
        idx = argv.index("--allowed-uid")
        if idx + 1 < len(argv):
            try:
                return int(argv[idx + 1])
            except ValueError:
                pass
    return 0


def main():
    allowed_uid = _parse_allowed_uid(sys.argv[1:])
    HelperServer(allowed_uid=allowed_uid).serve_forever()


if __name__ == "__main__":
    main()
