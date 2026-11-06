from datetime import datetime, timedelta, timezone

import pytest

from tang_monitor import commands
from tang_monitor.keys import KeyInfo
from tang_monitor.naming import Namer
from tang_monitor.options import Options, load_options, options_from_dict
from tang_monitor.records import TangRequest
from tang_monitor.state import AppState

T = datetime(2026, 1, 1, 15, 42, tzinfo=timezone.utc)
KEYS = [KeyInfo("a", "signing", "S256A", "S1A"), KeyInfo("b", "exchange", "S256B", "S1B")]
NAMES = {"192.168.1.50": "server.lan", "192.168.1.66": "stranger.lan"}


def make_state(tmp_path, reserved=True):
    namer = Namer(lookup=NAMES.get)
    return AppState(tmp_path, Options(["server.lan"], reserved), KEYS, namer)


def req(ip="192.168.1.50", host="192.168.1.87:7500", kind="rec", status=200):
    return TangRequest(T, ip, host, kind, status)


def test_load_options_defaults_and_values(tmp_path):
    assert load_options(tmp_path / "missing.json") == Options([], False)
    p = tmp_path / "o.json"
    p.write_text('{"known_devices": ["x"], "address_reserved": true}')
    assert load_options(p) == Options(["x"], True)


async def test_success_from_known_device_records_address(tmp_path):
    s = make_state(tmp_path)
    s.set_pi_addresses({"192.168.1.87"})
    entry = await s.handle_request(req())
    assert entry.device == "server.lan" and entry.known
    snap = s.snapshot()
    assert snap["devices"][0]["last_ok_address"] == "192.168.1.87"
    assert snap["devices"][0]["address_ok"] is True
    assert snap["requests"][0]["device"] == "server.lan"


async def test_device_row_carries_the_devices_own_last_ip(tmp_path):
    # The Devices row shows the device's own address separately from the Pi address it reaches Tang at.
    s = AppState(tmp_path, Options(["server.lan"], True), KEYS,
                 Namer(lookup={"192.168.1.50": "server.lan", "192.168.1.51": "server.lan"}.get))
    await s.handle_request(req(ip="192.168.1.50"))
    await s.handle_request(req(ip="192.168.1.51", status=404))  # newest request, even a failed one
    d = s.snapshot()["devices"][0]
    assert d["last_ip"] == "192.168.1.51"
    assert d["last_ok_address"] == "192.168.1.87"


async def test_unknown_device_logged_not_tracked(tmp_path):
    s = make_state(tmp_path)
    entry = await s.handle_request(req(ip="192.168.1.66"))
    assert not entry.known
    snap = s.snapshot()
    assert snap["devices"] == [] and snap["requests"][0]["known"] is False


async def test_unnamed_device_uses_ip(tmp_path):
    s = make_state(tmp_path)
    entry = await s.handle_request(req(ip="10.0.0.9"))
    assert entry.device == "10.0.0.9"


async def flagged_state(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req())
    for _ in range(3):
        s.set_pi_addresses({"192.168.1.112"})
    return s


async def test_mark_fixed_paths(tmp_path):
    s = await flagged_state(tmp_path)
    assert s.mark_fixed("nope") == "not_found"
    assert s.mark_fixed("server.lan") == "ok"
    assert s.snapshot()["devices"][0]["flag"] == "fixed_untested"
    assert s.mark_fixed("server.lan") == "not_flagged"


async def test_forget(tmp_path):
    s = await flagged_state(tmp_path)
    assert s.forget("server.lan") == {"forgot": True, "still_known_via_options": True}
    assert s.forget("server.lan") == {"forgot": False, "still_known_via_options": True}
    assert s.snapshot()["devices"] == []


async def test_snapshot_commands_null_when_unverified(tmp_path):
    s = await flagged_state(tmp_path)
    snap = s.snapshot()
    assert snap["commands_verified"] is False
    assert snap["devices"][0]["flag"] == "flagged"
    assert snap["devices"][0]["commands"] is None
    assert snap["test_commands"] is None


async def test_snapshot_commands_present_when_verified_and_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(commands, "COMMANDS_VERIFIED", True)
    s = make_state(tmp_path)
    await s.handle_request(req())
    snap = s.snapshot()
    assert snap["devices"][0]["commands"] is None  # not flagged
    for _ in range(3):
        s.set_pi_addresses({"fe80::1", "192.168.1.112", "10.0.0.1"})
    snap = s.snapshot()
    assert snap["primary_address"] == "10.0.0.1"
    cmds = snap["devices"][0]["commands"]
    assert set(cmds) == {"find", "fix", "test", "one_step_fix", "one_step_test"}
    assert "10.0.0.1:7500" in cmds["fix"]  # first IPv4 in sorted order
    assert set(snap["test_commands"]) == {"find", "test", "one_step_test"}
    assert snap["pi_addresses"] == sorted(["fe80::1", "192.168.1.112", "10.0.0.1"])


async def test_set_pi_addresses_none_keeps_flags(tmp_path):
    s = await flagged_state(tmp_path)
    s.set_pi_addresses(None)
    snap = s.snapshot()
    assert snap["pi_addresses"] is None
    assert snap["devices"][0]["flag"] == "flagged"
    assert snap["devices"][0]["address_ok"] is None
    assert snap["devices"][0]["commands"] is None


async def test_snapshot_commands_shown_with_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("TANG_COMMANDS_VERIFIED", "1")
    snap = make_state(tmp_path).snapshot()
    assert snap["commands_verified"] is True
    assert set(snap["test_commands"]) == {"find", "test", "one_step_test"}


def flag_of(s):
    return s.snapshot()["devices"][0]["flag"]


def address_ok_of(s):
    return s.snapshot()["devices"][0]["address_ok"]


async def test_address_ok_stays_on_until_the_flag_is_set(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req())
    s.set_pi_addresses({"192.168.1.112"})
    s.set_pi_addresses({"192.168.1.112"})
    assert address_ok_of(s) is True
    s.set_pi_addresses({"192.168.1.112"})
    assert address_ok_of(s) is False


async def test_flag_needs_three_consecutive_mismatching_checks(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req())
    s.set_pi_addresses({"192.168.1.112"})
    s.set_pi_addresses({"192.168.1.112"})
    assert flag_of(s) == "none"
    s.set_pi_addresses({"192.168.1.112"})
    assert flag_of(s) == "flagged"


async def test_matching_check_resets_mismatch_count(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req())
    s.set_pi_addresses({"192.168.1.112"})
    s.set_pi_addresses({"192.168.1.112"})
    s.set_pi_addresses({"192.168.1.87"})
    s.set_pi_addresses({"192.168.1.112"})
    s.set_pi_addresses({"192.168.1.112"})
    assert flag_of(s) == "none"


async def test_unknown_addresses_neither_count_nor_reset(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req())
    s.set_pi_addresses({"192.168.1.112"})
    s.set_pi_addresses(None)
    s.set_pi_addresses({"192.168.1.112"})
    s.set_pi_addresses(None)
    assert flag_of(s) == "none"
    s.set_pi_addresses({"192.168.1.112"})
    assert flag_of(s) == "flagged"


async def test_success_on_current_address_resets_mismatch_count(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req())
    s.set_pi_addresses({"192.168.1.112"})
    s.set_pi_addresses({"192.168.1.112"})
    await s.handle_request(req(host="192.168.1.112:7500"))
    s.set_pi_addresses({"192.168.1.112"})
    assert flag_of(s) == "none"


async def test_primary_address_prefers_primary_hint_else_first_ipv4(tmp_path):
    s = make_state(tmp_path)
    assert s.snapshot()["primary_address"] is None
    s.set_pi_addresses({"fe80::1", "192.168.1.112", "10.0.0.1"}, primary="192.168.1.112")
    assert s.snapshot()["primary_address"] == "192.168.1.112"
    s.set_pi_addresses({"fe80::1", "192.168.1.112", "10.0.0.1"}, primary="172.16.0.1")  # not an address
    assert s.snapshot()["primary_address"] == "10.0.0.1"
    s.set_pi_addresses({"fe80::1"})
    assert s.snapshot()["primary_address"] == "fe80::1"


async def test_ip_literal_in_known_devices(tmp_path):
    s = AppState(tmp_path, Options(["10.0.0.9"], True), KEYS, Namer(lookup=lambda ip: None))
    entry = await s.handle_request(req(ip="10.0.0.9"))
    assert entry.known and entry.device == "10.0.0.9"
    assert s.snapshot()["devices"][0]["device"] == "10.0.0.9"


async def test_mark_known_makes_new_requests_known(tmp_path):
    s = make_state(tmp_path)
    assert not (await s.handle_request(req(ip="192.168.1.66"))).known
    assert s.mark_known("stranger.lan") == "ok"
    assert s.is_known("stranger.lan", "192.168.1.66")
    assert (await s.handle_request(req(ip="192.168.1.66"))).known


async def test_mark_known_updates_past_rows_but_not_log(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req(ip="192.168.1.66"))
    assert s.snapshot()["requests"][0]["known"] is False
    s.mark_known("stranger.lan")
    assert s.snapshot()["requests"][0]["known"] is True
    assert s.log.recent()[0].known is False  # stored value is unchanged


async def test_mark_known_creates_record_from_newest_success(tmp_path):
    s = make_state(tmp_path)
    old = TangRequest(T, "192.168.1.66", "192.168.1.80:7500", "rec", 200)
    new = TangRequest(T.replace(hour=18), "192.168.1.66", "192.168.1.87:7500", "adv", 200)
    err = TangRequest(T.replace(hour=19), "192.168.1.66", "192.168.1.90:7500", "rec", 404)
    for r in (old, new, err):
        await s.handle_request(r)
    assert s.snapshot()["devices"] == []
    assert s.mark_known("stranger.lan") == "ok"
    rec = s.store.get("stranger.lan")
    assert rec.last_ok_address == "192.168.1.87" and rec.last_ok_at == new.at


async def test_mark_known_without_success_creates_no_record(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req(ip="192.168.1.66", status=404))
    assert s.mark_known("stranger.lan") == "ok"
    assert s.store.all() == []


async def test_mark_known_not_found_and_already_known(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req(ip="192.168.1.66"))
    await s.handle_request(req())
    assert s.mark_known("nope.lan") == "not_found"
    assert s.mark_known("server.lan") == "already_known"  # via the option
    assert s.mark_known("stranger.lan") == "ok"
    assert s.mark_known("stranger.lan") == "already_known"  # via the list


async def test_forget_removes_from_list_and_record(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req(ip="192.168.1.66"))
    s.mark_known("stranger.lan")
    assert s.store.get("stranger.lan") is not None
    assert s.forget("stranger.lan") == {"forgot": True, "still_known_via_options": False}
    assert s.store.get("stranger.lan") is None
    assert not s.is_known("stranger.lan", "192.168.1.66")


async def test_forget_list_only_entry(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req(ip="192.168.1.66", status=404))
    s.mark_known("stranger.lan")
    assert s.forget("stranger.lan")["forgot"] is True


async def test_snapshot_known_devices(tmp_path):
    s = make_state(tmp_path)
    await s.handle_request(req(ip="192.168.1.66", status=404))
    s.mark_known("stranger.lan")
    assert s.snapshot()["known_devices"] == [
        {"device": "stranger.lan", "source": "dashboard"},
        {"device": "server.lan", "source": "options"}]
    # option entries already in the dashboard list are not duplicated
    s.known.add("server.lan")
    assert [k["device"] for k in s.snapshot()["known_devices"]] == ["stranger.lan", "server.lan"]
    assert s.snapshot()["known_devices"][1]["source"] == "dashboard"


async def test_ip_option_with_resolved_name_is_known_everywhere(tmp_path):
    names = {"10.0.0.9": "box.lan"}
    s = AppState(tmp_path, Options(["10.0.0.9"], True), KEYS, Namer(lookup=names.get))
    entry = await s.handle_request(req(ip="10.0.0.9"))
    assert entry.known
    assert s.snapshot()["requests"][0]["known"] is True
    assert s.mark_known("box.lan") == "already_known"


async def test_dashboard_ip_id_ignored_once_name_resolves(tmp_path):
    names = {}
    s = AppState(tmp_path, Options([], True), KEYS, Namer(lookup=lambda ip: names.get(ip), ttl=timedelta(0)))
    await s.handle_request(req(ip="10.0.0.7"))
    assert s.mark_known("10.0.0.7") == "ok"
    names["10.0.0.7"] = "other.lan"
    entry = await s.handle_request(req(ip="10.0.0.7"))
    assert not entry.known
    assert s.snapshot()["requests"][0]["known"] is False


async def test_option_case_variant_not_duplicated_in_known_devices(tmp_path):
    s = AppState(tmp_path, Options(["Server.LAN", "10.0.0.5"], True), KEYS, Namer(lookup=NAMES.get))
    await s.handle_request(req())
    assert [k["device"] for k in s.snapshot()["known_devices"]] == ["server.lan", "10.0.0.5"]
    s.known.add("SERVER.lan")
    assert [k["device"] for k in s.snapshot()["known_devices"]] == ["server.lan", "10.0.0.5"]


async def test_mark_known_ok_when_only_some_rows_are_known(tmp_path):
    names = {"10.0.0.9": "box.lan", "10.0.0.20": "box.lan"}
    s = AppState(tmp_path, Options(["10.0.0.9"], True), KEYS, Namer(lookup=names.get))
    await s.handle_request(req(ip="10.0.0.9"))
    await s.handle_request(req(ip="10.0.0.20"))
    assert [r["known"] for r in s.snapshot()["requests"]] == [False, True]
    assert s.mark_known("box.lan") == "ok"
    assert all(r["known"] for r in s.snapshot()["requests"])
    assert s.mark_known("box.lan") == "already_known"


def test_load_options_ignores_blank_entries(tmp_path):
    p = tmp_path / "o.json"
    p.write_text('{"known_devices": ["x", "", "  "]}')
    assert load_options(p).known_devices == ["x"]


def test_options_from_dict_defaults_and_blank_dropping():
    assert options_from_dict({}) == Options([], False)
    assert options_from_dict("nope") == Options([], False)
    assert options_from_dict({"known_devices": "x"}) == Options([], False)
    assert options_from_dict({"known_devices": ["a", " ", ""], "address_reserved": True}) == Options(["a"], True)


async def test_set_address_reserved_results(tmp_path):
    s = make_state(tmp_path, reserved=False)
    assert await s.set_address_reserved(True) == "unavailable"

    async def no(v):
        return False

    s.on_set_address_reserved = no
    assert await s.set_address_reserved(True) == "failed"
    assert s.snapshot()["address_reserved"] is False

    async def yes(v):
        return True

    s.on_set_address_reserved = yes
    assert await s.set_address_reserved(True) == "ok"
    assert s.snapshot()["address_reserved"] is True
    assert s.options.known_devices == ["server.lan"]


async def test_update_options_changes_known_status_immediately(tmp_path):
    s = make_state(tmp_path)
    assert not (await s.handle_request(req(ip="192.168.1.66"))).known
    s.update_options(Options(["server.lan", "stranger.lan"], True))
    assert (await s.handle_request(req(ip="192.168.1.66"))).known
