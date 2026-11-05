"""Add-on options (from /data/options.json)."""
from dataclasses import dataclass, field
from pathlib import Path

from . import jsonfile


@dataclass(frozen=True)
class Options:
    known_devices: list[str] = field(default_factory=list)
    address_reserved: bool = False


def load_options(path: Path = Path("/data/options.json")) -> Options:
    raw = jsonfile.load(path, {})
    if not isinstance(raw, dict):
        raw = {}
    known = raw.get("known_devices", [])
    if not isinstance(known, list):
        known = []
    return Options([str(k) for k in known if str(k).strip()], bool(raw.get("address_reserved", False)))
