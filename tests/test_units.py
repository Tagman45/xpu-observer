"""Unit tests — metrics, providers parsers, hooks, diagnostics, exports."""
import os
import tempfile

from xpu_observer.core.metrics import Metric, Snapshot, mk, unavailable


def test_mk_normal():
    m = mk("cpu.load_pct", 42.0, "%", source="psutil")
    assert m.available and m.validity == "ok" and m.value == 42.0


def test_mk_none_is_unavailable():
    m = mk("npu.temp_c", None, "C", source="xrt")
    assert not m.available and m.validity == "unavailable"


def test_unavailable():
    m = unavailable("a", "src")
    assert m.value is None and not m.available


def test_snapshot_roundtrip():
    s = Snapshot()
    s.add(mk("x", 1.0, "") )
    d = s.as_dict()
    assert d["metrics"]["x"]["value"] == 1.0


# ---------------------------------------------------------------- xrt parser
from xpu_observer.providers.xrt import parse_aie_partitions, parse_platform

SAMPLE_PARTITIONS = """
[0] : NPU Compute Accelerator Device
Total Memory Usage: 2478 MB
	 Columns: [0, 1, 2, 3, 4, 5, 6, 7]
      Pid    Context    Submissions  Errors  | Name                        Status      Completions  Gops       Memory    Row/Set      Instructions
  |--------|-----------|-----------|-------| |----------------------------|--------------|-----------|-----------|-----------|-------------|
  |  1042  |     0     |      123   |   0   | | llama-cli                  | Active      | 118        | 0         | 0 KB      | 0x0         |
"""


def test_parse_partitions():
    r = parse_aie_partitions(SAMPLE_PARTITIONS)
    assert r["device"]
    assert r["total_mem_mb"] == 2478.0
    assert r["columns"] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert r["contexts"] and r["contexts"][0]["name"] == "llama-cli"


def test_parse_platform():
    r = parse_platform("Temperature: 41 C\nPower: 4.2 W\nFreq: 900MHz\n")
    assert r["temp_c"] == 41.0 and r["power_w"] == 4.2 and r["freq_mhz"] == 900.0


# ---------------------------------------------------------------- hooks
from xpu_observer.hooks import states
from xpu_observer.hooks.registry import find
from xpu_observer.hooks.compatibility import check


def test_hook_registry_known():
    assert find("xrt_dispatch_tracer") is not None
    assert find("nonexistent") is None


def test_compat_conservative():
    h = find("xrt_dispatch_tracer")
    r = check(h, detected_runtimes=[], target_present=False)
    assert not r["compatible"] and r["state"] == states.UNKNOWN
    r2 = check(h, detected_runtimes=["AMD XRT"], target_present=True)
    assert r2["compatible"] and r2["state"] == states.HOOK_DETECTED


# ---------------------------------------------------------------- diagnostics
from xpu_observer.diagnostics import correlation
from xpu_observer.diagnostics import ctrlcode


def test_timeline_unknown_steps():
    tl = correlation.Timeline()
    tl.add("TOKEN_BEGIN", 1.0, "runtime")
    out = tl.render()
    steps = {e["step"] for e in out}
    assert "TOKEN_BEGIN" in steps and "TOKEN_END" in steps
    end = next(e for e in out if e["step"] == "TOKEN_END")
    assert end["present"] is False and end["ts_m"] is None


def test_ctrlcode_scan(tmp_path):
    for n, sz in (("flm_ctrl_0001.bin", 100), ("flm_ctrl_0002.bin", 200)):
        p = tmp_path / n
        p.write_bytes(b"x" * sz)
    r = ctrlcode.scan_ctrlcodes(str(tmp_path))
    assert r["files"] == 2 and r["total_bytes"] == 300
    assert ctrlcode.scan_ctrlcodes(str(tmp_path / "missing"))["files"] == 0


# ---------------------------------------------------------------- exports
def test_csv_export():
    from xpu_observer.export import csv as c
    s = Snapshot()
    s.add(mk("a", 1.5, "unit", "src"))
    out = c.snapshot_to_csv(s)
    assert "a" in out and "1.5" in out


def test_history_csv():
    from xpu_observer.export import csv as c
    items = [{"ts": 1.0, "metrics": {"cpu.load_pct": {"value": 10.0}}},
             {"ts": 2.0, "metrics": {"cpu.load_pct": {"value": 11.0}}}]
    out = c.history_to_csv(items)
    assert "cpu.load_pct" in out
    assert out.count("\n") == 3


def test_collector_raw_not_double_nested():
    """Regression: raw must expose provider keys at top level (no nested wrapper)."""
    from xpu_observer.core.collector import Collector
    col = Collector()
    snap = col.collect_once(force_slow=True)
    raw = snap.raw
    # npu provider must expose its own subkeys (kernels/xrt), not {"npu": {...}}
    if "npu" in raw:
        assert isinstance(raw["npu"], dict)
        assert "kernels" in raw["npu"] or "xrt" in raw["npu"]
        # a nested 'npu' key inside raw["npu"] would be the double-nesting bug
        assert "npu" not in raw["npu"]
    if "processes" in raw:
        assert isinstance(raw["processes"], list)