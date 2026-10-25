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
    assert "Reserve 192.168.1.112" in out
    assert "&lt;b&gt;stranger" in out  # untrusted name escaped, not injected as markup
