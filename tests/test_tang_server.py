import asyncio
import sys
from pathlib import Path

import pytest

from tang_monitor.tang_server import start_tang_server

FAKE = (sys.executable, str(Path(__file__).resolve().parent / "fake_tangd.py"))


@pytest.fixture
async def server(tmp_path):
    reports = []

    async def on_request(r):
        reports.append(r)

    servers = []

    async def make(**kw):
        kw.setdefault("report_loopback", True)
        kw.setdefault("tangd", FAKE)
        s = await start_tang_server("127.0.0.1", 0, tmp_path, on_request, **kw)
        servers.append(s)
        return s, s.sockets[0].getsockname()[1], reports

    yield make
    for s in servers:
        s.close()
        await s.wait_closed()


async def exchange(port, data, *, half_close=False):
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(data)
    await w.drain()
    if half_close:
        w.write_eof()
    out = await asyncio.wait_for(r.read(), 5)
    w.close()
    return out


async def settle():
    await asyncio.sleep(0.2)


async def test_adv_roundtrip_reports_kind_status_host(server):
    _, port, reports = await server()
    out = await exchange(port, b"GET /adv HTTP/1.1\r\nHost: tang.local:7500\r\n\r\n")
    assert out.startswith(b"HTTP/1.1 200 OK")
    await settle()
    assert len(reports) == 1
    r = reports[0]
    assert (r.ip, r.host, r.kind, r.status) == ("127.0.0.1", "tang.local:7500", "adv", 200)
    assert r.at.tzinfo is not None


async def test_rec_with_body_passes_body_to_tangd(server):
    _, port, reports = await server()
    body = b"x" * 1000
    out = await exchange(
        port, b"POST /rec/abc HTTP/1.1\r\nHost: h\r\nContent-Length: 1000\r\n\r\n" + body)
    assert b"X-Body-Length: 1000" in out
    await settle()
    assert reports[0].kind == "rec" and reports[0].status == 200


async def test_garbage_closes_and_reports_nothing(server):
    _, port, reports = await server()
    assert await exchange(port, b"garbage\r\n\r\n") == b""
    assert await exchange(port, b"no terminator at all", half_close=True) == b""
    await settle()
    assert reports == []


async def test_oversized_body_closes_with_status_none(server):
    _, port, reports = await server()
    out = await exchange(port, b"POST /rec/a HTTP/1.1\r\nHost: h\r\nContent-Length: 70000\r\n\r\n")
    assert out == b""
    await settle()
    assert len(reports) == 1 and reports[0].status is None and reports[0].kind == "rec"


async def test_client_disconnect_midway_server_still_serves_next(server):
    _, port, reports = await server()
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(b"POST /rec/a HTTP/1.1\r\nHost: h\r\nContent-Length: 100\r\n\r\nshort")
    await w.drain()
    w.close()
    await settle()
    assert len(reports) == 1 and reports[0].status is None
    out = await exchange(port, b"GET /adv HTTP/1.1\r\nHost: h\r\n\r\n")
    assert out.startswith(b"HTTP/1.1 200")


async def test_tangd_timeout_status_none(server):
    _, port, reports = await server(timeout=0.5)
    out = await exchange(port, b"GET /slow HTTP/1.1\r\nHost: h\r\n\r\n")
    assert out == b""
    await settle()
    assert len(reports) == 1 and reports[0].status is None


async def test_loopback_not_reported_by_default(server):
    _, port, reports = await server(report_loopback=False)
    out = await exchange(port, b"GET /adv HTTP/1.1\r\nHost: h\r\n\r\n")
    assert out.startswith(b"HTTP/1.1 200")
    await settle()
    assert reports == []


async def test_missing_tangd_logs_error_status_none_and_keeps_serving(server, tmp_path, caplog):
    import logging
    _, port, reports = await server(tangd=("/nonexistent/tangd",))
    with caplog.at_level(logging.WARNING, logger="tang_monitor.tang_server"):
        out = await exchange(port, b"GET /adv HTTP/1.1\r\nHost: h\r\n\r\n")
        out2 = await exchange(port, b"GET /adv HTTP/1.1\r\nHost: h\r\n\r\n")
        await settle()
    assert out == b"" and out2 == b""
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
    assert len(reports) == 2 and all(r.status is None for r in reports)
