import threading
import time

from tang_monitor.naming import Namer, is_known, is_known_request


async def test_strips_dot_lowercases():
    n = Namer(lookup=lambda ip: "Server.lan.")
    assert await n.name_for("1.2.3.4") == "server.lan"


async def test_cache_hit_avoids_second_lookup():
    calls = []
    n = Namer(lookup=lambda ip: calls.append(ip) or "a.lan")
    await n.name_for("1.1.1.1")
    await n.name_for("1.1.1.1")
    assert len(calls) == 1


async def test_negative_result_cached():
    calls = []
    n = Namer(lookup=lambda ip: calls.append(ip))
    assert await n.name_for("1.1.1.1") is None
    assert await n.name_for("1.1.1.1") is None
    assert len(calls) == 1


async def test_hanging_lookup_times_out_to_none():
    release = threading.Event()
    n = Namer(lookup=lambda ip: release.wait(5), timeout=0.1)
    try:
        start = time.monotonic()
        assert await n.name_for("1.1.1.1") is None
        assert time.monotonic() - start < 1
    finally:
        release.set()


async def test_failed_lookup_is_not_cached():
    calls = []

    def flaky(ip):
        calls.append(ip)
        if len(calls) == 1:
            raise OSError("transient")
        return "a.lan"
    n = Namer(lookup=flaky)
    assert await n.name_for("1.1.1.1") is None
    assert await n.name_for("1.1.1.1") == "a.lan"
    assert len(calls) == 2


async def test_lookup_exception_gives_none():
    def boom(ip):
        raise OSError("nope")
    assert await Namer(lookup=boom).name_for("1.1.1.1") is None


def test_is_known():
    assert is_known("Host.LAN.", ["host.lan"])
    assert is_known("host.lan", ["HOST.lan."])
    assert not is_known("other", ["host.lan"])
    assert not is_known(None, ["host.lan"])


def test_is_known_request_by_name_or_ip_literal():
    assert is_known_request("host.lan", "1.1.1.1", ["host.lan"])
    assert is_known_request(None, "192.168.1.50", ["192.168.1.50"])
    assert is_known_request("other.lan", "fd00::5", ["FD00:0:0::5"])
    assert not is_known_request(None, "192.168.1.51", ["192.168.1.50", "host.lan"])
    assert not is_known_request(None, "192.168.1.51", ["not-an-ip"])
