"""Pure builder of Home Assistant entity states."""
import re

from .address_check import address_ok
from .devices import DeviceRecord
from .records import LoggedRequest


def device_slug(device: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", device.lower()).strip("_")


def event_data(entry: LoggedRequest) -> dict:
    r = entry.request
    return {"device": entry.device, "known": entry.known, "ip": r.ip, "kind": r.kind,
            "status": r.status, "host": r.host}


def _newest(entries: list[LoggedRequest]) -> LoggedRequest | None:
    return max(entries, key=lambda e: e.request.at, default=None)


def build_entities(log: list[LoggedRequest], devices: list[DeviceRecord],
                   pi_addresses: set[str] | None, tang_running: bool) -> dict[str, tuple[str, dict]]:
    ents: dict[str, tuple[str, dict]] = {
        "binary_sensor.tang_running": ("on" if tang_running else "off",
                                       {"friendly_name": "Tang running"}),
    }
    unlock = _newest([e for e in log if e.request.kind == "rec" and e.request.status == 200])
    if unlock:
        ents["sensor.tang_last_unlock"] = (unlock.request.at.isoformat(), {
            "friendly_name": "Tang last unlock", "device": unlock.device,
            "ip": unlock.request.ip, "device_class": "timestamp"})
    else:
        ents["sensor.tang_last_unlock"] = ("unknown", {
            "friendly_name": "Tang last unlock", "device_class": "timestamp"})
    unk = _newest([e for e in log if not e.known])
    if unk:
        ents["sensor.tang_last_unknown_request"] = (unk.request.at.isoformat(), {
            "friendly_name": "Tang last unknown request", "ip": unk.request.ip,
            "kind": unk.request.kind, "device_class": "timestamp"})
    else:
        ents["sensor.tang_last_unknown_request"] = ("unknown", {
            "friendly_name": "Tang last unknown request", "device_class": "timestamp"})
    for d in devices:
        ok = address_ok(d, pi_addresses)
        state = "unavailable" if ok is None else ("on" if ok else "off")
        ents[f"binary_sensor.tang_{device_slug(d.device)}_address_ok"] = (state, {
            "friendly_name": f"Tang {d.device} address OK", "device": d.device,
            "last_address": d.last_ok_address,
            "pi_addresses": sorted(pi_addresses) if pi_addresses is not None else [],
            "flag": d.flag})
    return ents
