"""Add-on entrypoint: Tang front end, ingress web app and the 60-second refresh loop."""
import asyncio
import logging
import os
import signal
from pathlib import Path

import aiohttp
from aiohttp import web

from .entities import build_entities, device_slug, event_data
from .keys import ensure_keys, load_keys
from .naming import Namer
from .options import load_options, options_from_dict
from .records import TangRequest
from .state import AppState
from .supervisor import TANG_CONTAINER_PORT, Supervisor
from .tang_server import start_tang_server
from .web import make_app

log = logging.getLogger("tang_monitor")

DATA_DIR = Path("/data")
TANG_PORT = TANG_CONTAINER_PORT
WEB_PORT = 8099
INTERVAL = 60.0
_HEALTH_TIMEOUT = aiohttp.ClientTimeout(total=5)


async def publish(state: AppState, sup: Supervisor) -> None:
    ents = build_entities(state.log.recent(), state.store.all(), state.pi_addresses, state.tang_running)
    for entity_id, (value, attrs) in ents.items():
        await sup.set_state(entity_id, value, attrs)


def make_on_request(state: AppState, sup: Supervisor):
    async def on_request(req: TangRequest) -> None:
        entry = await state.handle_request(req)
        try:
            await sup.fire_event("tang_request", event_data(entry))
        except Exception:
            log.exception("firing tang_request event failed")
        try:
            await publish(state, sup)
        except Exception:
            log.exception("publishing entities failed")
    return on_request


def make_set_address_reserved(sup: Supervisor):
    async def set_address_reserved(value: bool) -> bool:
        current = await sup.get_options()
        if current is None:
            return False
        return await sup.set_options({**current, "address_reserved": value})
    return set_address_reserved


async def tang_healthy(session: aiohttp.ClientSession, url: str) -> bool:
    try:
        async with session.get(url, timeout=_HEALTH_TIMEOUT) as resp:
            await resp.read()
            return resp.status == 200
    except Exception as e:  # noqa: BLE001 - any failure means "not running"
        log.debug("health check failed: %r", e)
        return False


async def refresh(state: AppState, sup: Supervisor, session: aiohttp.ClientSession, health_url: str) -> None:
    running = await tang_healthy(session, health_url)
    if running != state.tang_running:
        log.info("Tang is %s", "running" if running else "NOT running")
    state.tang_running = running
    addrs, primary, mac = await sup.network_info()
    state.set_pi_addresses(addrs, primary)
    state.pi_mac = mac or state.pi_mac  # keep the last known value through a failed check
    state.pi_hostname = await sup.host_name() or state.pi_hostname
    state.port = await sup.tang_port() or state.port  # the host port devices use, from the Network settings
    options = await sup.get_options()  # Configuration-tab edits apply here, with no restart
    if options is not None:
        state.update_options(options_from_dict(options))
    await publish(state, sup)


async def refresh_loop(state, sup, session, health_url: str, interval: float = INTERVAL,
                       refresh_fn=refresh) -> None:
    while True:
        try:
            await refresh_fn(state, sup, session, health_url)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("refresh failed")
        await asyncio.sleep(interval)


async def main(data_dir: Path = DATA_DIR) -> None:
    keydir = data_dir / "keys"
    keydir.mkdir(parents=True, exist_ok=True)
    ensure_keys(keydir)
    keys = load_keys(keydir)
    options = load_options(data_dir / "options.json")
    state = AppState(data_dir, options, keys, Namer(), port=TANG_PORT)
    for k in keys:
        log.info("%s key %s", k.use, k.s256)

    async with aiohttp.ClientSession() as session:
        sup = Supervisor(session, os.environ.get("SUPERVISOR_TOKEN"))
        async def on_forget(device: str) -> None:
            await sup.remove_state(f"binary_sensor.tang_{device_slug(device)}_address_ok")
        state.on_forget = on_forget
        state.on_set_address_reserved = make_set_address_reserved(sup)
        tang = await start_tang_server("0.0.0.0", TANG_PORT, keydir, make_on_request(state, sup))
        runner = web.AppRunner(make_app(state), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
        log.info("Tang on port %d, dashboard on port %d", TANG_PORT, WEB_PORT)
        try:
            await refresh_loop(state, sup, session, f"http://127.0.0.1:{TANG_PORT}/adv")
        finally:
            tang.close()
            await tang.wait_closed()
            await runner.cleanup()


async def _run() -> None:
    task = asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        await main()
    except asyncio.CancelledError:
        log.info("stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run())
