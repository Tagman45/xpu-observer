"""Tests for the XRT dispatch tracer (P0)."""
import json
import os

from xpu_observer.diagnostics.dispatch_trace import DispatchTracer, DispatchSpan
from xpu_observer.export import chrome_trace


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_jsonl_complete_spans(tmp_path):
    lines = [
        {"pid": 4528, "tid": 7890, "hwctx_id": 0, "kernel": "int4_gemv",
         "instruction_hash": "h1", "bo_id": 3, "group_id": 0,
         "start_ns": 1_000_000, "end_ns": 5_000_000,
         "sync_direction": "pre", "status": "ok", "token_id": 12},
        {"pid": 4528, "tid": 7890, "hwctx_id": 0, "kernel": "int4_gemv",
         "instruction_hash": "h1", "bo_id": 3, "group_id": 0,
         "start_ns": 6_000_000, "end_ns": 9_000_000, "sync_direction": "none",
         "status": "ok"},
        {"pid": 4528, "tid": 7891, "hwctx_id": 0, "kernel": "post_attn_fused",
         "instruction_hash": "h2", "bo_id": 7, "group_id": 0,
         "start_ns": 15_000_000, "end_ns": 25_000_000,
         "sync_direction": "both", "status": "timeout"},
    ]
    path = _write(tmp_path, "spans.jsonl",
                  "\n".join(json.dumps(l) for l in lines))
    tr = DispatchTracer()
    assert tr.ingest_jsonl(path) == 3
    assert len(tr.spans) == 3
    s0 = tr.spans[0]
    assert s0.kernel == "int4_gemv" and s0.token_id == 12
    assert s0.dur_ns == 4_000_000
    st = tr.stats()
    assert st["spans_total"] == 3
    assert set(st["per_kernel"]) == {"int4_gemv", "post_attn_fused"}
    # repeated instruction hash on rewrite path = reuse
    assert st["instruction_cache"]["misses"] == 2  # h1, h2 first occurrence
    sc = next(s for s in tr.spans if s.kernel == "int4_gemv" and s.end_ns == 9_000_000)
    assert sc.instruction_cache == "hit"


def test_csv_breakdown_style(tmp_path):
    csv_text = (
        "kernel,submit_us,wait_us,npu_us,sync_us,host_us,status\n"
        "int4_gemv,10,30,50,20,15,ok\n"
        "int4_gemv,12,28,52,18,14,timed_out\n"
    )
    path = _write(tmp_path, "xdna_profile.csv", csv_text)
    tr = DispatchTracer()
    assert tr.ingest_csv(path) == 2
    s = tr.spans[0]
    assert s.npu_us == 50.0 and s.wait_us == 30.0 and s.host_us == 15.0
    assert s.dur_ns == int((10 + 30 + 50 + 20 + 15) * 1000)
    st = tr.stats()
    assert st["per_kernel"]["int4_gemv"]["npu_us"] == 102.0  # 50+52
    assert st["verdict"] in ("HOST_BOUND", "NPU_BOUND", "SYNC_WAIT_BOUND")


def test_token_log(tmp_path):
    log = (
        "TOKEN_BEGIN,1,0\n"
        "TOKEN_BEGIN,2,100\n"
        "TOKEN_END,1,90\n"
        "TOKEN_END,2,190\n"
    )
    path = _write(tmp_path, "runtime_trace.log", log)
    tr = DispatchTracer()
    assert tr.ingest_tokens_log(path) == 4
    assert len(tr.tokens) == 2
    assert tr.tokens[0].begin_ns == 0 and tr.tokens[0].end_ns == 90


def test_token_correlation(tmp_path):
    lines = [
        {"pid": 1, "tid": 1, "kernel": "k", "start_ns": 10, "end_ns": 40},
        {"pid": 1, "tid": 1, "kernel": "k2", "start_ns": 60, "end_ns": 90},
    ]
    path = _write(tmp_path, "sp.jsonl", "\n".join(json.dumps(l) for l in lines))
    log = _write(tmp_path, "tok.log", "TOKEN_BEGIN,7,0\nTOKEN_END,7,50\n")
    tr = DispatchTracer()
    tr.ingest_jsonl(path)
    tr.ingest_tokens_log(log)
    matched = tr.correlate_tokens()
    assert matched >= 1
    assert tr.spans[0].token_id == 7


def test_phase_events_and_cache(tmp_path):
    events = [
        {"phase": "instr_build", "instruction_hash": "a2_kv8", "ts_ns": 0},
        {"phase": "bo_alloc", "bo_id": 3, "ts_ns": 0},
        {"phase": "bo_alloc", "bo_id": 3, "ts_ns": 1},          # realloc
        {"phase": "bo_free", "bo_id": 3, "ts_ns": 2},
        {"phase": "bo_alloc", "bo_id": 3, "ts_ns": 3},          # after free
        {"phase": "run.start", "pid": 5, "tid": 6, "hwctx_id": 0,
         "kernel": "int4_gemv", "instruction_hash": "a2_kv8", "bo_id": 3, "ts_ns": 10,
         "breakdown_us": {"submit": 5.0, "wait": 20.0, "npu": 30.0,
                          "sync": 5.0, "host": 50.0}},
        {"phase": "run.wait", "pid": 5, "tid": 6, "hwctx_id": 0, "ts_ns": 50},
        {"phase": "instr_cache_hit", "instruction_hash": "a2_kv8", "ts_ns": 60},
    ]
    path = _write(tmp_path, "stream.jsonl", "\n".join(json.dumps(e) for e in events))
    tr = DispatchTracer()
    assert tr.ingest_jsonl(path) == len(events)
    assert len(tr.spans) == 1
    sp = tr.spans[0]
    assert sp.kernel == "int4_gemv" and sp.dur_ns == 40
    assert sp.npu_us == 30.0 and sp.wait_us == 20.0
    st = tr.stats()
    assert st["verdict"] == "HOST_BOUND"   # host+wait dominates npu
    assert st["host_bound_pct"] is not None
    assert st["instruction_cache"]["misses"] >= 1
    assert st["instruction_cache"]["hits"] >= 1
    assert st["bo"]["reallocs"] == 2


def test_chrome_export(tmp_path):
    tr = DispatchTracer()
    tr.add_span(pid=1, tid=2, hwctx_id=0, kernel="int4_gemv", bo_id=3,
                start_ns=1_000, end_ns=9_000, status="ok", instruction_hash="x")
    out = chrome_trace.to_chrome_trace(tr.spans, tr.stats()["instruction_cache"])
    data = json.loads(out)
    assert any(e["ph"] == "X" and e["name"] == "int4_gemv" for e in data)
    xe = next(e for e in data if e["ph"] == "X")
    assert xe["ts"] == 1.0 and xe["dur"] == 8.0
    assert xe["args"]["bo_id"] == 3
    assert any(e["ph"] == "C" for e in data)


def test_host_bound_verdict(tmp_path):
    tr = DispatchTracer()
    tr.add_span(kernel="k", host_us=100.0, npu_us=1.0, start_ns=0, end_ns=1_000_000)
    assert tr.stats()["verdict"] == "HOST_BOUND"


def test_ingest_directory_autodetect(tmp_path):
    _write(tmp_path, "xdna_profile.csv",
           "kernel,submit_us,wait_us,npu_us,sync_us,host_us,status\nk,1,2,3,4,5,ok\n")
    tr = DispatchTracer()
    res = tr.ingest(str(tmp_path))
    assert len(tr.spans) == 1
    assert any("xdna_profile.csv" in k for k in res["ingested"])