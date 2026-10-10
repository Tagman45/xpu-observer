"""Local HTTP API (read-only + export), bound to 127.0.0.1 only.

Security: no writes, no arbitrary injection, responses bounded. Hook activation is
NEVER exposed here — it goes through the MCP confirmation flow (UI side).
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from ..export import csv as _csv
from ..export import json as _json


class _Handler(BaseHTTPRequestHandler):
    app: Any = None
    server: "_APIServer" = None

    def log_message(self, *a):  # silence
        pass

    def _send(self, code: int, body: Any, ctype: str = "application/json") -> None:
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        app = self.app
        try:
            if u.path == "/health":
                return self._send(200, {"ok": True, "ts": 0})
            if u.path == "/metrics":
                return self._send(200, app.snapshot_dict())
            if u.path == "/metrics/history":
                n = _int(q.get("limit", ["100"])[0], 100)
                items = app.collector.history_list(max_items=max(1, min(2000, n)))
                return self._send(200, {"items": items})
            if u.path == "/capabilities":
                return self._send(200, app.caps)
            if u.path == "/processes":
                snap = app.collector.snap()
                return self._send(200, {"processes": snap.raw.get("processes", [])})
            if u.path == "/npu/kernels":
                snap = app.collector.snap()
                return self._send(200, {"kernels": (snap.raw.get("npu") or {})
                                        .get("kernels", [])})
            if u.path.startswith("/trace/"):
                path = (q.get("path") or [""])[0]
                if not path:
                    return self._send(400, {"error": "path required"})
                from ..diagnostics.dispatch_trace import DispatchTracer  # noqa: PLC0415
                tr = DispatchTracer()
                tr.ingest(path)
                if u.path == "/trace/dispatch":
                    limit = _int(q.get("limit", ["200"])[0], 200)
                    st = tr.stats()
                    st["spans"] = [s.as_dict() for s in tr.spans[:max(1, min(2000, limit))]]
                    return self._send(200, st)
                if u.path == "/trace/cache":
                    st = tr.stats()
                    return self._send(200, {"instruction_cache": st["instruction_cache"],
                                            "bo": st["bo"], "spans_total": len(tr.spans)})
                if u.path == "/trace/export":
                    from ..export import chrome_trace  # noqa: PLC0415
                    fmt = q.get("format", ["chrome"])[0]
                    if fmt == "chrome":
                        body = chrome_trace.to_chrome_trace(
                            tr.spans, tr.stats()["instruction_cache"])
                        return self._send(200, body, ctype="application/json")
                    return self._send(400, {"error": "format inconnu (chrome)"})
            if u.path == "/drivers":
                return self._send(200, app.caps.get("drivers", {}))
            if u.path == "/hooks":
                hooks = app.hooks
                return self._send(200, {"state": "unavailable"} if hooks is None
                                  else {"state": "available",
                                        "hooks": hooks.status()})
            if u.path == "/export":
                fmt = q.get("format", ["json"])[0]
                snap = app.collector.snap()
                limit = _int(q.get("limit", ["0"])[0], 0)
                if fmt == "csv":
                    return self._send(200, _csv.snapshot_to_csv(snap),
                                      ctype="text/csv")
                if fmt == "history.csv":
                    items = app.collector.history_list(max_items=limit or 100)
                    return self._send(200, _csv.history_to_csv(items),
                                      ctype="text/csv")
                return self._send(200, _json.dump(snap.as_dict()))
            return self._send(404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})


class _APIServer:
    def __init__(self, app, port: int = 8766) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self._httpd.RequestHandlerClass.app = app
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="xpu-api", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()


def start_api(app, port: int = 8766) -> _APIServer:
    srv = _APIServer(app, port=port)
    srv.start()
    return srv


def _int(s: str, default: int) -> int:
    try:
        return int(s)
    except Exception:  # noqa: BLE001
        return default