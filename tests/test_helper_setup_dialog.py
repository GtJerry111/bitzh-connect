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
