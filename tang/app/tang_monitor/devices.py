"""Persistent per-device last-good-address store."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from . import jsonfile


@dataclass(frozen=True)
class DeviceRecord:
    device: str
    last_ok_address: str
    last_ok_at: datetime
    flag: Literal["none", "flagged", "fixed_untested"] = "none"


class DeviceStore:
    def __init__(self, path: Path):
        self._path = path
        self._devices: dict[str, DeviceRecord] = {}
        raw = jsonfile.load(path, [])
        try:
            for d in raw:
                rec = DeviceRecord(d["device"], d["last_ok_address"],
                                   datetime.fromisoformat(d["last_ok_at"]), d.get("flag", "none"))
                self._devices[rec.device] = rec
        except (KeyError, TypeError, ValueError):
            self._devices = {}

    def _persist(self) -> None:
        jsonfile.save(self._path, [
            {"device": r.device, "last_ok_address": r.last_ok_address,
             "last_ok_at": r.last_ok_at.isoformat(), "flag": r.flag}
            for r in self._devices.values()])

    def get(self, device: str) -> DeviceRecord | None:
        return self._devices.get(device)

    def all(self) -> list[DeviceRecord]:
        return list(self._devices.values())

    def put(self, record: DeviceRecord) -> None:
        self._devices[record.device] = record
        self._persist()

    def forget(self, device: str) -> bool:
        if self._devices.pop(device, None) is None:
            return False
        self._persist()
        return True
