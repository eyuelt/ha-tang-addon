from datetime import datetime, timezone

import pytest

from tang_monitor import commands
from tang_monitor.keys import KeyInfo
from tang_monitor.naming import Namer
from tang_monitor.options import Options, load_options
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
    assert s.forget("server.lan") is True
    assert s.forget("server.lan") is False
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
