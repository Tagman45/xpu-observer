"""XRT provider — NPU contexts, dispatches, columns, temp/power/freq via xrt-smi.

Portable: the xrt-smi binary is discovered at runtime (PATH / SystemRoot/System32/AMD).
Every metric records its source; tokens/s here is an *estimated* rate (heuristic based
on dispatch deltas), never asserted as a measured token counter.
"""
from __future__ import annotations

import re
from collections import deque
from typing import Any, Optional

from ..core import util
from ..core.metrics import Metric, ESTIMATED, UNAVAILABLE, mk

_WORKLOAD = ("flm", "llama", "llm", "qwen", "ggml", "xdna", "onnx",
             "vitis", "ryzen", "aie", "kernel", "stream", ".exe")


def parse_aie_partitions(raw: str) -> dict[str, Any]:
    res = {"device": "", "total_mem_mb": 0.0, "columns": [], "contexts": []}
    for line in raw.splitlines():
        m = re.search(r"\[.*?\]\s*:\s*(.*)", line)
        if m:
            res["device"] = m.group(1).strip()
            break
    for line in raw.splitlines():
        m = re.match(r"\s*Total Memory Usage:\s*([\d.]+)\s*MB", line)
        if m:
            res["total_mem_mb"] = float(m.group(1))
            break
    for line in raw.splitlines():
        m = re.search(r"Columns:\s*\[(.*?)\]", line)
        if m:
            res["columns"] = [int(x) for x in m.group(1).split(",") if x.strip().isdigit()]
            break
    ctx, row = {}, 0
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if not parts:
            continue
        if all(re.match(r"[=\-]+$", p) for p in parts):
            if ctx:
                res["contexts"].append(ctx)
                ctx = {}
            row = 0
            continue
        if row == 0 and parts and re.match(r"^\d+$", parts[0]):
            ctx = {
                "pid": int(parts[0]),
                "ctx_id": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
                "submissions": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
                "errors": int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0,
                "name": "", "completions": 0, "gops": 0,
                "mem_kb": 0, "instr_bo_kb": 0, "status": "",
            }
            # Single-line row: the name block follows on the same line
            # (adjacent | | collapses so name lands at index 4).
            if len(parts) >= 7:
                ctx["name"] = parts[4]
                ctx["status"] = parts[5]
                ctx["completions"] = int(parts[6]) if parts[6].isdigit() else 0
                if len(parts) > 8 and parts[8].isdigit():
                    ctx["gops"] = int(parts[8])
                res["contexts"].append(ctx)
                ctx = {}
                row = 0
            else:
                row = 1
        elif row == 1 and ctx:
            ctx["name"] = parts[0] if parts else ""
            ctx["status"] = parts[1] if len(parts) > 1 else ""
            ctx["completions"] = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            ctx["gops"] = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
            res["contexts"].append(ctx)
            ctx = {}
            row = 0
    if ctx:
        res["contexts"].append(ctx)
    return res


def parse_platform(raw: str) -> dict[str, float]:
    out = {"temp_c": 0.0, "power_w": 0.0, "freq_mhz": 0.0}
    for line in raw.splitlines():
        m = re.search(r"[Tt]emperature\D*([\d.]+)\s*C", line)
        if m:
            out["temp_c"] = float(m.group(1))
            continue
        m = re.search(r"[Pp]ower\D*([\d.]+)\s*W", line)
        if m:
            out["power_w"] = float(m.group(1))
            continue
        m = re.search(r"[Ff]req(?:uency)?\D*([\d.]+)\s*(?:MHz|GHz)", line)
        if m:
            v = float(m.group(1))
            out["freq_mhz"] = v * 1000 if "GHz" in line else v
    return out


def _is_workload(c: dict) -> bool:
    nm = (c.get("name") or "").lower()
    if any(k in nm for k in ("workload", "mcdm", "sessionhost", "amdxdna")):
        return False
    if any(k in nm for k in _WORKLOAD):
        return True
    return c.get("submissions", 0) > 0


class XRT:
    """Stateful NPU collector: keeps previous submissions to compute dispatch rates."""

    def __init__(self) -> None:
        self._path = util.find_xrt_smi()
        self._prev_subs: dict[int, int] = {}
        self._hist = deque(maxlen=30)
        self._ts: Optional[float] = None
        self._cycle = 0

    @property
    def available(self) -> bool:
        return self._path is not None

    def collect(self) -> tuple[list[Metric], dict[str, Any]]:
        src = "xrt-smi"
        if not self.available:
            return (
                [Metric("npu.state", None, source=src, available=False, validity=UNAVAILABLE,
                        note="xrt-smi not found")],
                {"xrt": {"available": False}},
            )
        self._cycle += 1
        rc, out = util.run([self._path, "examine", "-r", "aie-partitions", "--verbose"], timeout=6)
        if rc != 0 or not out:
            return ([Metric("npu.state", None, source=src, available=False, validity=UNAVAILABLE,
                            note="xrt-smi failed")],
                    {"xrt": {"available": False}})
        res = parse_aie_partitions(out)
        plat = {}
        if self._cycle % 8 == 0:
            rc2, out2 = util.run([self._path, "examine", "-r", "platform", "--verbose"], timeout=5)
            if rc2 == 0:
                plat = parse_platform(out2)
        ctxs = [c for c in res["contexts"] if _is_workload(c)]
        now = util.mono()
        interval = 0.1
        if self._ts is not None:
            interval = max(0.1, now - self._ts)
        self._ts = now
        layer_delta = 0
        live = set()
        for c in ctxs:
            cid = c["ctx_id"]
            prev = self._prev_subs.get(cid, c["submissions"])
            delta = max(0, c["submissions"] - prev)
            self._prev_subs[cid] = c["submissions"]
            c["delta"] = delta
            layer_delta += delta
            live.add(cid)
        for k in [k for k in self._prev_subs if k not in live]:
            del self._prev_subs[k]
        disp_s = layer_delta / interval
        self._hist.append(disp_s)
        disp_smooth = sum(self._hist) / len(self._hist)
        # COPIES the source heuristic of the reference app: 1 dispatch = 1 token for
        # FLM/llama single-thread workloads; otherwise estimated via ratio. Explicitly
        # marked ESTIMATED — never asserted as a measured token counter.
        is_flm = any((c.get("name") or "").lower().startswith("flm") for c in ctxs)
        tps = disp_smooth if is_flm else disp_smooth / 179.0
        state = "ACTIVE" if ctxs else "IDLE"
        total_subs = sum(c.get("submissions", 0) for c in ctxs)
        total_errs = sum(c.get("errors", 0) for c in ctxs)
        completions = sum(c.get("completions", 0) for c in ctxs)
        fail = (total_subs - completions) / total_subs * 100.0 if total_subs > 0 else 0.0
        metrics = [
            mk("npu.state", None if state == "IDLE" else 1.0, "", source=src,
               note=state),
            mk("npu.display", state, "", source=src),
            mk("npu.dispatch_s", disp_smooth, "1/s", source=src),
            mk("npu.tps_est", tps, "tokens/s", source=src, validity=ESTIMATED,
               note="heuristic from dispatch deltas; not a measured token counter"),
            mk("npu.ctx_count", float(len(ctxs)), "", source=src),
            mk("npu.mem_mb", res["total_mem_mb"], "MB", source=src),
            mk("npu.cols", float(len(res["columns"])), "", source=src),
            mk("npu.submissions", float(total_subs), "", source=src),
            mk("npu.errors", float(total_errs), "", source=src),
            mk("npu.fail_rate_pct", fail, "%", source=src),
            mk("npu.temp_c", plat.get("temp_c") or None, "C", source=src),
            mk("npu.power_w", plat.get("power_w") or None, "W", source=src),
            mk("npu.freq_mhz", plat.get("freq_mhz") or None, "MHz", source=src),
        ]
        raw = {"xrt": {"available": True, "device": res["device"], "columns": res["columns"],
                       "contexts": ctxs, "platform": plat}}
        return metrics, raw


_xrt_instance: Optional[XRT] = None


def collect() -> tuple[list[Metric], dict[str, Any]]:
    """Module-level collect(): keeps a single stateful XRT instance across cycles."""
    global _xrt_instance
    if _xrt_instance is None:
        _xrt_instance = XRT()
    return _xrt_instance.collect()