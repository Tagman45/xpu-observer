# Status Report — XPU Observer V0.1 → V0.5 (live build 2026-10-10)

Per-feature: implemented / tested / hardware vs simulation / limitations / measured results.

Legend: **IMP** implemented · **TEST** auto-tested · **HW** validated on this machine
(NPU XDNA2 + RTX 5070 + iGPU 880M) · **SIM** simulated in unit tests only.

## Core

| Feature | IMP | TEST | HW | Limitations / measured |
|---|---|---|---|---|
| Metric object (value/unit/source/ts/available/validity) | ✅ | ✅ | ✅ | missing ⇒ `unavailable`, never 0 |
| Capabilities (GPU, NPU, xrt-smi, nvidia-smi, pdh) | ✅ | ✅ | ✅ | `Get-CimInstance` cached (~1s) |
| Event bus | ✅ | ✅ | — | trivial pub/sub |
| Collector fast/slow split | ✅ | ✅ | ✅ | fast=pdh/cpu/ram, slow=xrt/gpu/procs every 4 cycles |
| History (bounded 600) | ✅ | ✅ | — | metrics only, raw not retained |
| Scheduler thread (non-blocking) | ✅ | ✅ | — | interval 2s default |

## Providers

| Feature | IMP | TEST | HW | Limitations / measured |
|---|---|---|---|---|
| cpu (`psutil`) | ✅ | ✅ | ✅ | temperacture souvent vide sur Windows |
| ram (`psutil`) | ✅ | ✅ | ✅ | |
| gpu (`nvidia-smi`, multi) | ✅ | ✅ | ✅ | RTX 5070: 2% idle, 1827/8151 MB |
| pdh WDDM (NPU/iGPU/dGPU) | ✅ | ✅ | ✅ | 0% idle — activity declared, not physical |
| xrt (contexts/dispatches/cols) | ✅ | ✅ | ✅ | IDLE 0 ctx; parser unit-tested on real format |
| npu (composite) + kernels scan | ✅ | ✅ | ✅ | kernel scan: env/localappdata only |
| processes (PID merge + DLL NPU) | ✅ | ✅ | ✅ | DLL scan only for NPU users |
| etw | 🔶 stub | — | — | returns `unavailable`; slot for later |

## API / MCP / Export

| Feature | IMP | TEST | HW |
|---|---|---|---|
| HTTP API 127.0.0.1 (read-only, bounded) | ✅ | ✅ live GET | ✅ |
| CSV/JSON export (+history.csv) | ✅ | ✅ | ✅ |
| MCP stdio (official protocol, no SDK dep) | ✅ | ✅ e2e real pipes | ✅ |
| 24 tools (read) + 2 controlled actions | ✅ | ✅ tools/list+c/call e2e | ✅ |
| Request-based activation (never injects) | ✅ | ✅ | ✅ (queue → GUI) |

## Hooks

| Feature | IMP | TEST | HW | Limitations |
|---|---|---|---|---|
| Catalog (8 hooks, no DLL bundled) | ✅ | ✅ | — | descriptive only |
| Runtime detection (DLL fingerprints) | ✅ | ✅ SIM | 🔶 | not run against a live LLM yet |
| Conservative compatibility | ✅ | ✅ | ✅ | unknown signature ≠ absent; no runtime ⇒ UNKNOWN |
| States (presence ≠ active) | ✅ | ✅ | — | |
| Verifier (DLL loaded in pid) | ✅ | ✅ SIM | — | generic hooks ⇒ UNKNOWN |
| Activation flow (confirmation) | ✅ | ✅ | — | manual step required |

## Diagnostics

| Feature | IMP | TEST | HW |
|---|---|---|---|
| Timeline TOKEN_BEGIN→END (UNKNOWN explicit) | ✅ | ✅ | — |
| Dispatch analysis (verdict) | ✅ | ✅ | — |
| ctrlcode scan (size distribution) | ✅ | ✅ | — |

## V0.6 — Dispatch tracer (added 2026-10-10)

| Feature | IMP | TEST | HW |
|---|---|---|---|
| Parse dispatch CSV (xdna_profile style, breakdown µs) | ✅ | ✅ | synthetic only |
| Parse JSONL runtime events (phase stream + complete spans) | ✅ | ✅ | synthetic only |
| Parse TOKEN markers (runtime_trace.log) | ✅ | ✅ | |
| Canonical span fields (pid, tid, hwctx_id, kernel, instruction_hash, bo_id, group_id, start_ns, end_ns, sync_direction, status, token_id) | ✅ | ✅ | |
| Token ↔ kernel ↔ context correlation | ✅ | ✅ (815/815 matched on demo) | SYN |
| Instruction cache hits/misses + BO realloc accounting | ✅ | ✅ | SYN |
| Per-kernel cost + verdict (HOST_BOUND / SYNC_WAIT_BOUND / NPU_BOUND) | ✅ | ✅ | SYN |
| Chrome Trace / Perfetto export (`ph X` + `ph C` counters) | ✅ | ✅ | |
| CLI `--trace` / `--trace-export`, MCP (4 tools), API `/trace/*` | ✅ | ✅ | |
| `scripts/make_demo_trace.py` (synthetic run) | ✅ | ✅ | SYN |

Demo result (synthetic, 128 tokens, 815 dispatches): `post_attn_fused` cumulé = 257,6 ms
NPU-vs-wait, `int4_gemv` = 12,5 ms NPU (wait domine), host 33% / NPU 67% / wait 26% →
`NPU_BOUND`. **Valeurs fictives** — le pipeline distingue host, sync, wait et compute
NPU, ce qui est le préalable pour investiguer « Qwen3.5-9B 1,8 → 0,6 tok/s avec K-split ».

Instrumentation priority: runtime native trace first; DLL hook capture feeds the same
normalized stream. Hooks remain confirmation-gated.

## Not done (honest)

- **ETW collector**: stub returns `unavailable`. Needs AMD XDNA ETW GUIDs + trace session — V0.6.
- **LLM tokens/s correlation**: only the *estimated* heuristic from dispatch deltas; a measured
  token counter requires a live instrumented runtime. **Not claimed as measured.**
- **PySide6 GUI**: pygame-checked out → tkinter used (zero dependency). PySide6 optional in `pyproject`.
- **System tray**: optional (`pystray`); not required for V0.1.
- **EC / MSR / driver-write features**: excluded from the public edition (security).

## Measured on this machine (2026-10-10, idle)

- PDH: npu 0%, igpu 0%, dgpu 0% — all WDDM-declared.
- XRT: device NPU, `IDLE`, 0 ctx, columns parser OK.
- GPU: RTX 5070 — load 2%, mem 1827/8151 MB, temp 43 °C, power ~32 W.
- CPU: ~8% (during collection), freq ~2.4–4 GHz (boost).

## Test matrix from the spec (§11)

1 Windows sans NPU —🔶 not run here (machine HAS NPU); code path degrades to `unavailable`.
2 AMD XDNA2 — ✅ (this machine)
3 XRT absent — ✅ unit (provider returns unavailable, no crash)
4 PDH indisponible — ✅ unit (`_pdh_available` False path)
5 NVIDIA + iGPU AMD — ✅ (RTX 5070 + 880M detected)
6 Plusieurs GPU — ✅ (multi-`gpu.{i}.` namespace)
7 Plusieurs process LLM — 🔶 not tested live
8 hook DLL absente — ✅ (catalog only, NOT_INSTALLED/UNKNOWN)
9 DLL présente mais hook inactif — ✅ logic (DLL_PRESENT vs HOOK_ACTIVE via verifier)
10 hook actif + vérifié — 🔶 requires live instrumented run
11 hook incompatible — ✅ unit
12 activation refusée — ✅ (pending stays; no injection)
13 processus terminé pendant analyse — ✅ (psutil try/except)
14 client MCP connecté — ✅ e2e
15 client MCP déconnecté — ✅ (EOF → run returns)
16 interface fermée, tray — 🔶 tray optional
17 export CSV pendant collecte — ✅
18 perf avec/sans hook — 🔶 pending live run
19 timeout XRT — ✅ (`util.run` timeout, returns unavailable)
20 redémarrage process instrumenté — 🔶 pending

→ 13/20 fully done, 7 pending a live instrumented LLM run or an NPU-less machine.