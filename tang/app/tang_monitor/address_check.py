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


def apply_success(prev: DeviceRecord | None, device: str, address: str, at: datetime,
                  pi_addresses: set[str] | None) -> DeviceRecord:
    flag = prev.flag if prev else "none"
    if pi_addresses is not None and address in pi_addresses:
        flag = "none"
    return DeviceRecord(device, address, at, flag)


def apply_check(rec: DeviceRecord, pi_addresses: set[str] | None) -> DeviceRecord:
    if pi_addresses is None:
        return rec
    if rec.flag == "none" and rec.last_ok_address not in pi_addresses:
        return replace(rec, flag="flagged")
    return rec


def mismatch(rec: DeviceRecord, pi_addresses: set[str] | None) -> bool | None:
    """True if a not-yet-flagged device points at an address the Pi lacks; None if unknown."""
    if pi_addresses is None:
        return None
    return rec.flag == "none" and rec.last_ok_address not in pi_addresses


def apply_fixed(rec: DeviceRecord) -> DeviceRecord:
    if rec.flag != "flagged":
        raise ValueError(f"device {rec.device!r} is not flagged")
    return replace(rec, flag="fixed_untested")


def address_ok(rec: DeviceRecord, pi_addresses: set[str] | None) -> bool | None:
    if pi_addresses is None:
        return None
    # The flag is the debounced signal: a mismatch only counts once AppState has flagged it.
    return rec.flag == "none"
