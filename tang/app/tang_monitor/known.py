"""Dashboard-managed list of known device ids."""
from pathlib import Path

from . import jsonfile
from .address_check import canonical_ip
from .naming import is_known


class KnownDevices:
    def __init__(self, path: Path):
        self._path = path
        self._ids: list[str] = []
        raw = jsonfile.load(path, [])
        if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
            self._ids = list(dict.fromkeys(raw))
        else:
            jsonfile.quarantine(path)

    def ids(self) -> list[str]:
        return list(self._ids)

    def add(self, device: str) -> bool:
        if device in self._ids:
            return False
        self._ids.append(device)
        jsonfile.save(self._path, self._ids)
        return True

    def remove(self, device: str) -> bool:
        if device not in self._ids:
            return False
        self._ids.remove(device)
        jsonfile.save(self._path, self._ids)
        return True

    def matches(self, name: str | None, ip: str) -> bool:
        if is_known(name, self._ids):
            return True
        cip = canonical_ip(ip)
        return cip is not None and cip in {canonical_ip(i) for i in self._ids}
