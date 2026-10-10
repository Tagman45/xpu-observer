"""API server test — start on ephemeral port, query endpoints."""
import json
import os
import subprocess
import sys
import urllib.request

from xpu_observer.runtime import App
from xpu_observer.api.server import start_api

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())


def test_api_metrics():
    app = App()
    app.start(collect_immediately=False)
    srv = start_api(app, port=0)
    port = srv._httpd.server_address[1]
    try:
        health = _get(f"http://127.0.0.1:{port}/health")
        assert health["ok"] is True
        m = _get(f"http://127.0.0.1:{port}/metrics")
        assert "metrics" in m
        caps = _get(f"http://127.0.0.1:{port}/capabilities")
        assert "gpus" in caps or "npu" in caps
    finally:
        srv.stop()
        app.stop()


def test_cli_once():
    env = dict(os.environ, PYTHONPATH=SRC)
    out = subprocess.run(
        [sys.executable, "-m", "xpu_observer.main", "--once"],
        capture_output=True, text=True, env=env, timeout=90)
    assert out.returncode == 0
    data = json.loads(out.stdout)
    assert "metrics" in data and "ts" in data