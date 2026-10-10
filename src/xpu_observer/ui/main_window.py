"""XPU Observer GUI — tkinter (stdlib) tabbed dashboard.

Six tabs: Dashboard · Processes · NPU Diagnostics · Hooks · MCP/API · Settings.
The UI only reads the shared snapshot (App.collector.snap()); collection runs on the
scheduler thread, so the UI never blocks and never triggers a collection itself.

Hook activation is confirmation-gated: the Hooks tab shows pending requests; Approve
records the user's consent (it never injects a DLL by itself).
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Optional

from ..runtime import App

BG = "#101014"
BG2 = "#181820"
CARD = "#20202b"
FG = "#e6e6e6"
DIM = "#9aa0aa"
ACC = "#3aa0ff"
OK = "#43c26a"
WARN = "#e0a000"
BAD = "#e05a5a"

TABS = ["Dashboard", "Processes", "NPU Diagnostics", "Hooks", "MCP / API", "Settings"]


def _as_list(v: Any) -> list:
    """Tolerate both flat (new) and nested (legacy) raw shapes."""
    if isinstance(v, dict):
        v = v.get("processes") if "processes" in v else next(
            (x for x in v.values() if isinstance(x, list)), [])
    return v if isinstance(v, list) else []


def _npu_block(snap: Any) -> dict:
    raw = snap.raw.get("npu") or {}
    if isinstance(raw, dict) and isinstance(raw.get("npu"), dict):
        raw = raw["npu"]            # legacy nested shape
    return raw if isinstance(raw, dict) else {}


def _fmt(v: Any, digits: int = 1) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


class Sparkline(tk.Canvas):
    """Minimal multi-series line chart from history values (no dependency)."""

    def __init__(self, master: Any, series: dict[str, str], **kw: Any) -> None:
        super().__init__(master, bg=BG2, highlightthickness=0, height=120, **kw)
        self.series = series          # label -> color
        self.data: dict[str, list[float]] = {k: [] for k in series}
        self.bind("<Configure>", lambda _e: self.redraw())

    def push(self, values: dict[str, float]) -> None:
        for k in self.series:
            self.data[k].append(values.get(k, 0.0))
            if len(self.data[k]) > 240:
                self.data[k].pop(0)
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        allv = [v for s in self.data.values() for v in s]
        top = max(1.0, max(allv) if allv else 1.0)
        n = max((len(s) for s in self.data.values()), default=0)
        for label, color in self.series.items():
            s = self.data[label]
            if len(s) < 2:
                continue
            pts = []
            for i, v in enumerate(s):
                x = (w - 1) * (i / max(1, n - 1))
                y = (h - 6) - (h - 12) * (v / top)
                pts += [x, y]
            self.create_line(*pts, fill=color, width=2, smooth=True)
        # legend
        self.create_text(6, 6, anchor="nw", fill=DIM,
                         text=f"0–{top:.0f}  ({n} pts)", font=("Consolas", 8))


class XPUApp:
    def __init__(self, app: App) -> None:
        self.app = app
        self.root = tk.Tk()
        self.root.title("XPU Observer")
        self.root.geometry("920x600")
        self.root.configure(bg=BG)
        self._refreshing = False
        self._caps: Optional[dict] = None       # filled by background thread
        self._hook_rows: list = []
        self._build()
        # Heavy work (capability detection, hook process-scan) runs OFF the Tk thread.
        threading.Thread(target=self._caps_bg, name="ui-caps", daemon=True).start()
        threading.Thread(target=self._hook_bg, name="ui-hooks", daemon=True).start()
        self.root.after(300, self._refresh)

    def _caps_bg(self) -> None:
        try:
            self._caps = self.app.caps
        except Exception:  # noqa: BLE001
            self._caps = {}

    def _hook_bg(self) -> None:
        while True:
            try:
                h = self.app.hooks
                if h is not None:
                    h.detect()
                    self._hook_rows = h.status().get("hooks", [])
            except Exception:  # noqa: BLE001
                pass
            time.sleep(10)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:  # noqa: BLE001
            pass
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG2, foreground=FG, padding=[12, 6])
        style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", ACC)])
        style.configure("Treeview", background=BG2, fieldbackground=BG2, foreground=FG,
                        rowheight=20)
        style.configure("Treeview.Heading", background=CARD, foreground=ACC)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        self.frames = {}
        for name in TABS:
            f = tk.Frame(nb, bg=BG)
            nb.add(f, text=name)
            self.frames[name] = f
        self._build_dashboard(self.frames["Dashboard"])
        self._build_processes(self.frames["Processes"])
        self._build_npu(self.frames["NPU Diagnostics"])
        self._build_hooks(self.frames["Hooks"])
        self._build_mcp(self.frames["MCP / API"])
        self._build_settings(self.frames["Settings"])

        self.status = tk.Label(self.root, text="", bg=BG, fg=DIM, anchor="w")
        self.status.pack(fill="x", padx=8, pady=4)

    def _card(self, parent: Any, row: int, col: int, label: str, color: str) -> tk.Label:
        c = tk.Frame(parent, bg=CARD, bd=0)
        c.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
        tk.Label(c, text=label, bg=CARD, fg=DIM, font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=(6, 0))
        v = tk.Label(c, text="—", bg=CARD, fg=color, font=("Consolas", 18, "bold"))
        v.pack(anchor="w", padx=8, pady=(0, 6))
        return v

    def _build_dashboard(self, f: Any) -> None:
        cards = tk.Frame(f, bg=BG)
        cards.pack(fill="x")
        for i in range(5):
            cards.columnconfigure(i, weight=1)
        self.card_cpu = self._card(cards, 0, 0, "CPU", OK)
        self.card_ram = self._card(cards, 0, 1, "RAM", OK)
        self.card_npu = self._card(cards, 0, 2, "NPU (WDDM)", ACC)
        self.card_igpu = self._card(cards, 0, 3, "iGPU", ACC)
        self.card_gpu = self._card(cards, 0, 4, "GPU 0", WARN)
        self.spark = Sparkline(f, {"cpu%": OK, "ram%": WARN, "npu%": ACC})
        self.spark.pack(fill="both", expand=True, padx=6, pady=6)
        self.dash_extra = tk.Label(f, text="", bg=BG, fg=DIM, anchor="w",
                                   justify="left", font=("Consolas", 9))
        self.dash_extra.pack(fill="x", padx=8, pady=(0, 6))

    def _build_processes(self, f: Any) -> None:
        cols = ("pid", "name", "kind", "cpu", "ram_mb", "gpu_mb", "npu_ctx", "npu_tps")
        self.proc_tree = ttk.Treeview(f, columns=cols, show="headings")
        for c, w in zip(cols, (60, 180, 70, 60, 80, 80, 70, 80)):
            self.proc_tree.heading(c, text=c)
            self.proc_tree.column(c, width=w, anchor="w")
        self.proc_tree.pack(fill="both", expand=True, padx=6, pady=6)

    def _build_npu(self, f: Any) -> None:
        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x", padx=6, pady=6)
        self.npu_head = tk.Label(top, text="", bg=BG2, fg=ACC, anchor="w",
                                 justify="left", font=("Consolas", 10))
        self.npu_head.pack(fill="x", padx=8, pady=6)
        self.npu_ctx = tk.Text(f, height=8, bg=BG2, fg=FG, font=("Consolas", 9))
        self.npu_ctx.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    def _build_hooks(self, f: Any) -> None:
        cols = ("id", "state", "runtime", "target", "reason")
        self.hook_tree = ttk.Treeview(f, columns=cols, show="headings", height=8)
        for c, w in zip(cols, (150, 120, 110, 140, 300)):
            self.hook_tree.heading(c, text=c)
            self.hook_tree.column(c, width=w, anchor="w")
        self.hook_tree.pack(fill="both", expand=False, padx=6, pady=6)
        bar = tk.Frame(f, bg=BG)
        bar.pack(fill="x", padx=6)
        tk.Label(bar, text="Confirmations en attente:", bg=BG, fg=DIM).pack(side="left")
        self._hook_pending_id: Optional[str] = None
        tk.Button(bar, text="Approuver", command=lambda: self._decide_hook(True),
                  bg=CARD, fg=OK).pack(side="right", padx=4)
        tk.Button(bar, text="Refuser", command=lambda: self._decide_hook(False),
                  bg=CARD, fg=BAD).pack(side="right", padx=4)
        self.hook_pending = tk.Listbox(f, bg=BG2, fg=WARN, height=4,
                                       selectbackground=CARD, font=("Consolas", 9))
        self.hook_pending.pack(fill="x", padx=6, pady=4)
        self.hook_log = tk.Text(f, height=4, bg=BG2, fg=DIM, font=("Consolas", 9))
        self.hook_log.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    def _build_mcp(self, f: Any) -> None:
        self.mcp_txt = tk.Text(f, bg=BG2, fg=FG, font=("Consolas", 9))
        self.mcp_txt.pack(fill="both", expand=True, padx=6, pady=6)

    def _build_settings(self, f: Any) -> None:
        box = tk.Frame(f, bg=BG)
        box.pack(anchor="nw", padx=12, pady=12)
        tk.Label(box, text="Intervalle collecte (s):", bg=BG, fg=FG).grid(row=0, column=0, sticky="w")
        self.interval_var = tk.StringVar(value=str(self.app.scheduler._interval))
        tk.Spinbox(box, from_=0.5, to=30, increment=0.5, textvariable=self.interval_var,
                   width=6, command=self._apply_interval).grid(row=0, column=1, padx=8)
        tk.Button(box, text="Exporter snapshot CSV…", command=self._export,
                  bg=CARD, fg=FG).grid(row=1, column=0, columnspan=2, sticky="w", pady=8)
        self.settings_msg = tk.Label(box, text="", bg=BG, fg=OK)
        self.settings_msg.grid(row=2, column=0, columnspan=2, sticky="w")

    # ---------------------------------------------------------------- actions
    def _apply_interval(self) -> None:
        try:
            self.app.scheduler._interval = max(0.5, float(self.interval_var.get()))
        except Exception:  # noqa: BLE001
            pass

    def _export(self) -> None:
        from ..export import csv as _csv  # noqa: PLC0415
        path = f"xpu_snapshot_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(_csv.snapshot_to_csv(self.app.collector.snap()))
            self.settings_msg.config(text=f"exporté → {path}", fg=OK)
        except Exception as exc:  # noqa: BLE001
            self.settings_msg.config(text=f"erreur: {exc}", fg=BAD)

    def _decide_hook(self, approve: bool) -> None:
        h = self.app.hooks
        if h is None:
            return
        sel = self.hook_pending.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(h.pending):
            return
        req = h.pending[idx]
        req["status"] = "approved_by_user" if approve else "denied_by_user"
        self.hook_log.insert("end", f"{time.strftime('%H:%M:%S')} {req['request_id']} "
                                    f"{req['action']} {req['hook']} -> {req['status']}"
                                    f" (aucune injection effectuée)\n")
        h.pending.pop(idx)

    # ---------------------------------------------------------------- refresh
    def _refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            snap = self.app.collector.snap()
            m = snap.metrics

            def val(name: str) -> Any:
                mm = m.get(name)
                if mm is None or mm.value is None:
                    return None
                if isinstance(mm.value, (int, float)):
                    return float(mm.value)
                return mm.value

            self.card_cpu.config(text=f"{_fmt(val('cpu.load_pct'))}%")
            self.card_ram.config(text=f"{_fmt(val('ram.pct'))}%")
            self.card_npu.config(text=f"{_fmt(val('npu.load_pct'))}%")
            self.card_igpu.config(text=f"{_fmt(val('igpu.load_pct'))}%")
            self.card_gpu.config(text=f"{_fmt(val('gpu.0.load_pct'))}%")
            self.spark.push({"cpu%": val("cpu.load_pct") or 0.0,
                             "ram%": val("ram.pct") or 0.0,
                             "npu%": val("npu.load_pct") or 0.0})
            xrt = _npu_block(snap).get("xrt") or {}
            self.dash_extra.config(text=(
                f"NPU state={_fmt(val('npu.display'))}  dispatch/s={_fmt(val('npu.dispatch_s'))}  "
                f"tps_est={_fmt(val('npu.tps_est'))}  kernels={_fmt(val('npu.kernels'),0)}  "
                f"data-tps={_fmt(val('npu.tps_est'))}  xrt={'yes' if xrt.get('available') else 'no'}"))

            self._refresh_processes(snap)
            self._refresh_npu(snap, xrt)
            self._refresh_hooks()
            self._refresh_mcp()

            caps = self._caps or {}
            self.status.config(text=f"ts={snap.ts:.1f}  metrics={len(m)}  "
                                    f"gpus={len(caps.get('gpus', []))}  "
                                    f"npu_present={caps.get('npu', {}).get('present')}")
        except Exception as exc:  # noqa: BLE001
            try:
                self.status.config(text=f"refresh error: {exc}")
            except Exception:  # noqa: BLE001
                pass
        finally:
            self._refreshing = False
            try:
                self.root.after(1200, self._refresh)
            except Exception:  # noqa: BLE001
                pass

    def _refresh_processes(self, snap: Any) -> None:
        procs = _as_list(snap.raw.get("processes"))
        self.proc_tree.delete(*self.proc_tree.get_children())
        for p in procs[:200]:
            self.proc_tree.insert("", "end", values=(
                p.get("pid"), p.get("name"), p.get("kind"),
                _fmt(p.get("cpu_pct")), _fmt(p.get("ram_mb")), _fmt(p.get("gpu_mem_mb")),
                p.get("npu_ctx"), _fmt(p.get("npu_tps"), 2)))

    def _refresh_npu(self, snap: Any, xrt: dict) -> None:
        self.npu_head.config(text=(
            f"device : {xrt.get('device') or '—'}\n"
            f"state  : {_fmt((snap.metrics.get('npu.display') or snap.metrics.get('npu.state')).value if 'npu.display' in snap.metrics else None)}  "
            f"cols : {len(xrt.get('columns') or [])}  "
            f"dispatch/s : {_fmt((snap.metrics.get('npu.dispatch_s') or snap.metrics.get('npu.state')).value if 'npu.dispatch_s' in snap.metrics else None)}"))
        self.npu_ctx.delete("1.0", "end")
        for c in (xrt.get("contexts") or []):
            self.npu_ctx.insert("end", f"ctx{c.get('ctx_id')} pid{c.get('pid')} "
                                      f"[{c.get('name')}] sub={c.get('submissions')} "
                                      f"status={c.get('status')} err={c.get('errors')}\n")
        kernels = _npu_block(snap).get("kernels") or []
        if kernels:
            self.npu_ctx.insert("end", f"\nKernels: {len(kernels)}\n")
            for k in kernels[:20]:
                self.npu_ctx.insert("end", f"  {k.get('kind'):<12} {k.get('name')}\n")

    def _refresh_hooks(self) -> None:
        self.hook_tree.delete(*self.hook_tree.get_children())
        for row in self._hook_rows:            # cached by background thread
            self.hook_tree.insert("", "end", values=(
                row["id"], row["state"], row["runtime"], row["target_dll"],
                row["reason"]))
        self.hook_pending.delete(0, "end")
        h = self.app.hooks
        if h is not None:
            for req in list(h.pending):
                self.hook_pending.insert("end", f"{req['request_id']} [{req['action']}] "
                                                f"{req['hook']} pid={req.get('pid')}")

    def _refresh_mcp(self) -> None:
        if self.mcp_txt.get("1.0", "end").strip():
            return  # fill once
        lines = ["MCP server: stdio (xpu-observer --mcp)", "API: http://127.0.0.1:8766 (--api)", ""]
        try:
            from ..mcp.server import _build_tools  # noqa: PLC0415
            tools = [t["name"] for t in _build_tools()]
            lines.append(f"MCP tools ({len(tools)}):")
            lines += [f"  - {t}" for t in tools]
        except Exception as exc:  # noqa: BLE001
            lines.append(f"(mcp indisponible: {exc})")
        self.mcp_txt.insert("1.0", "\n".join(lines))

    def run(self) -> None:
        self.root.mainloop()


def launch(app: App) -> None:
    XPUApp(app).run()


def _safe_tray(app: App) -> Any:
    try:
        import PIL.Image  # noqa: PLC0415
        return ("tray_available", PIL.Image.new("RGB", (64, 64), (16, 90, 200)))
    except Exception:  # noqa: BLE001
        return None