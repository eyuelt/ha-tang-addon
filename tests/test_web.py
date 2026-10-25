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
    assert set(j) == {"running", "pi_addresses", "address_reserved", "commands_verified",
                      "keys", "requests", "devices", "test_commands"}
    assert set(j["keys"][0]) == {"use", "s256", "s1"}
    assert set(j["requests"][0]) == {"at", "device", "known", "ip", "host", "kind", "status"}
    assert set(j["devices"][0]) == {"device", "last_ok_address", "last_ok_at", "flag",
                                    "address_ok", "commands"}


async def test_fixed_404_409_200(aiohttp_client, tmp_path):
    _, c = await make_client(aiohttp_client, tmp_path)
    assert (await c.post("/api/devices/nope/fixed")).status == 404
    assert (await c.post("/api/devices/d.lan/fixed")).status == 200
    assert (await c.post("/api/devices/d.lan/fixed")).status == 409


async def test_forget_200_404(aiohttp_client, tmp_path):
    _, c = await make_client(aiohttp_client, tmp_path)
    assert (await c.post("/api/devices/d.lan/forget")).status == 200
    assert (await c.post("/api/devices/d.lan/forget")).status == 404


async def test_index_and_static(aiohttp_client, tmp_path):
    _, c = await make_client(aiohttp_client, tmp_path)
    r = await c.get("/")
    assert r.status == 200 and "<html" in await r.text()
    assert (await c.get("/static/app.js")).status == 200
    assert (await c.get("/static/../web.py")).status == 404


def test_index_uses_relative_api_url():
    js = (Path(__file__).parent.parent / "tang/app/tang_monitor/static/app.js").read_text()
    assert 'fetch("api/state"' in js
