from services.update_service import ReleaseInfo
from views.update_dialog import UpdateDialog


def _release():
    return ReleaseInfo(
        version="1.5.0",
        tag="v1.5.0",
        body="更新内容\n\n- 应用内更新\n- 镜像下载",
        html_url="https://github.com/GtJerry111/bitzh-connect/releases/tag/v1.5.0",
        assets=(
            {
                "name": "bitzh-connect-darwin-arm64.zip",
                "browser_download_url": "https://example/arm64.zip",
                "size": 100,
            },
        ),
    )


def test_stage1_buttons_and_notes(qtbot):
    asset = _release().assets[0]
    dialog = UpdateDialog(_release(), asset, "a" * 64, "auto")
    qtbot.addWidget(dialog)
    assert dialog.stack.currentIndex() == 0
    assert dialog.download_btn.text() == "下载并安装"
    assert dialog.later_btn.text() == "稍后"
    assert "应用内更新" in dialog.notes.toPlainText()


def test_progress_updates_bar_and_meta(qtbot):
    dialog = UpdateDialog(_release(), _release().assets[0], None, "auto")
    qtbot.addWidget(dialog)
    dialog._on_progress(50, 100)
    assert dialog.progress.value() == 50
    assert "50%" in dialog.progress_meta.text()


def test_source_label_is_mirror(qtbot):
    dialog = UpdateDialog(_release(), _release().assets[0], None, "auto")
    qtbot.addWidget(dialog)
    dialog._on_source(
        "https://gh-proxy.com/https://github.com/x/y.zip"
    )
    assert "gh-proxy.com" in dialog.source_meta.text()


def test_error_page(qtbot):
    dialog = UpdateDialog(_release(), _release().assets[0], None, "auto")
    qtbot.addWidget(dialog)
    dialog._on_download_error("SHA256 校验失败")
    assert dialog.stack.currentIndex() == 3
    assert "SHA256" in dialog.error_message.text()
