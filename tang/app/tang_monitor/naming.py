"""Reverse-DNS device naming with a TTL cache."""
import asyncio
import socket
from collections.abc import Callable
from datetime import datetime, timedelta


def _normalize(name: str) -> str:
    return name.lower().rstrip(".")


def reverse_lookup(ip: str) -> str | None:
    try:
        return _normalize(socket.gethostbyaddr(ip)[0])
    except OSError:
        return None


class Namer:
    def __init__(self, lookup: Callable[[str], str | None] = reverse_lookup,
                 ttl: timedelta = timedelta(minutes=10), timeout: float = 2.0,
                 now: Callable[[], datetime] = datetime.now):
        self._lookup = lookup
        self._ttl = ttl
        self._timeout = timeout
        self._now = now
        self._cache: dict[str, tuple[datetime, str | None]] = {}

    async def name_for(self, ip: str) -> str | None:
        hit = self._cache.get(ip)
        if hit is not None and self._now() - hit[0] < self._ttl:
            return hit[1]
        try:
            raw = await asyncio.wait_for(asyncio.to_thread(self._lookup, ip), self._timeout)
        except Exception:  # includes TimeoutError
            raw = None
        name = _normalize(raw) if raw else None
        self._cache[ip] = (self._now(), name)
        return name


def is_known(name: str | None, known: list[str]) -> bool:
    if not name:
        return False
    return _normalize(name) in {_normalize(k) for k in known}
