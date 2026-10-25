from datetime import datetime, timezone

import pytest

from tang_monitor.address_check import apply_check, apply_fixed, apply_success, address_ok
from tang_monitor.devices import DeviceRecord

T = datetime(2026, 1, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 1, 2, tzinfo=timezone.utc)


def rec(addr="192.168.1.87", flag="none"):
    return DeviceRecord("d", addr, T, flag)


def test_new_device_success_on_current_address_is_ok():
    r = apply_success(None, "d", "192.168.1.87", T, {"192.168.1.87"})
    assert (r.device, r.last_ok_address, r.last_ok_at, r.flag) == ("d", "192.168.1.87", T, "none")
    assert address_ok(r, {"192.168.1.87"}) is True


def test_check_flags_when_pi_moved():
    assert apply_check(rec(), {"192.168.1.112"}).flag == "flagged"


def test_check_with_unknown_pi_addresses_changes_nothing():
    r = rec()
    assert apply_check(r, None) == r
    assert apply_success(r, "d", "1.2.3.4", T2, None).flag == "none"
    assert address_ok(r, None) is None


def test_fixed_only_from_flagged():
    assert apply_fixed(rec(flag="flagged")).flag == "fixed_untested"
    for f in ("none", "fixed_untested"):
        with pytest.raises(ValueError):
            apply_fixed(rec(flag=f))


def test_fixed_untested_stays_until_success_on_current_address():
    cur = {"192.168.1.112"}
    r = rec(flag="fixed_untested")
    r = apply_success(r, "d", "192.168.1.87", T2, cur)
    assert r.flag == "fixed_untested"
    assert apply_check(r, cur).flag == "fixed_untested"
    r = apply_success(r, "d", "192.168.1.112", T2, cur)
    assert r.flag == "none"


def test_flagged_stays_on_old_address_success():
    r = apply_success(rec(flag="flagged"), "d", "192.168.1.87", T2, {"192.168.1.112"})
    assert r.flag == "flagged"


def test_ipv6_and_multiple_pi_addresses_match_any():
    pis = {"192.168.1.87", "fd00::5"}
    assert apply_check(rec("fd00::5"), pis).flag == "none"
    assert address_ok(rec("fd00::5"), pis) is True
    assert address_ok(rec("fd00::6"), pis) is False
    assert address_ok(rec(flag="flagged"), pis) is False


def test_hostname_host_yields_no_address():
    from datetime import datetime, timezone
    from tang_monitor.address_check import success_address
    from tang_monitor.records import LoggedRequest, TangRequest
    e = LoggedRequest(TangRequest(datetime(2026, 1, 1, tzinfo=timezone.utc), "10.0.0.5",
                                  "pi.lan:7500", "rec", 200), "d", True)
    assert success_address(e) is None


def test_ipv6_host_normalized_to_canonical_form():
    from datetime import datetime, timezone
    from tang_monitor.address_check import success_address
    from tang_monitor.records import LoggedRequest, TangRequest
    e = LoggedRequest(TangRequest(datetime(2026, 1, 1, tzinfo=timezone.utc), "10.0.0.5",
                                  "[FD00:0:0::5]:7500", "rec", 200), "d", True)
    assert success_address(e) == "fd00::5"
