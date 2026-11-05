"""Dashboard-managed list of known device ids."""
from pathlib import Path

from . import jsonfile
from .naming import normalize_id


class KnownDevices:
    """Device ids (a resolved name, else an IP), stored in normalized form."""

    def __init__(self, path: Path):
        self._path = path
        self._ids: list[str] = []
        raw = jsonfile.load(path, [])
        if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
            self._ids = list(dict.fromkeys(normalize_id(x) for x in raw))
        else:
            jsonfile.quarantine(path)

    def ids(self) -> list[str]:
        return list(self._ids)

    def add(self, device: str) -> bool:
        device = normalize_id(device)
        if device in self._ids:
            return False
        self._ids.append(device)
        jsonfile.save(self._path, self._ids)
        return True

    def remove(self, device: str) -> bool:
        device = normalize_id(device)
        if device not in self._ids:
            return False
        self._ids.remove(device)
        jsonfile.save(self._path, self._ids)
        return True

    def matches(self, name: str | None, ip: str) -> bool:
        """Match the request's device id: the resolved name if any, else the IP."""
        return normalize_id(name or ip) in self._ids
