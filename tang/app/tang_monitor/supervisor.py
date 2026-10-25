"""Minimal client for the Home Assistant Supervisor API."""
import logging

import aiohttp

from .address_check import canonical_ip

log = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=10)


class Supervisor:
    def __init__(self, session: aiohttp.ClientSession, token: str | None,
                 base: str = "http://supervisor"):
        self._session = session
        self._token = token
        self._base = base.rstrip("/")
        self._logged: set[str] = set()

    def _fail(self, kind: str, detail: object) -> None:
        if kind not in self._logged:
            self._logged.add(kind)
            log.warning("Supervisor %s failed: %s (further failures not logged)", kind, detail)

    def _ok(self, kind: str) -> None:
        self._logged.discard(kind)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def pi_addresses(self) -> set[str] | None:
        if self._token is None:
            return None
        try:
            async with self._session.get(f"{self._base}/network/info", headers=self._headers,
                                         timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                body = await resp.json()
            out: set[str] = set()
            for iface in body["data"]["interfaces"]:
                for fam in ("ipv4", "ipv6"):
                    for a in (iface.get(fam) or {}).get("address") or []:
                        ip = canonical_ip(a.split("/", 1)[0])
                        if ip is not None:
                            out.add(ip)
        except Exception as e:  # noqa: BLE001 - any failure means "unknown"
            self._fail("network_info", e)
            return None
        self._ok("network_info")
        return out

    async def _post(self, kind: str, path: str, body: dict) -> None:
        if self._token is None:
            return
        try:
            async with self._session.post(f"{self._base}{path}", json=body, headers=self._headers,
                                          timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            self._fail(kind, e)
            return
        self._ok(kind)

    async def set_state(self, entity_id: str, state: str, attributes: dict) -> None:
        await self._post("set_state", f"/core/api/states/{entity_id}",
                         {"state": state, "attributes": attributes})

    async def fire_event(self, event_type: str, data: dict) -> None:
        await self._post("fire_event", f"/core/api/events/{event_type}", data)
