"""TCP front end: one fresh tangd subprocess per connection, reporting each request."""
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from .http_parse import classify, parse_request_head, parse_status
from .records import TangRequest

log = logging.getLogger(__name__)

MAX_HEAD = 16384
MAX_BODY = 65536
_LOOPBACK = {"127.0.0.1", "::1"}


async def start_tang_server(
    host: str,
    port: int,
    keydir: Path,
    on_request: Callable[[TangRequest], Awaitable[None]],
    tangd: Sequence[str] = ("/usr/libexec/tangd",),
    timeout: float = 10.0,
    report_loopback: bool = False,
) -> asyncio.Server:
    async def run_tangd(request: bytes) -> bytes:
        proc = await asyncio.create_subprocess_exec(
            *tangd, str(keydir),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        try:
            out, _ = await proc.communicate(request)
            return out
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: dict) -> None:
        head_bytes = await reader.readuntil(b"\r\n\r\n")
        head = parse_request_head(head_bytes)
        state["head"] = head
        if head.content_length > MAX_BODY:
            raise ValueError("body too large")
        body = await reader.readexactly(head.content_length)
        out = await run_tangd(head_bytes + body)
        writer.write(out)
        await writer.drain()
        state["status"] = parse_status(out)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        state: dict = {"head": None, "status": None}
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else "unknown"
        try:
            await asyncio.wait_for(serve(reader, writer, state), timeout)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug("connection from %s failed: %r", ip, e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        head = state["head"]
        if head is None or (ip in _LOOPBACK and not report_loopback):
            return
        try:
            await on_request(TangRequest(
                at=datetime.now(timezone.utc), ip=ip, host=head.host,
                kind=classify(head.path), status=state["status"]))
        except Exception:
            log.exception("on_request callback failed")

    return await asyncio.start_server(handle, host, port, limit=MAX_HEAD)
