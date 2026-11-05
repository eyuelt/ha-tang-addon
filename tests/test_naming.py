import socket
import threading
import time

import pytest

from tang_monitor.naming import Namer, is_known, is_known_request, reverse_lookup


@pytest.mark.parametrize("errno", [1, 4])  # HOST_NOT_FOUND, NO_DATA
def test_reverse_lookup_no_name_is_a_real_none(monkeypatch, errno):
    def fail(ip):
        raise socket.herror(errno, "no name")
    monkeypatch.setattr(socket, "gethostbyaddr", fail)
    assert reverse_lookup("10.0.0.5") is None


@pytest.mark.parametrize("exc", [socket.herror(2, "try again"), socket.gaierror(-3, "temporary failure"),
                                 TimeoutError()])
def test_reverse_lookup_transient_failure_raises(monkeypatch, exc):
    def fail(ip):
        raise exc
    monkeypatch.setattr(socket, "gethostbyaddr", fail)
    with pytest.raises(OSError):
        reverse_lookup("10.0.0.5")


async def test_transient_failure_through_namer_is_retried(monkeypatch):
    calls = []

    def flaky(ip):
        calls.append(ip)
        if len(calls) == 1:
            raise socket.herror(2, "try again")
        return ("pi.lan", [], [ip])
    monkeypatch.setattr(socket, "gethostbyaddr", flaky)
    n = Namer()
    assert await n.name_for("10.0.0.5") is None
    assert await n.name_for("10.0.0.5") == "pi.lan"


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
