"""Import smoke tests — every module imports and exposes its entry points."""
import importlib

MODULES = [
    "xpu_observer.core.util",
    "xpu_observer.core.metrics",
    "xpu_observer.core.capabilities",
    "xpu_observer.core.event_bus",
    "xpu_observer.core.collector",
    "xpu_observer.core.scheduler",
    "xpu_observer.providers.cpu",
    "xpu_observer.providers.ram",
    "xpu_observer.providers.gpu",
    "xpu_observer.providers.npu",
    "xpu_observer.providers.pdh",
    "xpu_observer.providers.xrt",
    "xpu_observer.providers.processes",
    "xpu_observer.providers.etw",
    "xpu_observer.hooks.registry",
    "xpu_observer.hooks.compatibility",
    "xpu_observer.hooks.manager",
    "xpu_observer.hooks.verifier",
    "xpu_observer.hooks.deploy",
    "xpu_observer.diagnostics.correlation",
    "xpu_observer.diagnostics.dispatch",
    "xpu_observer.diagnostics.ctrlcode",
    "xpu_observer.diagnostics.dispatch_trace",
    "xpu_observer.export.csv",
    "xpu_observer.export.json",
    "xpu_observer.export.chrome_trace",
    "xpu_observer.api.server",
    "xpu_observer.mcp.server",
    "xpu_observer.runtime",
    "xpu_observer.main",
]


def test_imports():
    for m in MODULES:
        importlib.import_module(m)


def test_main_entry():
    from xpu_observer import main
    assert callable(main.main)


def test_version():
    from xpu_observer import __version__
    assert __version__