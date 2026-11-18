"""Ingress web app: JSON API plus static dashboard."""
import argparse
import asyncio
import contextlib
import json
import weakref
from pathlib import Path

from aiohttp import web

STATIC = Path(__file__).parent / "static"
# Revalidate on every load (a cheap 304 when unchanged) so an app update shows up without a hard refresh.
NO_CACHE = {"Cache-Control": "no-cache"}
INGRESS_REMOTES = frozenset({"172.30.32.2", "127.0.0.1", "::1"})


def make_app(state, allow_remotes: frozenset[str] = INGRESS_REMOTES) -> web.Application:
    @web.middleware
    async def only_ingress(request: web.Request, handler):
        if request.remote not in allow_remotes:
            raise web.HTTPForbidden()
        return await handler(request)

    @web.middleware
    async def notify_after_change(request: web.Request, handler):
        try:
            return await handler(request)
        finally:
            if request.method != "GET":
                state.changes.notify()

    async def index(request):
        return web.FileResponse(STATIC / "index.html", headers=NO_CACHE)

    async def static_file(request):
        path = (STATIC / request.match_info["file"]).resolve()
        if path.parent != STATIC.resolve() or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers=NO_CACHE)

    async def api_state(request):
        return web.json_response(state.snapshot())

    sockets: weakref.WeakSet = weakref.WeakSet()

    async def api_ws(request):
        """Push the state now and after every change, so the dashboard doesn't have to poll."""
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        sockets.add(ws)

        async def push():
            last = None
            while not ws.closed:
                changed = state.changes.next()
                text = json.dumps(state.snapshot())
                if text != last:
                    await ws.send_str(text)
                    last = text
                await changed.wait()

        pusher = asyncio.create_task(push())
        try:
            async for _ in ws:  # the page sends nothing; this ends when it disconnects
                pass
        finally:
            pusher.cancel()
            with contextlib.suppress(asyncio.CancelledError, ConnectionError, RuntimeError):
                await pusher
        return ws

    async def close_sockets(app):
        for ws in list(sockets):
            await ws.close(code=1001, message=b"server shutting down")

    async def fixed(request):
        result = state.mark_fixed(request.match_info["device"])
        if result == "not_found":
            raise web.HTTPNotFound()
        if result == "not_flagged":
            raise web.HTTPConflict()
        return web.json_response({"ok": True})

    async def forget(request):
        device = request.match_info["device"]
        had_record = state.store.get(device) is not None
        result = state.forget(device)
        if not result["forgot"] and not result["still_known_via_options"]:
            raise web.HTTPNotFound()
        if had_record:
            await state.notify_forgotten(device)
        return web.json_response(result)

    async def known(request):
        result = state.mark_known(request.match_info["device"])
        if result == "not_found":
            raise web.HTTPNotFound()
        if result == "already_known":
            raise web.HTTPConflict()
        return web.json_response({"ok": True})

    async def address_reserved(request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - any unparseable body is a bad request
            raise web.HTTPBadRequest()
        if not isinstance(body, dict) or not isinstance(body.get("reserved"), bool):
            raise web.HTTPBadRequest()
        result = await state.set_address_reserved(body["reserved"])
        if result == "unavailable":
            return web.json_response({"error": "Home Assistant isn't reachable from the app right now."},
                                     status=503)
        if result == "failed":
            return web.json_response({"error": "Home Assistant didn't accept the change."}, status=502)
        return web.json_response({"address_reserved": body["reserved"]})

    app = web.Application(middlewares=[only_ingress, notify_after_change])
    app.on_shutdown.append(close_sockets)
    app.add_routes([
        web.get("/", index),
        web.get("/static/{file}", static_file),
        web.get("/api/state", api_state),
        web.get("/api/ws", api_ws),
        web.post("/api/devices/{device}/fixed", fixed),
        web.post("/api/devices/{device}/forget", forget),
        web.post("/api/devices/{device}/known", known),
        web.post("/api/address-reserved", address_reserved),
    ])
    return app


def _demo_state():
    import asyncio
    import tempfile
    from datetime import datetime, timedelta

    from . import commands
    from .keys import KeyInfo
    from .naming import Namer
    from .options import Options
    from .records import TangRequest
    from .state import AppState

    commands.COMMANDS_VERIFIED = True
    names = {"192.168.1.50": "server.lan", "192.168.1.51": "laptop.lan",
             "192.168.1.66": "<b>stranger</b>.lan"}
    keys = [KeyInfo("a", "signing", "SIGNFP256xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "s1"),
            KeyInfo("b", "exchange", "EXCHFP256xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "s1b")]
    s = AppState(Path(tempfile.mkdtemp()), Options(["server.lan", "laptop.lan", "desktop.lan"], False),
                 keys, Namer(lookup=names.get))
    now = datetime.now().astimezone()
    sample = [(now - timedelta(days=d, hours=2), "192.168.1.50", "192.168.1.112:7500", "rec", 200)
              for d in range(9, 2, -1)]  # a week of daily unlocks, so History has more than fits
    sample += [
        (now - timedelta(hours=26), "192.168.1.51", "192.168.1.87:7500", "rec", 200),
        (now - timedelta(minutes=30), "192.168.1.66", "192.168.1.112:7500", "adv", 200),
        (now - timedelta(minutes=5), "192.168.1.50", "192.168.1.112:7500", "adv", 200),
        (now - timedelta(minutes=5), "192.168.1.50", "192.168.1.112:7500", "rec", 200),
        (now - timedelta(minutes=1), "192.168.1.50", "192.168.1.112:7500", "rec", 404),
    ]

    async def feed():
        for at, ip, host, kind, status in sample:
            await s.handle_request(TangRequest(at, ip, host, kind, status))
    asyncio.run(feed())
    async def demo_reserve(value: bool) -> bool:
        return True
    s.on_set_address_reserved = demo_reserve
    s.tang_running = True
    s.pi_mac, s.pi_hostname = "02:00:00:00:00:01", "homeassistant"
    for _ in range(3):  # the flag needs 3 consecutive mismatching checks
        s.set_pi_addresses({"192.168.1.112"}, primary="192.168.1.112")
    return s


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    if not args.demo:
        raise SystemExit("only --demo is supported here; the add-on entrypoint runs the app")
    web.run_app(make_app(_demo_state()), host="127.0.0.1", port=args.port)
