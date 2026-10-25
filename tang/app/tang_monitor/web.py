"""Ingress web app: JSON API plus static dashboard."""
import argparse
from pathlib import Path

from aiohttp import web

STATIC = Path(__file__).parent / "static"
INGRESS_REMOTES = frozenset({"172.30.32.2", "127.0.0.1", "::1"})


def make_app(state, allow_remotes: frozenset[str] = INGRESS_REMOTES) -> web.Application:
    @web.middleware
    async def only_ingress(request: web.Request, handler):
        if request.remote not in allow_remotes:
            raise web.HTTPForbidden()
        return await handler(request)

    async def index(request):
        return web.FileResponse(STATIC / "index.html")

    async def static_file(request):
        path = (STATIC / request.match_info["file"]).resolve()
        if path.parent != STATIC.resolve() or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def api_state(request):
        return web.json_response(state.snapshot())

    async def fixed(request):
        result = state.mark_fixed(request.match_info["device"])
        if result == "not_found":
            raise web.HTTPNotFound()
        if result == "not_flagged":
            raise web.HTTPConflict()
        return web.json_response({"ok": True})

    async def forget(request):
        if not state.forget(request.match_info["device"]):
            raise web.HTTPNotFound()
        await state.notify_forgotten(request.match_info["device"])
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[only_ingress])
    app.add_routes([
        web.get("/", index),
        web.get("/static/{file}", static_file),
        web.get("/api/state", api_state),
        web.post("/api/devices/{device}/fixed", fixed),
        web.post("/api/devices/{device}/forget", forget),
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
    s = AppState(Path(tempfile.mkdtemp()), Options(["server.lan", "laptop.lan"], False),
                 keys, Namer(lookup=names.get))
    now = datetime.now().astimezone()
    sample = [
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
    s.tang_running = True
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
