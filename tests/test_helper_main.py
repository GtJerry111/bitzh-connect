from privileged_helper.main import _parse_allowed_uid


def test_parse_allowed_uid():
    assert _parse_allowed_uid(["--allowed-uid", "501"]) == 501
    assert _parse_allowed_uid([]) == 0
    assert _parse_allowed_uid(["--allowed-uid", "abc"]) == 0
