"""UI construction smoke test — builds all tabs without entering mainloop."""
import tkinter as tk

import pytest

from xpu_observer.runtime import App
from xpu_observer.ui.main_window import XPUApp, TABS


def test_ui_constructs_all_tabs():
    try:
        ui = XPUApp(App())
    except tk.TclError as exc:      # no display available
        pytest.skip(f"no display: {exc}")
    assert set(ui.frames.keys()) == set(TABS)
    ui.root.update()                # force widget realisation
    ui.root.destroy()