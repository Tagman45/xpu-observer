"""Generate a synthetic dispatch trace to exercise XPU Observer's tracer without hardware.

Simulates a Qwen3.5-9B-style run over `n_tokens` tokens with per-kernel host/NPU
breakdown, instruction cache (cache key per (kernel, shape)) and BO alloc/free/rewrite.
NOT a hardware measurement — use it to validate the pipeline end to end:

    python scripts/make_demo_trace.py out/
    xpu-observer --trace out --trace-export out/trace.chrome.json
"""
from __future__ import annotations

import json
import os
import random
import sys

KERNELS = {
    # kernel: (npu_us, host_pre_us, wait_us, sync_us) — plausible order of magnitude
    "int4_gemv":        (60.0, 25.0, 400.0, 30.0),   # host/wait-heavy → HOST_BOUND risk
    "post_attn_fused":  (1400.0, 30.0, 250.0, 60.0),
    "flowkv_per_head":  (900.0, 20.0, 200.0, 50.0),
    "ffn16_2mm":        (700.0, 35.0, 300.0, 55.0),
}


def main(out_dir: str, n_tokens: int = 64, seed: int = 7) -> None:
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(seed)
    events: list[dict] = []
    t_ns = 0
    token_id = 0
    cache: dict[str, bool] = {}
    bo_alloc: dict[int, bool] = {}
    next_bo = 0
    for _ in range(n_tokens):
        token_id += 1
        events.append({"phase": "TOKEN_BEGIN", "token_id": token_id, "ts_ns": t_ns})
        for _ in range(rng.randint(4, 9)):
            kernel = rng.choice(list(KERNELS))
            npu_us, host_us, wait_us, sync_us = KERNELS[kernel]
            cache_key = f"{kernel}_sl={rng.choice([128, 256, 512])}_h4"
            if cache_key not in cache:
                events.append({"phase": "instr_build", "instruction_hash": cache_key,
                               "ts_ns": t_ns})
                cache[cache_key] = True
            else:
                events.append({"phase": "instr_cache_hit", "instruction_hash": cache_key,
                               "ts_ns": t_ns})
            if not bo_alloc or rng.random() < 0.2:
                next_bo += 1
                events.append({"phase": "bo_alloc", "bo_id": next_bo, "ts_ns": t_ns})
                bo_alloc[next_bo] = True
                if next_bo > 1:
                    events.append({"phase": "bo_free", "bo_id": next_bo - 1, "ts_ns": t_ns})
                    bo_alloc[next_bo - 1] = False
            bo = max(bo_alloc, key=lambda b: bo_alloc[b], default=next_bo)
            pid = 1042
            tid = 7890 + rng.randint(0, 3)
            start = t_ns
            dur_ns = int((host_us + wait_us + npu_us + sync_us) * 1000)
            end = start + dur_ns
            events.append({"phase": "run.start", "pid": pid, "tid": tid, "hwctx_id": 0,
                           "kernel": kernel, "instruction_hash": cache_key, "bo_id": bo,
                           "group_id": 0, "ts_ns": start,
                           "breakdown_us": {"submit": host_us * 0.4,
                                            "wait": wait_us,
                                            "npu": npu_us,
                                            "sync": sync_us,
                                            "host": host_us * 0.6}})
            events.append({"phase": "run.wait", "pid": pid, "tid": tid, "hwctx_id": 0,
                           "ts_ns": end})
            t_ns = end
        t_ns += rng.randint(200, 800) * 1000
        events.append({"phase": "TOKEN_END", "token_id": token_id, "ts_ns": t_ns})
    path = os.path.join(out_dir, "dispatch_trace.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
    print(f"demo trace -> {path} ({len(events)} events, {n_tokens} tokens)")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo_trace")
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 64
    main(out, n_tokens=n)