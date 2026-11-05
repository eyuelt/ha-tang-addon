"""Application state tying keys, request log, device store and address checks together."""
import ipaddress
from dataclasses import replace
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Literal

from . import commands
from .address_check import (canonical_ip, address_ok, apply_check, apply_fixed, apply_success,
                            mismatch, success_address)
from .devices import DeviceStore
from .keys import KeyInfo
from .known import KnownDevices
from .naming import Namer, is_known_request, normalize_id
from .options import Options
from .records import LoggedRequest, RequestLog, TangRequest


MISMATCH_CHECKS = 3  # consecutive mismatching checks before a device is flagged


class AppState:
    def __init__(self, data_dir: Path, options: Options, keys: list[KeyInfo], namer: Namer,
                 port: int = 7500):
        self.options = options
        self.keys = keys
        self.namer = namer
        self.port = port
        self.tang_running = False
        self.pi_addresses: set[str] | None = None
        self._primary_hint: str | None = None
        self.on_forget: Callable[[str], Awaitable[None]] | None = None
        self._mismatches: dict[str, int] = {}  # in memory only; a restart resets the debounce
        self.log = RequestLog(data_dir / "requests.json")
        self.store = DeviceStore(data_dir / "devices.json")
        self.known = KnownDevices(data_dir / "known.json")

    @staticmethod
    def _name_of(entry: LoggedRequest) -> str | None:
        return entry.device if entry.device != entry.request.ip else None

    def is_known(self, name: str | None, ip: str) -> bool:
        return is_known_request(name, ip, self.options.known_devices) or self.known.matches(name, ip)

    async def handle_request(self, req: TangRequest) -> LoggedRequest:
        name = await self.namer.name_for(req.ip)
        device = name or req.ip
        entry = LoggedRequest(req, device, self.is_known(name, req.ip))
        self.log.append(entry)
        addr = success_address(entry)
        if addr is not None:
            if self.pi_addresses is not None and addr in self.pi_addresses:
                self._mismatches.pop(device, None)
            self.store.put(apply_success(self.store.get(device), device, addr, req.at,
                                         self.pi_addresses))
        return entry

    def set_pi_addresses(self, addrs: set[str] | None, primary: str | None = None) -> None:
        self.pi_addresses = None if addrs is None else set(addrs)
        self._primary_hint = primary if addrs is not None else None
        for rec in self.store.all():
            m = mismatch(rec, self.pi_addresses)
            if m is None:
                continue
            if not m:
                self._mismatches.pop(rec.device, None)
                continue
            n = self._mismatches.get(rec.device, 0) + 1
            self._mismatches[rec.device] = n
            if n >= MISMATCH_CHECKS:
                self.store.put(apply_check(rec, self.pi_addresses))

    def mark_fixed(self, device: str) -> Literal["ok", "not_found", "not_flagged"]:
        rec = self.store.get(device)
        if rec is None:
            return "not_found"
        try:
            self.store.put(apply_fixed(rec))
        except ValueError:
            return "not_flagged"
        return "ok"

    def mark_known(self, device: str) -> Literal["ok", "not_found", "already_known"]:
        entries = [e for e in self.log.recent() if e.device == device]  # newest first
        if not entries:
            return "not_found"
        if all(self.is_known(self._name_of(e), e.request.ip) for e in entries):
            return "already_known"
        self.known.add(device)
        for e in entries:
            as_known = replace(e, known=True)
            addr = success_address(as_known)
            if addr is not None:
                self.store.put(apply_success(self.store.get(device), device, addr, e.request.at,
                                             self.pi_addresses))
                break
        return "ok"

    def forget(self, device: str) -> dict:
        self._mismatches.pop(device, None)
        removed_record = self.store.forget(device)
        removed_known = self.known.remove(device)
        return {"forgot": removed_record or removed_known,
                "still_known_via_options": self._known_via_options(device)}

    def _known_via_options(self, device: str) -> bool:
        is_ip = canonical_ip(device) is not None
        return is_known_request(None if is_ip else device, device if is_ip else "",
                                self.options.known_devices)

    async def notify_forgotten(self, device: str) -> None:
        if self.on_forget is not None:
            await self.on_forget(device)

    def primary_address(self) -> str | None:
        if not self.pi_addresses:
            return None
        if self._primary_hint in self.pi_addresses:
            return self._primary_hint
        addrs = sorted(self.pi_addresses)
        for a in addrs:
            try:
                if ipaddress.ip_address(a).version == 4:
                    return a
            except ValueError:
                continue
        return addrs[0]

    def _known_devices(self) -> list[dict]:
        ids = self.known.ids()
        out = [{"device": d, "source": "dashboard"} for d in ids]
        listed = set(ids)
        for d in map(normalize_id, self.options.known_devices):
            if d not in listed:
                listed.add(d)
                out.append({"device": d, "source": "options"})
        return out

    def _has_signing(self) -> bool:
        return any(k.use == "signing" for k in self.keys)

    def snapshot(self) -> dict:
        verified = commands.commands_verified()
        primary = self.primary_address()
        can_cmd = verified and primary is not None and self._has_signing()
        exchange = [k for k in self.keys if k.use == "exchange"]
        devices = []
        for r in self.store.all():
            cmds = None
            if can_cmd and r.flag != "none":
                cmds = commands.device_commands(r.last_ok_address, primary, self.port, self.keys)
            devices.append({
                "device": r.device, "last_ok_address": r.last_ok_address,
                "last_ok_at": r.last_ok_at.isoformat(), "flag": r.flag,
                "address_ok": address_ok(r, self.pi_addresses), "commands": cmds})
        test_commands = None
        if verified:
            test_commands = {
                "find": commands.find_steps(None),
                "test": commands.test_command(),
                "one_step_test": commands.one_step_script("test", exchange, None)}
        return {
            "running": self.tang_running,
            "primary_address": primary,
            "pi_addresses": None if self.pi_addresses is None else sorted(self.pi_addresses),
            "address_reserved": self.options.address_reserved,
            "commands_verified": verified,
            "keys": [{"use": k.use, "s256": k.s256, "s1": k.s1} for k in self.keys],
            "requests": [{"at": e.request.at.isoformat(), "device": e.device, "known": self.is_known(self._name_of(e), e.request.ip),
                          "ip": e.request.ip, "host": e.request.host, "kind": e.request.kind,
                          "status": e.request.status} for e in self.log.recent()],
            "devices": devices,
            "known_devices": self._known_devices(),
            "test_commands": test_commands,
        }
