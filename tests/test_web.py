from datetime import datetime, timezone
from pathlib import Path

from tang_monitor.keys import KeyInfo
from tang_monitor.naming import Namer
from tang_monitor.options import Options
from tang_monitor.records import TangRequest
from tang_monitor.state import AppState
from tang_monitor.web import make_app

T = datetime(2026, 1, 1, 15, 42, tzinfo=timezone.utc)
KEYS = [KeyInfo("a", "signing", "S256A", "S1A"), KeyInfo("b", "exchange", "S256B", "S1B")]
LOCAL = frozenset({"127.0.0.1"})


async def make_client(aiohttp_client, tmp_path, allow=LOCAL):
    s = AppState(tmp_path, Options(["d.lan"], True), KEYS, Namer(lookup=lambda ip: "d.lan"))
    await s.handle_request(TangRequest(T, "1.1.1.1", "192.168.1.87:7500", "rec", 200))
    for _ in range(3):  # the flag needs 3 consecutive mismatching checks
        s.set_pi_addresses({"192.168.1.112"})
    return s, await aiohttp_client(make_app(s, allow))


async def test_rejects_non_ingress_remote_403(aiohttp_client, tmp_path):
    _, c = await make_client(aiohttp_client, tmp_path, frozenset({"172.30.32.2"}))
    assert (await c.get("/api/state")).status == 403
    assert (await c.get("/")).status == 403


async def test_state_json_shape(aiohttp_client, tmp_path):
    _, c = await make_client(aiohttp_client, tmp_path)
    r = await c.get("/api/state")
    assert r.status == 200
    j = await r.json()
    assert set(j) == {"running", "primary_address", "pi_mac", "pi_hostname", "pi_addresses", "address_reserved",
                      "commands_verified",
                      "keys", "requests", "devices", "known_devices", "test_commands"}
    assert set(j["keys"][0]) == {"use", "s256", "s1"}
    assert set(j["requests"][0]) == {"at", "device", "known", "ip", "host", "kind", "status"}
    assert set(j["devices"][0]) == {"device", "last_ip", "last_ok_address", "last_ok_at", "flag",
                                    "address_ok", "commands"}


async def test_fixed_404_409_200(aiohttp_client, tmp_path):
    _, c = await make_client(aiohttp_client, tmp_path)
    assert (await c.post("/api/devices/nope/fixed")).status == 404
    assert (await c.post("/api/devices/d.lan/fixed")).status == 200
    assert (await c.post("/api/devices/d.lan/fixed")).status == 409


async def test_forget_200_404(aiohttp_client, tmp_path):
    _, c = await make_client(aiohttp_client, tmp_path)
    r = await c.post("/api/devices/d.lan/forget")
    assert r.status == 200
    assert await r.json() == {"forgot": True, "still_known_via_options": True}
    # nothing left to remove, but the option still lists it: 200 so the UI can show the note
    r = await c.post("/api/devices/d.lan/forget")
    assert r.status == 200
    assert await r.json() == {"forgot": False, "still_known_via_options": True}
    assert (await c.post("/api/devices/nope.lan/forget")).status == 404


async def test_known_200_404_409(aiohttp_client, tmp_path):
    s, c = await make_client(aiohttp_client, tmp_path)
    s.namer._cache["1.1.1.2"] = (s.namer._now(), "other.lan")
    await s.handle_request(TangRequest(T, "1.1.1.2", "192.168.1.87:7500", "rec", 200))
    assert (await c.post("/api/devices/nope/known")).status == 404
    assert (await c.post("/api/devices/d.lan/known")).status == 409  # via the option
    assert (await c.post("/api/devices/other.lan/known")).status == 200
    assert s.known.ids() == ["other.lan"]
    assert (await c.post("/api/devices/other.lan/known")).status == 409  # via the list


async def test_forget_list_only_device_skips_on_forget(aiohttp_client, tmp_path):
    s, c = await make_client(aiohttp_client, tmp_path)
    forgotten = []

    async def on_forget(device):
        forgotten.append(device)
    s.on_forget = on_forget
    s.known.add("x.lan")
    r = await c.post("/api/devices/x.lan/forget")
    assert r.status == 200 and await r.json() == {"forgot": True, "still_known_via_options": False}
    assert forgotten == []


async def test_forget_calls_on_forget_only_on_success(aiohttp_client, tmp_path):
    s, c = await make_client(aiohttp_client, tmp_path)
    forgotten = []

    async def on_forget(device):
        forgotten.append(device)
    s.on_forget = on_forget
    assert (await c.post("/api/devices/d.lan/forget")).status == 200
    assert (await c.post("/api/devices/d.lan/forget")).status == 200  # option-only: no removal
    assert (await c.post("/api/devices/nope.lan/forget")).status == 404
    assert forgotten == ["d.lan"]


def test_default_ingress_remotes_pinned():
    from tang_monitor.web import INGRESS_REMOTES
    assert INGRESS_REMOTES == {"172.30.32.2", "127.0.0.1", "::1"}


async def test_index_and_static(aiohttp_client, tmp_path):
    _, c = await make_client(aiohttp_client, tmp_path)
    r = await c.get("/")
    assert r.status == 200 and "<html" in await r.text()
    assert (await c.get("/static/app.js")).status == 200
    assert (await c.get("/static/../web.py")).status == 404


def test_index_uses_relative_api_url():
    js = (Path(__file__).parent.parent / "tang/app/tang_monitor/static/app.js").read_text()
    assert 'fetch("api/state"' in js


async def test_address_reserved_route(aiohttp_client, tmp_path):
    s, c = await make_client(aiohttp_client, tmp_path)
    r = await c.post("/api/address-reserved", json={"reserved": True})
    assert r.status == 503
    assert (await r.json()) == {"error": "Home Assistant isn't reachable from the app right now."}

    async def no(v):
        return False
    s.on_set_address_reserved = no
    r = await c.post("/api/address-reserved", json={"reserved": True})
    assert r.status == 502
    assert (await r.json()) == {"error": "Home Assistant didn't accept the change."}

    async def yes(v):
        return True
    s.on_set_address_reserved = yes
    r = await c.post("/api/address-reserved", json={"reserved": False})
    assert r.status == 200 and (await r.json()) == {"address_reserved": False}

    for body in ({"reserved": "yes"}, {"x": 1}, [True], 5):
        assert (await c.post("/api/address-reserved", json=body)).status == 400
    assert (await c.post("/api/address-reserved", data="not json")).status == 400
