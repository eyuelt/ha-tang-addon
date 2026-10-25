"""Fake tangd: one HTTP request on stdin, one response on stdout. Keydir arg ignored."""
import sys
import time

data = sys.stdin.buffer.read()
head, _, body = data.partition(b"\r\n\r\n")
line = head.split(b"\r\n", 1)[0]
if b"/slow" in line:
    time.sleep(30)
if line.startswith(b"GET /adv") or line.startswith(b"POST /rec/"):
    status = b"200 OK"
else:
    status = b"404 Not Found"
sys.stdout.buffer.write(
    b"HTTP/1.1 " + status + b"\r\nX-Body-Length: " + str(len(body)).encode()
    + b"\r\nContent-Length: 2\r\n\r\n{}")
sys.stdout.buffer.flush()
