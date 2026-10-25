"""Persistent request log."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from . import jsonfile


@dataclass(frozen=True)
class TangRequest:
    at: datetime
    ip: str
    host: str | None
    kind: Literal["adv", "rec", "other"]
    status: int | None


@dataclass(frozen=True)
class LoggedRequest:
    request: TangRequest
    device: str
    known: bool


def _to_json(e: LoggedRequest) -> dict:
    r = e.request
    return {"at": r.at.isoformat(), "ip": r.ip, "host": r.host, "kind": r.kind,
            "status": r.status, "device": e.device, "known": e.known}


def _from_json(d: dict) -> LoggedRequest:
    req = TangRequest(at=datetime.fromisoformat(d["at"]), ip=d["ip"], host=d["host"],
                      kind=d["kind"], status=d["status"])
    return LoggedRequest(request=req, device=d["device"], known=d["known"])


class RequestLog:
    def __init__(self, path: Path, limit: int = 500):
        self._path = path
        self._limit = limit
        raw = jsonfile.load(path, [])
        try:
            if not isinstance(raw, list):
                raise TypeError("expected a list")
            self._entries = [_from_json(d) for d in raw][-limit:]  # oldest first
        except (KeyError, TypeError, ValueError):
            self._entries = []
            jsonfile.quarantine(path)

    def append(self, entry: LoggedRequest) -> None:
        self._entries.append(entry)
        del self._entries[:-self._limit]
        jsonfile.save(self._path, [_to_json(e) for e in self._entries])

    def recent(self) -> list[LoggedRequest]:
        return list(reversed(self._entries))
