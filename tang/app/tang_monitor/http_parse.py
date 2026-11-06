"""Minimal HTTP/1.x request and status-line parsing for the Tang proxy."""
import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RequestHead:
    method: str
    path: str
    host: str | None
    content_length: int


def parse_request_head(data: bytes) -> RequestHead:
    head = data.split(b"\r\n\r\n", 1)[0]
    try:
        lines = head.decode("latin-1").split("\r\n")
    except UnicodeDecodeError as e:  # pragma: no cover - latin-1 never fails
        raise ValueError("undecodable request") from e
    parts = lines[0].split(" ")
    if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2].startswith("HTTP/"):
        raise ValueError(f"malformed request line: {lines[0]!r}")
    host: str | None = None
    content_length = 0
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if not sep:
            continue
        name = name.strip().lower()
        value = value.strip()
        if name == "host":
            host = value
        elif name == "content-length":
            if not value.isascii() or not value.isdigit():
                raise ValueError(f"bad Content-Length: {value!r}")
            content_length = int(value)
    return RequestHead(parts[0], parts[1], host, content_length)


def classify(path: str) -> Literal["adv", "rec", "other"]:
    path = path.split("?", 1)[0]
    if path == "/adv" or path.startswith("/adv/"):
        return "adv"
    if path.startswith("/rec/"):
        return "rec"
    return "other"


_STATUS = re.compile(rb"HTTP/\d(?:\.\d)? (\d{3})")


def parse_status(data: bytes) -> int | None:
    m = _STATUS.match(data)
    return int(m.group(1)) if m else None


def host_address(host: str | None) -> str | None:
    if not host:
        return None
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end > 1 else None
    if host.count(":") == 1:
        return host.split(":", 1)[0] or None
    return host


def host_port(host: str | None) -> int | None:
    """The port in a Host header (80, the http default, when absent); None when missing or invalid."""
    if not host:
        return None
    if host.startswith("["):
        end = host.find("]")
        rest = host[end + 1:] if end > 1 else ""
    elif host.count(":") == 1:
        rest = host[host.index(":"):]
    else:
        rest = ""  # a bare name, IPv4 address or unbracketed IPv6 address
    if not rest:
        return 80
    if not rest.startswith(":") or not rest[1:].isdigit():
        return None
    port = int(rest[1:])
    return port if 0 < port < 65536 else None
