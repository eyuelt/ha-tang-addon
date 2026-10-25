from tang_monitor.http_parse import parse_request_head, classify, parse_status, host_address
import pytest

def test_parses_rec_post():
    h = parse_request_head(b"POST /rec/abc HTTP/1.1\r\nHost: 192.168.1.87:7500\r\nContent-Length: 12\r\n\r\n")
    assert (h.method, h.path, h.host, h.content_length) == ("POST", "/rec/abc", "192.168.1.87:7500", 12)

def test_missing_host_and_length():
    h = parse_request_head(b"GET /adv HTTP/1.1\r\n\r\n")
    assert h.host is None and h.content_length == 0

@pytest.mark.parametrize("raw", [b"", b"garbage\r\n\r\n", b"GET\r\n\r\n", b"POST /rec/x HTTP/1.1\r\nContent-Length: -1\r\n\r\n"])
def test_malformed_raises(raw):
    with pytest.raises(ValueError):
        parse_request_head(raw)

@pytest.mark.parametrize("path,kind", [("/adv", "adv"), ("/adv/", "adv"), ("/adv/thp", "adv"), ("/rec/kid", "rec"), ("/", "other"), ("/recx", "other")])
def test_classify(path, kind):
    assert classify(path) == kind

def test_parse_status():
    assert parse_status(b"HTTP/1.1 200 OK\r\n...") == 200
    assert parse_status(b"nonsense") is None

@pytest.mark.parametrize("host,addr", [("192.168.1.87:7500", "192.168.1.87"), ("192.168.1.87", "192.168.1.87"),
    ("[fe80::1]:7500", "fe80::1"), ("pi.lan:7500", "pi.lan"), (None, None), ("", None)])
def test_host_address(host, addr):
    assert host_address(host) == addr
