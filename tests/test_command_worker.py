"""CommandWorker 进程生命周期回归测试。"""
import sys
import time


def test_stop_before_spawn_terminates_process(qtbot):
    """stop() 先于 run() 中 Popen 完成时，终止意图必须被记录并在 spawn 后补杀。

    未修复时 stop() 空转，子进程会跑满 30s 成为无人看管的存活进程。
    """
    from utils.set_proxy import CommandWorker

    worker = CommandWorker(
        command_args=[sys.executable, "-c", "import time; time.sleep(30)"],
        proxy_enabled=False,
        window=None,
    )
    finished_codes = []
    worker.finished.connect(lambda code: finished_codes.append(code))

    worker.stop()  # 进程尚未 spawn，只应记录终止意图
    assert worker._stop_requested is True

    start = time.monotonic()
    worker.start()
    # 给足超时保证 finished 必然触发（未修复时跑满 30s），再断言耗时
    qtbot.waitUntil(lambda: len(finished_codes) == 1, timeout=35000)
    elapsed = time.monotonic() - start
    worker.wait(3000)

    assert elapsed < 25  # 进程被提前终止，远未跑满 30s
