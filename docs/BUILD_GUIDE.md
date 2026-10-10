# Build Guide

Two supported builds: **editable dev install** (fast) and **PyInstaller single EXE**
(distribution). PySide6 is NOT required — the default GUI is tkinter (stdlib).

## Dev install

```powershell
cd xpu-observer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
pytest tests -q
```

## PyInstaller single file

```powershell
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --name xpu-observer `
  --paths src src\xpu_observer\main.py
```

The binary is not 195 KB: it bundles Python + psutil + mcp. Expect a few MB. We do not
claim otherwise.

> Hook catalog is embedded data (no external DLL bundled). A system tray needs
> `pip install -e .[tray]` before building.

## GitHub Actions

`.github/workflows/release.yml` builds the EXE on `windows-latest`, runs pytest and
uploads the artifact. See below.

## Verification checklist

- [ ] `python -m compileall src tests` green
- [ ] `pytest tests -q` green (MCP e2e speaks real pipes)
- [ ] `xpu-observer --once` prints a valid snapshot on a machine WITH an NPU
- [ ] `xpu-observer --once` works on a machine WITHOUT an NPU (npU metrics go `unavailable`)
- [ ] `xpu-observer --api` → `Invoke-RestMethod http://127.0.0.1:8766/metrics`