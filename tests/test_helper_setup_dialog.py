def test_dialog_lists_operations_and_buttons(qtbot):
    from views.helper_setup_dialog import HelperSetupDialog

    dlg = HelperSetupDialog()
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "安装 TUN 特权服务"
    text = dlg.operations_text()
    assert "LaunchDaemon" in text or "开机" in text
    assert "quarantine" in text.lower() or "授权" in text
    assert dlg.install_button.text() == "安装"
    assert dlg.cancel_button.text() == "稍后"


def test_install_button_disables_and_runs_installer(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    calls = []
    monkeypatch.setattr(
        mod.helper_installer, "install_async",
        lambda on_done: calls.append(on_done),
    )
    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    dlg.install_button.click()
    assert calls  # 触发了安装
    assert not dlg.install_button.isEnabled()  # 安装中禁用防重复
    calls[0](True)  # 模拟安装成功回调
    # PySide6 6.11 起枚举不再支持实例级查找（dlg.Accepted 不可用），
    # 需经嵌套枚举 DialogCode 访问；断言语义不变
    assert dlg.result() == dlg.DialogCode.Accepted


def test_install_failure_shows_error_and_reenables(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    calls = []
    monkeypatch.setattr(
        mod.helper_installer, "install_async",
        lambda on_done: calls.append(on_done),
    )
    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    dlg.install_button.click()
    calls[0](False)
    assert dlg.install_button.isEnabled()
    assert "失败" in dlg.status_text()


def test_install_double_click_only_triggers_once(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    calls = []
    monkeypatch.setattr(
        mod.helper_installer, "install_async",
        lambda on_done: calls.append(on_done),
    )
    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    dlg.install_button.click()
    dlg.install_button.click()  # 安装中禁用，"安装"不应二次触发授权
    assert len(calls) == 1


def test_cancel_rejects_without_running_installer(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    calls = []
    monkeypatch.setattr(
        mod.helper_installer, "install_async",
        lambda on_done: calls.append(on_done),
    )
    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    dlg.cancel_button.click()
    assert dlg.result() == dlg.DialogCode.Rejected
    assert not calls  # "稍后"不触发安装


def test_cancel_disabled_while_installing(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    calls = []
    monkeypatch.setattr(
        mod.helper_installer, "install_async",
        lambda on_done: calls.append(on_done),
    )
    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    dlg.install_button.click()
    # 授权框已弹出，关闭对话框无法取消授权，故"稍后"须禁用
    assert not dlg.cancel_button.isEnabled()


def test_cancel_reenabled_after_failure(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    calls = []
    monkeypatch.setattr(
        mod.helper_installer, "install_async",
        lambda on_done: calls.append(on_done),
    )
    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    dlg.install_button.click()
    assert not dlg.cancel_button.isEnabled()
    calls[0](False)  # 失败/取消授权后回到可交互状态
    assert dlg.cancel_button.isEnabled()


def test_installer_exception_shows_error_and_reenables(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    def boom(on_done):
        raise RuntimeError("提权进程启动失败")

    monkeypatch.setattr(mod.helper_installer, "install_async", boom)
    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    dlg.install_button.click()  # 不应把异常抛给 Qt 事件循环
    assert dlg.install_button.isEnabled()
    assert dlg.cancel_button.isEnabled()
    assert "失败" in dlg.status_text()
