import ipaddress

from utils.direct_ip import (
    MAX_DIRECT_IPS,
    ip_set_changed,
    parse_direct_ips,
    split_pasted_ips,
    status_for_ip,
    validate_direct_ips,
)


def test_split_chinese_separators_and_fullwidth():
    text = "10.182.37.18，10.182.37.19、10.182.37.20；１０.１８２.３７.２１"
    assert split_pasted_ips(text) == [
        "10.182.37.18",
        "10.182.37.19",
        "10.182.37.20",
        "10.182.37.21",
    ]


def test_split_strips_quotes_and_trailing_chinese_period():
    assert split_pasted_ips("“10.182.37.18”\n（10.182.37.19）。") == [
        "10.182.37.18",
        "10.182.37.19",
    ]


def test_parse_direct_ips_dedupes_and_drops_invalid_for_config():
    assert parse_direct_ips("10.0.0.1\n10.0.0.1\n10.0.0.999\n") == ["10.0.0.1"]


def test_validate_reports_invalid_duplicate_reserved_and_forbidden():
    result = validate_direct_ips(
        ["10.0.0.1", "10.0.0.1", "999.1.1.1", "127.0.0.1", "10.0.0.2"],
        forbidden_ips={"10.0.0.2"},
    )
    assert result.valid == ["10.0.0.1"]
    assert [i.reason for i in result.issues] == [
        "duplicate",
        "invalid",
        "reserved",
        "forbidden",
    ]
    assert result.issues[0].index == 1
    assert result.issues[1].index == 2


def test_validate_skips_local_network():
    result = validate_direct_ips(
        ["10.0.0.20", "10.182.37.18"],
        local_networks=(ipaddress.IPv4Network("10.0.0.0/24"),),
    )
    assert result.valid == ["10.182.37.18"]
    assert result.skipped_local == ["10.0.0.20"]
    assert result.issues == []


def test_status_for_ip():
    assert status_for_ip("1.1.1.1", {"1.1.1.1": True}, set()) == "ok"
    assert status_for_ip("1.1.1.1", {"1.1.1.1": False}, set()) == "failed"
    assert status_for_ip("1.1.1.1", {"1.1.1.1": True}, {"1.1.1.1"}) == "pending"
    assert status_for_ip("1.1.1.1", {}, set()) == "unapplied"


def test_ip_set_changed_ignores_order():
    assert ip_set_changed(["1.1.1.1", "2.2.2.2"], ["2.2.2.2", "1.1.1.1"]) is False
    assert ip_set_changed(["1.1.1.1"], []) is True


def test_max_constant():
    assert MAX_DIRECT_IPS == 100
