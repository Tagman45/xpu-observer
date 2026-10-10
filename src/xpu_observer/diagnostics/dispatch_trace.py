"""Dispatch tracer — captures xrt::run start/wait/sync per dispatch.

Priority of instrumentation (per red-team): the runtime's OWN explicit trace
mechanism (CSV profiler, JSONL dispatch events, TOKEN markers) is ingested first.
DLL hooks are only a fallback when no native trace exists — a legitimate hook capture
is fed here as the same normalized event stream.

Canonical span fields: pid, tid, hwctx_id, kernel, instruction_hash, bo_id, group_id,
start_ns, end_ns, sync_direction, status, token_id, source.

Also accounts instruction cache hits/misses and BO reallocations so the MLIR-AIE-style
optimizations (cached instruction BOs, buffer reuse) can be verified against real runs.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# column aliases -> canonical field
_ALIASES: dict[str, tuple[str, ...]] = {
    "pid": ("pid", "process_id", "process"),
    "tid": ("tid", "thread_id", "thread"),
    "hwctx_id": ("hwctx_id", "hwctx", "context_id", "ctx_id"),
    "kernel": ("kernel", "kernel_name", "op", "op_name", "name"),
    "instruction_hash": ("instruction_hash", "instr_hash", "cache_key", "hash", "instruction"),
    "bo_id": ("bo_id", "buffer_id", "buf_id", "bo"),
    "group_id": ("group_id", "group"),
    "start_ns": ("start_ns", "start", "ts_ns", "begin_ns"),
    "end_ns": ("end_ns", "end", "complete_ns"),
    "sync_direction": ("sync_direction", "sync", "direction"),
    "status": ("status", "result"),
    "token_id": ("token_id", "token"),
    "submit_us": ("submit_us", "submit"),
    "wait_us": ("wait_us", "wait"),
    "npu_us": ("npu_us", "npu_eff", "compute"),
    "sync_us": ("sync_us", "sync_us", "sync_total"),
    "host_us": ("host_us", "host_ovh", "host"),
}

_PHASES = ("host_pre", "xrt_submit", "cx_wait", "np_dispatch", "np_completion",
           "sync_pre", "sync_post", "host_post", "bo_alloc", "bo_free",
           "instr_build", "instr_cache_hit")

_RUNNER_MS = re.compile(r"([a-z0-9_]+)_ms=([\d.]+)")
_NPUHOOK_EXEC = re.compile(r"Exec NPU\s*:\s*([\d.]+)\s*ms")


def _norm_field(header: str) -> Optional[str]:
    low = re.sub(r"[^a-z0-9_]", "", header.lower())
    for canon, aliases in _ALIASES.items():
        if low in aliases or low == canon:
            return canon
    return None


def _num(v: Any) -> Any:
    if v is None or v == "":
        return 0
    try:
        return int(v)
    except Exception:  # noqa: BLE001
        try:
            return float(v)
        except Exception:  # noqa: BLE001
            return v


@dataclass
class DispatchSpan:
    pid: int = 0
    tid: int = 0
    hwctx_id: int = 0
    kernel: str = ""
    instruction_hash: str = ""
    bo_id: int = -1
    group_id: int = 0
    start_ns: int = 0
    end_ns: int = 0
    sync_direction: str = ""          # none | pre | post | both
    status: str = "ok"
    token_id: Any = None
    source: str = ""
    submit_us: float = 0.0
    wait_us: float = 0.0
    npu_us: float = 0.0
    sync_us: float = 0.0
    host_us: float = 0.0
    total_us: float = 0.0            # measured total (dialects without breakdown)
    instruction_cache: str = "unknown"  # hit | miss | unknown

    @property
    def dur_ns(self) -> int:
        return max(0, self.end_ns - self.start_ns)

    @property
    def host_total_us(self) -> float:
        return self.submit_us + self.wait_us + self.host_us

    @property
    def measure_us(self) -> float:
        """Best available duration: real breakdown total, else measured total, else ns."""
        if any((self.submit_us, self.wait_us, self.npu_us, self.sync_us, self.host_us)):
            return self.submit_us + self.wait_us + self.npu_us + self.sync_us + self.host_us
        if self.total_us:
            return self.total_us
        return self.dur_ns / 1000.0

    def as_dict(self) -> dict[str, Any]:
        return {"pid": self.pid, "tid": self.tid, "hwctx_id": self.hwctx_id,
                "kernel": self.kernel, "instruction_hash": self.instruction_hash,
                "bo_id": self.bo_id, "group_id": self.group_id,
                "start_ns": self.start_ns, "end_ns": self.end_ns,
                "duration_ns": self.dur_ns, "sync_direction": self.sync_direction,
                "status": self.status, "token_id": self.token_id, "source": self.source,
                "breakdown_us": {"submit": round(self.submit_us, 1),
                                 "wait": round(self.wait_us, 1),
                                 "npu": round(self.npu_us, 1),
                                 "sync": round(self.sync_us, 1),
                                 "host": round(self.host_us, 1),
                                 "total": round(self.total_us, 1)},
                "instruction_cache": self.instruction_cache}


@dataclass
class TokenSpan:
    token_id: Any
    begin_ns: int
    end_ns: int
    total_us: float = 0.0


class DispatchTracer:
    def __init__(self, source: str = "") -> None:
        self.source = source
        self.spans: list[DispatchSpan] = []
        self.tokens: list[TokenSpan] = []
        # instruction cache accounting
        self._instr_seen: set[str] = set()
        self._instr_explicit: dict[str, str] = {}   # hash -> hit|miss
        self.instr_builds = 0
        self.instr_cache_hits = 0
        # BO accounting
        self._bo_alloc_count: dict[int, int] = {}
        self._bo_freed: set[int] = set()
        self.bo_reallocs = 0
        self.bo_reuses = 0
        # phase state machine for streamed events
        self._live: dict[int, DispatchSpan] = {}
        self._opened: dict[tuple[int, int], float] = {}

    # ------------------------------------------------------------------ events
    def add_span(self, **kw: Any) -> None:
        s = DispatchSpan(**{k: v for k, v in kw.items() if hasattr(DispatchSpan, k)})
        s.source = s.source or self.source
        if s.instruction_hash:
            s.instruction_cache = self._note_instruction(s.instruction_hash, None)
        if s.bo_id >= 0:
            self.bo_reuses += 1
        self.spans.append(s)

    def add_event(self, ev: dict[str, Any]) -> None:
        """Streamed runtime event. 'phase' selects handling; span events complete on end."""
        phase = str(ev.get("phase") or ev.get("type") or "")
        pid = int(ev.get("pid", 0) or 0)
        tid = int(ev.get("tid", 0) or 0)
        hwctx = int(ev.get("hwctx_id", ev.get("hwctx", 0)) or 0)
        ts = int(ev.get("ts_ns", ev.get("ts", 0)) or 0)
        if phase == "TOKEN_BEGIN":
            self.tokens.append(TokenSpan(ev.get("token_id", len(self.tokens)),
                                         ts, int(ev.get("end_ns", 0) or 0)))
        elif phase == "TOKEN_END":
            tid_ = ev.get("token_id")
            for t in self.tokens:
                if (tid_ is None or t.token_id == tid_) and t.end_ns == 0:
                    t.end_ns = ts
                    break
        elif phase in ("instr_build", "instr_miss", "instr_allocate"):
            self._note_instruction(str(ev.get("instruction_hash", ev.get("hash", ""))), "miss")
            self.instr_builds += 1
        elif phase in ("instr_cache_hit",):
            h = str(ev.get("instruction_hash", ev.get("hash", "")))
            self._note_instruction(h, "hit")
            self.instr_cache_hits += 1
        elif phase == "bo_alloc":
            bo = int(ev.get("bo_id", ev.get("bo", -1)) or -1)
            if bo >= 0:
                self._bo_alloc_count[bo] = self._bo_alloc_count.get(bo, 0) + 1
                if self._bo_alloc_count[bo] > 1 or bo in self._bo_freed:
                    self.bo_reallocs += 1
        elif phase == "bo_free":
            bo = int(ev.get("bo_id", ev.get("bo", -1)) or -1)
            if bo >= 0:
                self._bo_freed.add(bo)
        elif phase in ("xrt_submit", "run.start", "start"):
            key = (pid, tid, hwctx)
            bd = ev.get("breakdown_us") or {}
            self._live[key] = DispatchSpan(
                pid=pid, tid=tid, hwctx_id=hwctx,
                kernel=str(ev.get("kernel", "")),
                instruction_hash=str(ev.get("instruction_hash", "")),
                bo_id=int(ev.get("bo_id", -1) or -1),
                group_id=int(ev.get("group_id", 0) or 0),
                start_ns=ts, status=str(ev.get("status", "ok")),
                token_id=ev.get("token_id"), source=self.source,
                submit_us=float(bd.get("submit", ev.get("submit_us", 0.0) or 0.0)),
                wait_us=float(bd.get("wait", ev.get("wait_us", 0.0) or 0.0)),
                npu_us=float(bd.get("npu", ev.get("npu_us", 0.0) or 0.0)),
                sync_us=float(bd.get("sync", ev.get("sync_us", 0.0) or 0.0)),
                host_us=float(bd.get("host", ev.get("host_us", 0.0) or 0.0)))
        elif phase in ("run.wait", "wait", "xrt_wait"):
            key = (pid, tid, hwctx)
            sp = self._live.pop(key, None)
            if sp is not None:
                sp.end_ns = max(sp.end_ns, ts)
                sp.instruction_cache = self._note_instruction(sp.instruction_hash, None) \
                    if sp.instruction_hash else sp.instruction_cache
                if sp.bo_id >= 0:
                    self.bo_reuses += 1
                self.spans.append(sp)
        elif phase in ("sync_pre", "sync_post") or "sync" in phase:
            pass  # direction recorded when a complete span carries it

    def _note_instruction(self, hash_: str, explicit: Optional[str]) -> str:
        if not hash_:
            return "unknown"
        if explicit in ("hit", "miss"):
            self._instr_explicit[hash_] = explicit
        if hash_ in self._instr_seen:
            if self._instr_explicit.get(hash_, "hit") == "miss":
                # previously built -> reuse is a cache tier hit
                self.instr_cache_hits += 1
                return "hit"
            return "hit"
        self._instr_seen.add(hash_)
        if explicit == "miss":
            self.instr_builds += 1
            return "miss"
        return "miss"

    # ------------------------------------------------------------------. ingest
    def ingest_jsonl(self, path: str) -> int:
        n = 0
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if "phase" in ev or "type" in ev:
                    self.add_event(ev)
                else:
                    self.add_span(**{_norm_field(k) or k: v for k, v in ev.items()})
                n += 1
        return n

    def ingest_csv(self, path: str) -> int:
        """Auto-detects dialects:
          - xdna_profile (header: token_idx, sync_pre_us) with '_TOKEN' aggregate rows;
          - breakdown (submit_us/wait_us/npu_us/sync_us/host_us);
          - start_ns complete spans.
        """
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            lines = [ln for ln in fh if ln.startswith("#") is False]
        if not lines:
            return 0
        header = lines[0].strip().split(",")
        if "token_idx" in header and "sync_pre_us" in header:
            return self._ingest_xdna_profile_lines(header, lines[1:])
        return self._ingest_csv_generic(header, lines[1:])

    def _ingest_csv_generic(self, header: list[str], rows: list[str]) -> int:
        n = 0
        import io as _io
        reader = csv.DictReader(_io.StringIO("\n".join([",".join(header)] + rows)))
        cols = reader.fieldnames or []
        canon = {c: _norm_field(c) for c in cols}
        if "start_ns" in canon.values():
            for row in reader:
                if any(v not in (None, "") for v in row.values()):
                    self.add_span(**{canon[c]: _num(row[c]) for c in cols if canon[c]})
                    n += 1
        elif "submit_us" in canon.values():  # runtime profiler breakdown style
            acc = 0
            for row in reader:
                if all(row.get(c) in (None, "") for c in cols if canon[c]):
                    continue
                breakdown = {canon[c]: _num(row[c]) for c in cols
                             if canon[c] and canon[c] in
                             ("submit_us", "wait_us", "npu_us", "sync_us", "host_us")}
                start = int(acc)
                dur = int(sum(breakdown.values()) * 1000)
                acc += dur
                kw = {canon[c]: _num(row[c]) for c in cols
                      if canon[c] and canon[c] not in
                      ("submit_us", "wait_us", "npu_us", "sync_us", "host_us")}
                kw.update(breakdown)
                kw.update(start_ns=start, end_ns=start + dur)
                self.add_span(**kw)
                n += 1
        else:
            for row in reader:
                self.add_span(**{canon[c]: _num(row[c]) for c in cols if canon[c]})
                n += 1
        return n

    def _ingest_xdna_profile_lines(self, header: list[str], rows: list[str]) -> int:
        """Native runtime dialect. Header comment documents remap:
        submit_us=total_us, wait_us=dispatch_count(signed mirror in captures),
        sync_pre_us=npu_us, sync_post_us=sync_us, host_pre_us=host_us.
        '_TOKEN' rows are per-token aggregates; other rows per dispatch."""
        idx = {c: i for i, c in enumerate(header)}
        def g(row, col):
            i = idx.get(col)
            if i is None or i >= len(row) or row[i] in ("", None):
                return 0.0
            try:
                return float(row[i])
            except Exception:  # noqa: BLE001
                return 0.0
        acc = 0.0
        for raw in rows:
            row = raw.strip().split(",")
            if not row or row[0].strip() == "":
                continue
            token = int(_num(row[idx["token_idx"]]))
            kernel = str(row[idx["kernel"]])
            total = g(row, "submit_us")
            if kernel == "_TOKEN":
                self.tokens.append(TokenSpan(token, int(acc * 1000),
                                             int((acc + total) * 1000), total_us=total))
                acc += total
            else:
                self.add_span(kernel=kernel, token_id=token, total_us=total,
                              submit_us=0.0, wait_us=0.0,
                              npu_us=g(row, "sync_pre_us"), sync_us=g(row, "sync_post_us"),
                              host_us=g(row, "host_pre_us"), source="xdna_profile")
        return len(rows)

    def ingest_tokens_log(self, path: str) -> int:
        n = 0
        pat = re.compile(r"(TOKEN_(?:BEGIN|END))[,\s]+(\d+)[,\s]+(\d+(?:\.\d+)?)")
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = pat.search(line)
                if not m:
                    continue
                ev = {"phase": m.group(1), "token_id": int(m.group(2)),
                      "ts_ns": int(float(m.group(3)))}
                self.add_event(ev)
                n += 1
        return n

    def ingest(self, path: str) -> dict[str, Any]:
        """Auto-detect a trace source: file (csv/jsonl/log), a runtime dir, or a
        directory of xdna-runner report.json files."""
        if os.path.isdir(path):
            counts: dict[str, int] = {}
            n = self.ingest_xdna_runner_reports(path)
            if n:
                counts["xdna-runner report.json"] = n
            h = self.ingest_hook_logs(path)
            if h:
                counts["hook logs (NpuHook)"] = h
            for pat in ("xdna_profile*.csv", "dispatch*.csv", "*.jsonl", "runtime_trace*.log",
                        "runtime_stdout.log", "xrt_trace*.csv"):
                for f in sorted(glob.glob(os.path.join(path, pat))):
                    counts[f] = self._ingest_one(f)
            return {"ingested": counts}
        return {"ingested": {path: self._ingest_one(path)}}

    def ingest_hook_logs(self, root: str) -> int:
        """Ingest hook-captured dispatch events from NpuHook.dll logs.

        NpuHook.dll (MinHook on xrt_coreutil) prints `Exec NPU : X ms (...)` lines and
        writes logs under `<cwd>/logs/` (npuhook_dll.log, fence.log, xclbin.log,
        preemption.log). Each `Exec NPU` line is one observed NPU execution time.
        """
        n = 0
        pats = (os.path.join(root, "**", "logs", "*.log"),
                os.path.join(root, "**", "npuhook_dll.log"),
                os.path.join(root, "**", "fence.log"))
        seen: set[str] = set()
        for pat in pats:
            for f in glob.glob(pat, recursive=True):
                if f in seen:
                    continue
                seen.add(f)
                try:
                    with open(f, encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            m = _NPUHOOK_EXEC.search(line)
                            if m:
                                self.add_span(kernel="npu_hook",
                                              npu_us=float(m.group(1)) * 1000,
                                              source="NpuHook.dll")
                                n += 1
                except Exception:  # noqa: BLE001
                    continue
        return n

    def ingest_xdna_runner_reports(self, root: str) -> int:
        """Ingest `open-xdna-runtime` run reports: each report.json carries the runner
        stdout with per-run XRT timings (submit_ms, xrt_wait_ms, resident_dispatch_ms,
        xrt_setup_ms, bo_alloc_ms, h2d_write/sync_ms, runner_total_ms). One run ≈ one
        dispatch, so each becomes a DispatchSpan with a real host/wait/npu split."""
        n = 0
        for rp in sorted(glob.glob(os.path.join(root, "**", "report.json"), recursive=True)):
            try:
                with open(rp, encoding="utf-8", errors="replace") as fh:
                    data = json.load(fh)
            except Exception:  # noqa: BLE001
                continue
            stdout = data.get("stdout") or ""
            if "_ms=" not in stdout:
                continue
            ms = {m.group(1): float(m.group(2)) for m in _RUNNER_MS.finditer(stdout)}
            cmd = data.get("command") or []
            kernel = str(cmd[2]) if len(cmd) >= 3 else "MLIR_AIE"
            instr = (data.get("manifest") or {}).get("sha256", "")
            self.add_span(
                kernel=kernel, instruction_hash=instr,
                submit_us=ms.get("submit", 0.0) * 1000,
                wait_us=ms.get("xrt_wait", 0.0) * 1000,
                npu_us=ms.get("resident_dispatch", 0.0) * 1000,
                sync_us=ms.get("h2d_sync", 0.0) * 1000,
                host_us=(ms.get("input_read", 0.0) + ms.get("bo_alloc", 0.0)
                         + ms.get("h2d_write", 0.0) + ms.get("xrt_setup", 0.0)
                         + ms.get("output_write", 0.0)) * 1000,
                total_us=ms.get("runner_total", 0.0) * 1000,
                status=str(data.get("status", "")), source="xdna-runner")
            n += 1
        return n

    def _ingest_one(self, path: str) -> int:
        low = path.lower()
        if low.endswith(".jsonl"):
            return self.ingest_jsonl(path)
        if low.endswith(".csv"):
            return self.ingest_csv(path)
        if low.endswith(".log"):
            return self.ingest_tokens_log(path) + self.ingest_jsonl(path)
        return 0

    # ------------------------------------------------------------- correlation
    def correlate_tokens(self) -> int:
        """Assign token_id to each span containing its midpoint inside a token window."""
        if not self.tokens:
            return 0
        assigned = 0
        for sp in self.spans:
            if sp.token_id is not None:
                continue
            mid = (sp.start_ns + sp.end_ns) // 2
            for t in self.tokens:
                if t.end_ns and t.begin_ns <= mid < t.end_ns:
                    sp.token_id = t.token_id
                    assigned += 1
                    break
        return assigned

    # ------------------------------------------------------------------- stats
    def stats(self) -> dict[str, Any]:
        per_kernel: dict[str, dict[str, float]] = {}
        host_total = npu_total = sync_total = wait_total = 0.0
        for sp in self.spans:
            k = sp.kernel or "(unknown)"
            e = per_kernel.setdefault(k, {"n": 0.0, "dur_us": 0.0, "npu_us": 0.0,
                                          "sync_us": 0.0, "wait_us": 0.0,
                                          "host_us": 0.0, "max_dur_us": 0.0})
            d = sp.measure_us
            e["n"] += 1; e["dur_us"] += d
            e["npu_us"] += sp.npu_us; e["sync_us"] += sp.sync_us
            e["wait_us"] += sp.wait_us; e["host_us"] += sp.host_us
            e["max_dur_us"] = max(e["max_dur_us"], d)
            host_total += sp.host_total_us + sp.sync_us
            npu_total += sp.npu_us; sync_total += sp.sync_us; wait_total += sp.wait_us
        total = host_total + npu_total
        breakdown_present = total > 0
        hit = getattr(self, "instr_cache_hits", 0)
        miss = getattr(self, "instr_builds", 0) or max(0, len(self._instr_seen))
        bo_unique = len(self._bo_alloc_count) or max(0, len({s.bo_id for s in self.spans if s.bo_id >= 0}))
        token_us = [t.total_us for t in self.tokens if t.total_us]
        tok = {}
        if token_us:
            tok = {"n": len(token_us), "min_us": min(token_us), "max_us": max(token_us),
                   "mean_us": round(sum(token_us) / len(token_us), 1),
                   "median_us": _median(token_us),
                   "sum_us": round(sum(token_us), 1),
                   "tps_upper_bound": round(1e6 / (sum(token_us) / len(token_us)), 2)}
        self.correlate_tokens()
        return {
            "spans_total": len(self.spans),
            "tokens_total": len(self.tokens),
            "tokens_matched": sum(1 for sp in self.spans if sp.token_id is not None),
            "token_dispatch_us": tok,
            "per_kernel": per_kernel,
            "host_bound_pct": round(host_total / total * 100, 1) if total else None,
            "npu_bound_pct": round(npu_total / total * 100, 1) if total else None,
            "sync_pct": round(sync_total / total * 100, 1) if total else None,
            "wait_pct": round(wait_total / total * 100, 1) if total else None,
            "instruction_cache": {"hits": hit, "misses": miss,
                                  "total": hit + miss},
            "bo": {"unique_ids": bo_unique, "reallocs": self.bo_reallocs,
                   "reuses": self.bo_reuses},
            "verdict": self._verdict(host_total, npu_total, wait_total, sync_total,
                                     breakdown_present),
        }

    def _verdict(self, host: float, npu: float, wait: float, sync: float,
                 breakdown: bool) -> str:
        if not breakdown:
            return "TIMING_MEASURED" if self.spans else "no_trace"
        if not (host + npu):
            return "TIMING_MEASURED"
        if host / (host + npu) > 0.6:
            return "HOST_BOUND"
        if wait / (host + npu) > 0.35:
            return "SYNC_WAIT_BOUND"
        return "NPU_BOUND"


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0