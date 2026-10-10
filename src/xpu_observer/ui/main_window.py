"""tkinter dashboard — reads the shared snapshot (never blocks a collection).

The UI only consumes App.collector.snap(); collection happens on the scheduler thread.
Also surfaces pending hook confirmation requests (approve/deny); approving NEVER injects
— it only records the user's consent for a follow-up instrumentation step.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Optional

from ..runtime import App

_KEY_HINTS = ("npu.", "igpu.", "cpu.", "ram.", "gpu.0.load", "processes.npu")


class Dashboard:
    def __init__(self, app: App) -> None:
        self.app = app
        self.root = tk.Tk()
        self.root.title("XPU Observer")
        self.root.geometry("640x480")
        self.root.configure(bg="#101010")
        self._tree = ttk.Treeview(self.root, columns=("val", "unit", "src", "valid"),
                                  show="headings", height=18)
        for c, w in (("val", 90), ("unit", 70), ("src", 160), ("valid", 90)):
            self._tree.heading(c, text=c)
            self._tree.column(c, width=w, anchor="w")
        self._tree.pack(fill="both", expand=True, padx=4, pady=4)
        self._status = tk.Label(self.root, text="", bg="#101010", fg="#bbb", anchor="w")
        self._status.pack(fill="x", padx=6)
        self._pending_txt = tk.Text(self.root, height=4, bg="#101010", fg="#e0a000")
        self._pending_txt.pack(fill="x", padx=6, pady=(0, 4))

    def _refresh(self) -> None:
        snap = self.app.collector.snap()
        rows = [(m.name, m.value, m.unit, m.source, m.validity)
                for m in snap.metrics.values()
                if any(m.name.startswith(k) for k in _KEY_HINTS) or m.validity == "error"]
        rows.sort(key=lambda r: r[0])
        self._tree.delete(*self._tree.get_children())
        for r in rows:
            val = "" if r[1] is None else (f"{r[1]:.2f}" if isinstance(r[1], float) else str(r[1]))
            self._tree.insert("", "end", values=(r[0], val, r[2], r[3], r[4]))
        self._status.config(text=f"ts={snap.ts:.1f} metrics={len(snap.metrics)} "
                                 f"gpus={len(self.app.caps.get('gpus', []))} "
                                 f"npu={self.app.caps.get('npu', {}).get('present')} "
                                 f"xrt={bool(self.app.caps.get('tools', {}).get('xrt_smi'))}")
        self._refresh_pending()
        self.root.after(1500, self._refresh)

    def _refresh_pending(self) -> None:
        h = self.app.hooks
        if h is None or not h.pending:
            self._pending_txt.delete("1.0", "end")
            self._pending_txt.insert("1.0", "hooks: aucune confirmation en attente")
            return
        self._pending_txt.delete("1.0", "end")
        for req in h.pending:
            self._pending_txt.insert("end",
                f"{req['request_id']} [{req['action']}] {req['hook']}"
                f" pid={req.get('pid')} - {req['status']}\n")

    def run(self) -> None:
        self._refresh()
        self.root.mainloop()


def launch(app: App) -> None:
    Dashboard(app).run()


def _safe_tray(app: App) -> Any:
    """Optional tray; None if pystray unavailable (never fails the app)."""
    try:
        import PIL.Image  # noqa: PLC0415
        icon = PIL.Image.new("RGB", (64, 64), (16, 90, 200))
        return ("tray_available", icon)
    except Exception:  # noqa: BLE001
        return None