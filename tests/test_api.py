"""API server test — start on ephemeral port, query endpoints."""
import json
import os
import subprocess
import sys
import urllib.request

from xpu_observer.runtime import App
from xpu_observer.api.server import start_api

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _get(url, tries=3):
    last = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.5)
    raise last


def test_api_metrics():
    # No scheduler: the API reads the (empty) snapshot; avoids background load.
    app = App()
    srv = start_api(app, port=0)
    port = srv._httpd.server_address[1]
    try:
        health = _get(f"http://127.0.0.1:{port}/health")
        assert health["ok"] is True
        m = _get(f"http://127.0.0.1:{port}/metrics")
        assert "metrics" in m
    finally:
        srv.stop()


def test_cli_once():
    env = dict(os.environ, PYTHONPATH=SRC)
    out = subprocess.run(
        [sys.executable, "-m", "xpu_observer.main", "--once"],
        capture_output=True, text=True, env=env, timeout=90)
    assert out.returncode == 0
    data = json.loads(out.stdout)
    assert "metrics" in data and "ts" in data