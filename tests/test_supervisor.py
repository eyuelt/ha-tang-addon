from aiohttp import web

from tang_monitor.supervisor import Supervisor

NET = {"data": {"interfaces": [{"ipv4": {"address": ["192.168.1.87/24"]},
                                "ipv6": {"address": ["fe80::1/64"]}}]}}


async def make(aiohttp_client, status=200):
    seen = []

    async def net(request):
        seen.append(("GET", request.path, request.headers.get("Authorization"), None))
        return web.json_response(NET, status=status)

    async def post(request):
        seen.append(("POST", request.path, request.headers.get("Authorization"), await request.json()))
        return web.json_response({}, status=status)

    app = web.Application()
    app.router.add_get("/network/info", net)
    app.router.add_post("/core/api/states/{eid}", post)
    app.router.add_post("/core/api/events/{ev}", post)
    client = await aiohttp_client(app)
    return client, seen


async def test_parses_ipv4_ipv6_strips_prefix(aiohttp_client):
    client, seen = await make(aiohttp_client)
    sup = Supervisor(client.session, "tok", base=str(client.make_url("")).rstrip("/"))
    assert await sup.pi_addresses() == {"192.168.1.87", "fe80::1"}
    assert seen[0][2] == "Bearer tok"


async def test_403_returns_none(aiohttp_client):
    client, _ = await make(aiohttp_client, status=403)
    sup = Supervisor(client.session, "tok", base=str(client.make_url("")).rstrip("/"))
    assert await sup.pi_addresses() is None


async def test_unreachable_returns_none_and_writes_do_not_raise(aiohttp_client):
    client, _ = await make(aiohttp_client)
    sup = Supervisor(client.session, "tok", base="http://127.0.0.1:1")
    assert await sup.pi_addresses() is None
    await sup.set_state("sensor.x", "1", {})
    await sup.fire_event("e", {})


async def test_no_token_returns_none_and_writes_are_noops(aiohttp_client):
    client, seen = await make(aiohttp_client)
    sup = Supervisor(client.session, None, base=str(client.make_url("")).rstrip("/"))
    assert await sup.pi_addresses() is None
    await sup.set_state("sensor.x", "1", {})
    await sup.fire_event("e", {})
    assert seen == []


async def test_set_state_posts_bearer_token(aiohttp_client):
    client, seen = await make(aiohttp_client)
    sup = Supervisor(client.session, "tok", base=str(client.make_url("")).rstrip("/"))
    await sup.set_state("sensor.x", "on", {"a": 1})
    await sup.fire_event("tang_x", {"b": 2})
    assert seen[0] == ("POST", "/core/api/states/sensor.x", "Bearer tok", {"state": "on", "attributes": {"a": 1}})
    assert seen[1] == ("POST", "/core/api/events/tang_x", "Bearer tok", {"b": 2})


async def test_supervisor_normalizes_and_ignores_non_ip(aiohttp_client):
    body = {"data": {"interfaces": [{"ipv4": {"address": ["not-an-ip/24"]},
                                     "ipv6": {"address": ["FD00:0:0::5/64"]}}]}}

    async def net(request):
        return web.json_response(body)

    app = web.Application()
    app.router.add_get("/network/info", net)
    client = await aiohttp_client(app)
    sup = Supervisor(client.session, "tok", base=str(client.make_url("")).rstrip("/"))
    assert await sup.pi_addresses() == {"fd00::5"}
