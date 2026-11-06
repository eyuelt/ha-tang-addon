"""Pure per-device address-check logic (flag states)."""
import ipaddress
from dataclasses import replace
from datetime import datetime

from .devices import DeviceRecord
from .http_parse import host_address
from .records import LoggedRequest


def canonical_ip(value: str | None) -> str | None:
    """Canonical compressed form of an IP literal; None for hostnames or junk."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def success_address(entry: LoggedRequest) -> str | None:
    """The address a successful request used, or None if it must not update a device."""
    r = entry.request
    if r.status != 200 or not entry.known or r.kind not in ("adv", "rec"):
        return None
    return canonical_ip(host_address(r.host))


def points_here(address: str, port: int | None, pi_addresses: set[str], tang_port: int | None) -> bool:
    """True if address:port reaches this Tang. An unknown port (either side) only checks the address."""
    return address in pi_addresses and (port is None or tang_port is None or port == tang_port)


def apply_success(prev: DeviceRecord | None, device: str, address: str, at: datetime,
                  pi_addresses: set[str] | None, port: int | None = None,
                  tang_port: int | None = None) -> DeviceRecord:
    flag = prev.flag if prev else "none"
    if pi_addresses is not None and points_here(address, port, pi_addresses, tang_port):
        flag = "none"
    return DeviceRecord(device, address, at, flag, port)


def apply_check(rec: DeviceRecord, pi_addresses: set[str] | None,
                tang_port: int | None = None) -> DeviceRecord:
    if mismatch(rec, pi_addresses, tang_port):
        return replace(rec, flag="flagged")
    return rec


def mismatch(rec: DeviceRecord, pi_addresses: set[str] | None, tang_port: int | None = None) -> bool | None:
    """True if a not-yet-flagged device points at an address or port this Tang lacks; None if unknown."""
    if pi_addresses is None:
        return None
    return rec.flag == "none" and not points_here(rec.last_ok_address, rec.last_ok_port, pi_addresses,
                                                  tang_port)


def apply_fixed(rec: DeviceRecord) -> DeviceRecord:
    if rec.flag != "flagged":
        raise ValueError(f"device {rec.device!r} is not flagged")
    return replace(rec, flag="fixed_untested")


def address_ok(rec: DeviceRecord, pi_addresses: set[str] | None) -> bool | None:
    if pi_addresses is None:
        return None
    # The flag is the debounced signal: a mismatch only counts once AppState has flagged it.
    return rec.flag == "none"
