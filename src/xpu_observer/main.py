"""xpu-observer CLI entry point.

Modes:
  --once                 collect one pass, print JSON, exit (for scripts/tests)
  --export PATH          collect one pass, write snapshot CSV/JSON, exit
  --api                  start local HTTP API (127.0.0.1:8766) and headless loop
  --mcp                  run MCP server over stdio (with --api both can run)
  --ui                   start the tkinter dashboard
Default (no flag): headless background collection with API.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Optional

from . import __version__


def _parse(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="xpu-observer",
                                description="Universal Windows CPU/GPU/NPU monitor")
    p.add_argument("--once", action="store_true", help="collect once and print JSON")
    p.add_argument("--export", metavar="PATH", help="write snapshot export and exit")
    p.add_argument("--api", action="store_true", help="start local HTTP API")
    p.add_argument("--api-port", type=int, default=8766)
    p.add_argument("--mcp", action="store_true", help="run MCP server (stdio)")
    p.add_argument("--ui", action="store_true", help="start tkinter dashboard")
    p.add_argument("--interval", type=float, default=2.0, help="fast collect interval (s)")
    p.add_argument("--version", action="version", version=f"xpu-observer {__version__}")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse(argv)
    from .runtime import App  # noqa: PLC0415

    if args.once or args.export:
        app = App()
        app.scheduler._interval = args.interval
        app.start(collect_immediately=True)
        snap = app.collector.snap()
        app.stop()
        if args.export:
            from .export import csv as _csv  # noqa: PLC0415
            from .export import json as _json  # noqa: PLC0415
            path = args.export
            if path.lower().endswith(".csv"):
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(_csv.snapshot_to_csv(snap))
            else:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(_json.dump(snap.as_dict()))
            print(f"exported -> {path}")
        else:
            print(json.dumps(snap.as_dict(), indent=2, default=str))
        return 0

    app = App()
    app.scheduler._interval = args.interval
    app.start(collect_immediately=True)

    api = None
    if args.api:
        from .api.server import start_api  # noqa: PLC0415
        api = start_api(app, port=args.api_port)
        print(f"API: http://127.0.0.1:{args.api_port}")

    if args.ui:
        from .ui.main_window import launch  # noqa: PLC0415
        launch(app)
        app.stop()
        if api:
            api.stop()
        return 0

    if args.mcp:
        from .mcp.server import run  # noqa: PLC0415
        run(app)
        app.stop()
        if api:
            api.stop()
        return 0

    # headless background loop (api only)
    try:
        print("xpu-observer running (ctrl+c to stop)")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        if api:
            api.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())