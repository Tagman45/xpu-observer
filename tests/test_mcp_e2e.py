"""End-to-end MCP stdio test — real subprocess, real Content-Length framing.

Verifies the official handshake: initialize -> notifications/initialized ->
tools/list -> tools/call. Not a simulation: the bytes travel the actual pipes.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time

from xpu_observer.mcp.server import _build_tools, _schema

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

SCRIPT = (
    "from xpu_observer.runtime import App;"
    "from xpu_observer.mcp.server import run;"
    "app = App(); app.start(collect_immediately=False); run(app)"
)


def _frame(obj) -> bytes:
    body = json.dumps(obj).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body


class _Reader(threading.Thread):
    def __init__(self, stream):
        super().__init__(daemon=True)
        self._stream = stream
        self.frames = queue.Queue()

    def run(self):
        while True:
            headers = {}
            while True:
                line = self._stream.readline()
                if not line:
                    return
                if line in (b"\n", b"\r\n"):
                    break
                k, _, v = line.decode("latin-1").partition(":")
                headers[k.strip().lower()] = v.strip()
            n = int(headers.get("content-length", 0))
            if n and n < 10_000_000:
                body = self._stream.read(n)
                try:
                    self.frames.put(json.loads(body))
                except Exception:  # noqa: BLE001
                    pass


def _get(reader, timeout=20):
    return reader.frames.get(timeout=timeout)


def test_mcp_handshake():
    env = dict(os.environ, PYTHONPATH=SRC)
    proc = subprocess.Popen(
        [sys.executable, "-c", SCRIPT], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    reader = _Reader(proc.stdout)
    reader.start()
    try:
        assert proc.stdin is not None
        proc.stdin.write(_frame({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}))
        proc.stdin.flush()
        init = _get(reader)
        assert init["result"]["serverInfo"]["name"] == "xpu-observer"
        assert init["result"]["capabilities"]["tools"] == {}

        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized",
                                 "params": {}}))
        proc.stdin.flush()

        proc.stdin.write(_frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                                 "params": {}}))
        proc.stdin.flush()
        lst = _get(reader)
        names = [t["name"] for t in lst["result"]["tools"]]
        assert "get_cpu_metrics" in names
        assert "request_hook_activation" in names
        assert "request_hook_deactivation" in names

        proc.stdin.write(_frame({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                 "params": {"name": "get_monitor_health",
                                            "arguments": {}}}))
        proc.stdin.flush()
        call = _get(reader)
        assert call["result"]["isError"] is False
        assert "last_ts" in json.loads(call["result"]["content"][0]["text"])
    finally:
        proc.kill()


def test_schema_invalid_required():
    s = _schema([{"name": "pid", "type": "integer", "required": True}])
    assert s["required"] == ["pid"]


def test_build_tools_no_readonly_injection():
    tools = {t["name"] for t in _build_tools()}
    assert "request_hook_activation" in tools
    assert "request_hook_deactivation" in tools