"""UI construction smoke test — builds all tabs without entering mainloop."""
import tkinter as tk

import pytest

from xpu_observer.runtime import App
from xpu_observer.ui.main_window import XPUApp, TABS


def _display_ok() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _display_ok(), reason="no display")
def test_ui_constructs_all_tabs():
    app = App()
    ui = XPUApp(app)
    assert set(ui.frames.keys()) == set(TABS)
    ui.root.update()          # force widget realisation
    ui.root.destroy()