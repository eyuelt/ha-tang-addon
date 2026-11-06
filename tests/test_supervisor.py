from aiohttp import web

from tang_monitor.supervisor import Supervisor

NET = {"data": {"interfaces": [{"ipv4": {"address": ["192.168.1.87/24"]},
                                "ipv6": {"address": ["fe80::1/64"]}}]}}

OPTS = {"result": "ok", "data": {"known_devices": ["server.lan"], "address_reserved": False}}


async def make(aiohttp_client, status=200, opts_body=OPTS):
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

    async def delete(request):
        seen.append(("DELETE", request.path, request.headers.get("Authorization"), None))
        return web.json_response({}, status=status)
    app.router.add_delete("/core/api/states/{eid}", delete)
    app.router.add_post("/core/api/events/{ev}", post)

    async def get_opts(request):
        seen.append(("GET", request.path, request.headers.get("Authorization"), None))
        return web.json_response(opts_body, status=status)

    async def set_opts(request):
        seen.append(("POST", request.path, request.headers.get("Authorization"), await request.json()))
        return web.json_response({"result": "ok"}, status=status)
    app.router.add_get("/addons/self/options/config", get_opts)
    app.router.add_post("/addons/self/options", set_opts)
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


async def test_empty_address_list_is_unknown(aiohttp_client):
    async def net(request):
        return web.json_response({"data": {"interfaces": [{"ipv4": {"address": []}, "ipv6": None}]}})

    app = web.Application()
    app.router.add_get("/network/info", net)
    client = await aiohttp_client(app)
    sup = Supervisor(client.session, "tok", base=str(client.make_url("")).rstrip("/"))
    assert await sup.pi_addresses() is None
    assert await sup.network_info() == (None, None, None)


async def _sup_with_net(aiohttp_client, ifaces):
    async def net(request):
        return web.json_response({"data": {"interfaces": ifaces}})

    app = web.Application()
    app.router.add_get("/network/info", net)
    client = await aiohttp_client(app)
    return Supervisor(client.session, "tok", base=str(client.make_url("")).rstrip("/"))


async def test_primary_is_first_ipv4_of_primary_interface(aiohttp_client):
    sup = await _sup_with_net(aiohttp_client, [
        {"primary": False, "ipv4": {"address": ["10.0.0.1/24"]}},
        {"primary": True, "mac": "02:00:00:00:00:01", "ipv4": {"address": ["192.168.1.87/24", "192.168.1.90/24"]},
         "ipv6": {"address": ["fd00::5/64"]}}])
    addrs, primary, mac = await sup.network_info()
    assert primary == "192.168.1.87"
    assert mac == "02:00:00:00:00:01"
    assert addrs == {"10.0.0.1", "192.168.1.87", "192.168.1.90", "fd00::5"}


async def test_no_primary_interface_gives_none_primary(aiohttp_client):
    sup = await _sup_with_net(aiohttp_client, [{"primary": False, "ipv4": {"address": ["10.0.0.1/24"]}}])
    assert (await sup.network_info())[1:] == (None, None)


async def test_mac_ignored_when_primary_interface_has_no_ipv4(aiohttp_client):
    sup = await _sup_with_net(aiohttp_client, [{"primary": True, "mac": "02:00:00:00:00:01", "ipv4": None,
                                                "ipv6": {"address": ["fd00::5/64"]}}])
    assert (await sup.network_info())[1:] == (None, None)


async def _sup_with_host(aiohttp_client, body, status=200, token="tok"):
    seen = []

    async def host(request):
        seen.append(request.headers.get("Authorization"))
        return web.json_response(body, status=status)

    app = web.Application()
    app.router.add_get("/host/info", host)
    client = await aiohttp_client(app)
    return Supervisor(client.session, token, base=str(client.make_url("")).rstrip("/")), seen


async def test_host_name_reads_host_info(aiohttp_client):
    sup, seen = await _sup_with_host(aiohttp_client, {"result": "ok", "data": {"hostname": "homeassistant"}})
    assert await sup.host_name() == "homeassistant"
    assert seen == ["Bearer tok"]


async def test_host_name_none_on_error_bad_data_or_no_token(aiohttp_client):
    sup, _ = await _sup_with_host(aiohttp_client, {"result": "error"}, status=500)
    assert await sup.host_name() is None
    sup, _ = await _sup_with_host(aiohttp_client, {"result": "ok", "data": {"hostname": ""}})
    assert await sup.host_name() is None
    sup, _ = await _sup_with_host(aiohttp_client, {"result": "ok", "data": {"hostname": 5}})
    assert await sup.host_name() is None
    sup, seen = await _sup_with_host(aiohttp_client, {"result": "ok", "data": {"hostname": "x"}}, token=None)
    assert await sup.host_name() is None and seen == []


async def test_remove_state_deletes_with_token(aiohttp_client):
    client, seen = await make(aiohttp_client)
    sup = Supervisor(client.session, "tok", base=str(client.make_url("")).rstrip("/"))
    await sup.remove_state("binary_sensor.tang_x_address_ok")
    assert seen == [("DELETE", "/core/api/states/binary_sensor.tang_x_address_ok", "Bearer tok", None)]


async def test_remove_state_noop_without_token_and_never_raises(aiohttp_client):
    client, seen = await make(aiohttp_client)
    await Supervisor(client.session, None, base=str(client.make_url("")).rstrip("/")).remove_state("sensor.x")
    assert seen == []
    await Supervisor(client.session, "tok", base="http://127.0.0.1:1").remove_state("sensor.x")
    client2, _ = await make(aiohttp_client, status=500)
    await Supervisor(client2.session, "tok", base=str(client2.make_url("")).rstrip("/")).remove_state("sensor.x")


def _sup(client, token="tok"):
    return Supervisor(client.session, token, base=str(client.make_url("")).rstrip("/"))


async def test_get_options_returns_data_with_bearer(aiohttp_client):
    client, seen = await make(aiohttp_client)
    assert await _sup(client).get_options() == OPTS["data"]
    assert seen[0] == ("GET", "/addons/self/options/config", "Bearer tok", None)


async def test_get_options_none_on_bad_data_error_or_no_token(aiohttp_client):
    client, _ = await make(aiohttp_client, opts_body={"data": ["x"]})
    assert await _sup(client).get_options() is None
    client, _ = await make(aiohttp_client, status=500)
    assert await _sup(client).get_options() is None
    client, seen = await make(aiohttp_client)
    assert await _sup(client, None).get_options() is None
    assert seen == []


async def test_set_options_posts_full_dict(aiohttp_client):
    client, seen = await make(aiohttp_client)
    new = {"known_devices": ["server.lan"], "address_reserved": True}
    assert await _sup(client).set_options(new) is True
    assert seen[0] == ("POST", "/addons/self/options", "Bearer tok", {"options": new})


async def test_set_options_false_on_errors_or_no_token(aiohttp_client):
    for status in (400, 500):
        client, _ = await make(aiohttp_client, status=status)
        assert await _sup(client).set_options({"a": 1}) is False
    client, seen = await make(aiohttp_client)
    assert await _sup(client, None).set_options({"a": 1}) is False
    assert seen == []
    dead = Supervisor(client.session, "tok", base="http://127.0.0.1:1")
    assert await dead.set_options({"a": 1}) is False
    assert await dead.get_options() is None
