"""Application state tying keys, request log, device store and address checks together."""
import ipaddress
from dataclasses import replace
from pathlib import Path
from typing import Literal

from . import commands
from .address_check import (address_ok, apply_check, apply_fixed, apply_success,
                            success_address)
from .devices import DeviceStore
from .keys import KeyInfo
from .naming import Namer, is_known
from .options import Options
from .records import LoggedRequest, RequestLog, TangRequest


class AppState:
    def __init__(self, data_dir: Path, options: Options, keys: list[KeyInfo], namer: Namer,
                 port: int = 7500):
        self.options = options
        self.keys = keys
        self.namer = namer
        self.port = port
        self.tang_running = False
        self.pi_addresses: set[str] | None = None
        self.log = RequestLog(data_dir / "requests.json")
        self.store = DeviceStore(data_dir / "devices.json")

    async def handle_request(self, req: TangRequest) -> LoggedRequest:
        name = await self.namer.name_for(req.ip)
        device = name or req.ip
        entry = LoggedRequest(req, device, is_known(name, self.options.known_devices))
        self.log.append(entry)
        addr = success_address(entry)
        if addr is not None:
            self.store.put(apply_success(self.store.get(device), device, addr, req.at,
                                         self.pi_addresses))
        return entry

    def set_pi_addresses(self, addrs: set[str] | None) -> None:
        self.pi_addresses = None if addrs is None else set(addrs)
        for rec in self.store.all():
            new = apply_check(rec, self.pi_addresses)
            if new != rec:
                self.store.put(new)

    def mark_fixed(self, device: str) -> Literal["ok", "not_found", "not_flagged"]:
        rec = self.store.get(device)
        if rec is None:
            return "not_found"
        try:
            self.store.put(apply_fixed(rec))
        except ValueError:
            return "not_flagged"
        return "ok"

    def forget(self, device: str) -> bool:
        return self.store.forget(device)

    def _primary_address(self) -> str | None:
        if not self.pi_addresses:
            return None
        addrs = sorted(self.pi_addresses)
        for a in addrs:
            try:
                if ipaddress.ip_address(a).version == 4:
                    return a
            except ValueError:
                continue
        return addrs[0]

    def _has_signing(self) -> bool:
        return any(k.use == "signing" for k in self.keys)

    def snapshot(self) -> dict:
        verified = bool(commands.COMMANDS_VERIFIED)
        primary = self._primary_address()
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
            "pi_addresses": None if self.pi_addresses is None else sorted(self.pi_addresses),
            "address_reserved": self.options.address_reserved,
            "commands_verified": verified,
            "keys": [{"use": k.use, "s256": k.s256, "s1": k.s1} for k in self.keys],
            "requests": [{"at": e.request.at.isoformat(), "device": e.device, "known": e.known,
                          "ip": e.request.ip, "host": e.request.host, "kind": e.request.kind,
                          "status": e.request.status} for e in self.log.recent()],
            "devices": devices,
            "test_commands": test_commands,
        }
