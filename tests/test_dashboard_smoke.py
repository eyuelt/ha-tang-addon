"""Render the demo dashboard in headless Chrome and check the real DOM."""
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
APP_DIR = Path(__file__).parent.parent / "tang/app"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def demo_url():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "tang_monitor.web", "--demo", "--port", str(port)],
                            cwd=APP_DIR, env={**os.environ, "PYTHONPATH": str(APP_DIR)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(url + "api/state", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("demo server did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_demo_dashboard_renders_real_dom(demo_url, tmp_path):
    if not os.path.exists(CHROME):
        pytest.skip(f"headless Chrome not found at {CHROME}")
    out = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", f"--user-data-dir={tmp_path}",
         "--virtual-time-budget=5000", "--dump-dom", demo_url],
        capture_output=True, text=True, timeout=60).stdout
    assert "<main" in out
    assert "[object" not in out
    assert not re.search(r"(^|>)\s*null\s*(<|$)", out, re.M)  # a stray "null" text node
    assert ">When<" in out and ">Who<" in out and ">Result<" in out
    assert "How to fix" in out
    assert "Reserve <code>192.168.1.112</code>" in out  # addresses are bold (.banner .text code)
    assert "&lt;b&gt;stranger" in out  # untrusted name escaped, not injected as markup
    assert ">Mark as reserved<" in out  # the reservation banner button
    assert "then press “Mark as reserved”." in out
    # Every banner shares one layout: text, then actions on the right.
    assert 'class="banner warn"' in out and 'class="banner bad"' in out and 'class="alert' not in out
    assert re.search(r'class="banner bad">.*?<div class="actions"><button[^>]*>I\'ve fixed it<', out, re.S)
    # One combined endpoint per side, so an address change and a port change read the same way.
    assert ("<code>laptop.lan</code> unlocks via <code>192.168.1.87:7500</code>, but Tang is now at "
            "<code>192.168.1.112:7500</code>") in out
    assert '<code>02:00:00:00:00:01</code>' in out  # bold via .banner code, kept on one line
    assert "for this Home Assistant machine" in out and "this Pi" not in out
    assert "02:00:00:00:00:01" in out and "homeassistant" in out  # how to spot this machine in the router's list
    assert ">Mark as known<" in out  # on the unknown row
    assert "desktop.lan" in out and "known, not seen yet" in out  # known device with no record
    # Devices row: own address in parentheses, then the address it reaches Tang at, labelled.
    assert "reaches Tang at <code>192.168.1.112:7500</code>" in out and "last seen" in out and not re.search(r"\.lan via <code>", out)
