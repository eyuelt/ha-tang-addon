"""Minimal client for the Home Assistant Supervisor API."""
import logging

import aiohttp

from .address_check import canonical_ip

log = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=10)
TANG_CONTAINER_PORT = 7500  # Tang's port inside the container; config.yaml maps it to a host port


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

    async def network_info(self) -> tuple[set[str] | None, str | None, str | None]:
        """(all of this machine's addresses, first IPv4 of the primary interface, that interface's MAC).

        Each part is None when unknown."""
        if self._token is None:
            return None, None, None
        try:
            async with self._session.get(f"{self._base}/network/info", headers=self._headers,
                                         timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                body = await resp.json()
            out: set[str] = set()
            primary: str | None = None
            mac: str | None = None
            for iface in body["data"]["interfaces"]:
                for fam in ("ipv4", "ipv6"):
                    for a in (iface.get(fam) or {}).get("address") or []:
                        ip = canonical_ip(a.split("/", 1)[0])
                        if ip is not None:
                            out.add(ip)
                if iface.get("primary") and primary is None:
                    for a in (iface.get("ipv4") or {}).get("address") or []:
                        ip = canonical_ip(a.split("/", 1)[0])
                        if ip is not None:
                            primary = ip
                            m = iface.get("mac")
                            mac = m if isinstance(m, str) and m else None
                            break
        except Exception as e:  # noqa: BLE001 - any failure means "unknown"
            self._fail("network_info", e)
            return None, None, None
        self._ok("network_info")
        # No addresses at all (e.g. link down) is "unknown", not "the machine has no address".
        return (out or None), primary, mac

    async def pi_addresses(self) -> set[str] | None:
        return (await self.network_info())[0]

    async def host_name(self) -> str | None:
        """This machine's hostname, which it also sends to the router over DHCP; None when unknown."""
        if self._token is None:
            return None
        try:
            async with self._session.get(f"{self._base}/host/info", headers=self._headers,
                                         timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                name = (await resp.json())["data"]["hostname"]
            if not isinstance(name, str) or not name:
                raise ValueError("hostname missing")
        except Exception as e:  # noqa: BLE001
            self._fail("host_name", e)
            return None
        self._ok("host_name")
        return name

    async def tang_port(self) -> int | None:
        """The host port mapped to Tang in this app's Network settings; None when unknown or turned off."""
        if self._token is None:
            return None
        try:
            async with self._session.get(f"{self._base}/addons/self/info", headers=self._headers,
                                         timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                port = ((await resp.json())["data"].get("network") or {}).get(f"{TANG_CONTAINER_PORT}/tcp")
        except Exception as e:  # noqa: BLE001
            self._fail("tang_port", e)
            return None
        self._ok("tang_port")
        return port if type(port) is int else None  # bool is an int subclass; reject it

    async def get_options(self) -> dict | None:
        """The app's own validated options, or None when unknown."""
        if self._token is None:
            return None
        try:
            async with self._session.get(f"{self._base}/addons/self/options/config",
                                         headers=self._headers, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                data = (await resp.json())["data"]
            if not isinstance(data, dict):
                raise ValueError("options data is not an object")
        except Exception as e:  # noqa: BLE001
            self._fail("get_options", e)
            return None
        self._ok("get_options")
        return data

    async def set_options(self, options: dict) -> bool:
        """Write the COMPLETE options dict (merge behaviour is undocumented)."""
        if self._token is None:
            return False
        try:
            async with self._session.post(f"{self._base}/addons/self/options", json={"options": options},
                                          headers=self._headers, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            self._fail("set_options", e)
            return False
        self._ok("set_options")
        return True

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

    async def remove_state(self, entity_id: str) -> None:
        if self._token is None:
            return
        try:
            async with self._session.delete(f"{self._base}/core/api/states/{entity_id}",
                                            headers=self._headers, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            self._fail("remove_state", e)
            return
        self._ok("remove_state")

    async def fire_event(self, event_type: str, data: dict) -> None:
        await self._post("fire_event", f"/core/api/events/{event_type}", data)
