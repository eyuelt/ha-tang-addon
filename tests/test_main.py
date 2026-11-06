import asyncio
import logging
from datetime import datetime, timezone

import pytest
from aiohttp import web

from tang_monitor import __main__ as main
from tang_monitor.keys import KeyInfo
from tang_monitor.naming import Namer
from tang_monitor.options import Options
from tang_monitor.records import TangRequest
from tang_monitor.state import AppState

T = datetime(2026, 1, 1, 15, 42, tzinfo=timezone.utc)
KEYS = [KeyInfo("a", "signing", "S256A", "S1A"), KeyInfo("b", "exchange", "S256B", "S1B")]


class FakeSupervisor:
    def __init__(self, addrs=None, fail=(), primary=None, options=None, mac=None, hostname=None, port=None):
        self.port = port
        self.options = options
        self.mac = mac
        self.hostname = hostname
        self.set_calls: list[dict] = []
        self.set_ok = True
        self.addrs = addrs
        self.primary = primary
        self.removed: list[str] = []
        self.fail = set(fail)
        self.states: dict[str, tuple[str, dict]] = {}
        self.events: list[tuple[str, dict]] = []

    async def network_info(self):
        if "pi_addresses" in self.fail:
            raise RuntimeError("boom")
        return self.addrs, self.primary, self.mac

    async def host_name(self):
        return self.hostname

    async def get_options(self):
        return self.options

    async def tang_port(self):
        return self.port

    async def set_options(self, options):
        self.set_calls.append(options)
        return self.set_ok

    async def remove_state(self, entity_id):
        self.removed.append(entity_id)

    async def set_state(self, entity_id, state, attributes):
        if "set_state" in self.fail:
            raise RuntimeError("boom")
        self.states[entity_id] = (state, attributes)

    async def fire_event(self, event_type, data):
        if "fire_event" in self.fail:
            raise RuntimeError("boom")
        self.events.append((event_type, data))


def make_state(tmp_path):
    return AppState(tmp_path, Options(["server.lan"], False), KEYS,
                    Namer(lookup={"192.168.1.50": "server.lan"}.get))


def req(status=200):
    return TangRequest(T, "192.168.1.50", "192.168.1.87:7500", "rec", status)


async def test_on_request_logs_fires_event_and_publishes(tmp_path):
    state, sup = make_state(tmp_path), FakeSupervisor()
    await main.make_on_request(state, sup)(req())
    assert len(state.log.recent()) == 1
    assert sup.events == [("tang_request", {"device": "server.lan", "known": True,
                                            "ip": "192.168.1.50", "kind": "rec", "status": 200,
                                            "host": "192.168.1.87:7500"})]
    assert sup.states["sensor.tang_last_unlock"][0] == T.isoformat()
    assert "binary_sensor.tang_server_lan_address_ok" in sup.states


async def test_on_request_survives_supervisor_failures(tmp_path, caplog):
    state, sup = make_state(tmp_path), FakeSupervisor(fail={"fire_event"})
    await main.make_on_request(state, sup)(req())
    assert "sensor.tang_last_unlock" in sup.states  # publish still ran
    sup.fail = {"set_state"}
    with caplog.at_level(logging.ERROR):
        await main.make_on_request(state, sup)(req())
    assert len(state.log.recent()) == 2
    assert "publish" in caplog.text


@pytest.fixture
async def health_url(aiohttp_server):
    status = {"code": 200}

    async def adv(request):
        return web.Response(status=status["code"], text="{}")

    app = web.Application()
    app.add_routes([web.get("/adv", adv)])
    server = await aiohttp_server(app)
    return str(server.make_url("/adv")), status


async def test_refresh_sets_running_addresses_and_publishes(tmp_path, health_url):
    import aiohttp
    url, status = health_url
    state, sup = make_state(tmp_path), FakeSupervisor(addrs={"192.168.1.87", "10.0.0.1"}, primary="192.168.1.87")
    async with aiohttp.ClientSession() as session:
        await main.refresh(state, sup, session, url)
        assert state.tang_running is True
        assert state.pi_addresses == {"192.168.1.87", "10.0.0.1"}
        assert state.primary_address() == "192.168.1.87"
        assert sup.states["binary_sensor.tang_running"][0] == "on"
        status["code"] = 500
        await main.refresh(state, sup, session, url)
        assert state.tang_running is False
        assert sup.states["binary_sensor.tang_running"][0] == "off"


async def test_refresh_unreachable_tang_is_not_running(tmp_path):
    import aiohttp
    state, sup = make_state(tmp_path), FakeSupervisor()
    state.tang_running = True
    async with aiohttp.ClientSession() as session:
        await main.refresh(state, sup, session, "http://127.0.0.1:1/adv")
    assert state.tang_running is False


async def test_refresh_loop_survives_a_failing_iteration(tmp_path, caplog):
    calls = []

    async def flaky(*args):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        if len(calls) == 3:
            raise asyncio.CancelledError

    with caplog.at_level(logging.ERROR):
        with pytest.raises(asyncio.CancelledError):
            await main.refresh_loop(None, None, None, "x", interval=0, refresh_fn=flaky)
    assert len(calls) == 3
    assert "refresh failed" in caplog.text


async def test_refresh_applies_options_from_supervisor(tmp_path):
    import aiohttp
    state = make_state(tmp_path)
    sup = FakeSupervisor(options={"known_devices": ["a.lan", " "], "address_reserved": True})
    async with aiohttp.ClientSession() as session:
        await main.refresh(state, sup, session, "http://127.0.0.1:1/adv")
    assert state.options == Options(["a.lan"], True)


async def test_refresh_keeps_options_when_supervisor_returns_none(tmp_path):
    import aiohttp
    state = make_state(tmp_path)
    async with aiohttp.ClientSession() as session:
        await main.refresh(state, FakeSupervisor(options=None), session, "http://127.0.0.1:1/adv")
    assert state.options == Options(["server.lan"], False)


async def test_set_reserved_callback_sends_full_merged_dict(tmp_path):
    state = make_state(tmp_path)
    sup = FakeSupervisor(options={"known_devices": ["x.lan"], "address_reserved": False, "other": 1})
    cb = main.make_set_address_reserved(sup)
    assert await cb(True) is True
    assert sup.set_calls == [{"known_devices": ["x.lan"], "address_reserved": True, "other": 1}]
    sup.options = None
    assert await cb(True) is False
    assert len(sup.set_calls) == 1


async def test_refresh_records_pi_mac_and_hostname_keeping_last_known(tmp_path):
    import aiohttp
    state = make_state(tmp_path)
    sup = FakeSupervisor(addrs={"192.168.1.87"}, primary="192.168.1.87", mac="02:00:00:00:00:01",
                         hostname="homeassistant")
    async with aiohttp.ClientSession() as session:
        await main.refresh(state, sup, session, "http://127.0.0.1:1/adv")
        assert (state.pi_mac, state.pi_hostname) == ("02:00:00:00:00:01", "homeassistant")
        sup.mac = sup.hostname = None
        await main.refresh(state, sup, session, "http://127.0.0.1:1/adv")
    assert (state.pi_mac, state.pi_hostname) == ("02:00:00:00:00:01", "homeassistant")
    snap = state.snapshot()
    assert (snap["pi_mac"], snap["pi_hostname"]) == ("02:00:00:00:00:01", "homeassistant")


async def test_refresh_uses_the_mapped_host_port_keeping_last_known(tmp_path):
    import aiohttp
    state = make_state(tmp_path)
    assert state.port == 7500  # the default mapping, until Home Assistant says otherwise
    sup = FakeSupervisor(port=7600)
    async with aiohttp.ClientSession() as session:
        await main.refresh(state, sup, session, "http://127.0.0.1:1/adv")
        assert state.port == 7600 and state.port_known
        sup.port = None  # a failed check, or the port turned off
        await main.refresh(state, sup, session, "http://127.0.0.1:1/adv")
    assert state.port == 7600 and state.port_known
