"""Hook registry — declarative catalog of known instrumentation hooks.

This catalog describes hooks and their compatibility rules. It does NOT bundle any
DLL: activation requires an explicitly provided, user-approved DLL path plus an
in-process confirmation. Unknown third-party signatures are never assumed absent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Known runtime DLL fingerprints (used by discovery, no hardcoded machine paths).
RUNTIME_DLLS: dict[str, tuple[str, ...]] = {
    "AMD XRT": ("xrt_coreutil.dll", "xrt_core.dll"),
    "llama.cpp": ("ggml.dll", "llama.dll", "ggml-xdna.dll"),
    "ONNX Runtime": ("onnxruntime.dll", "onnxruntime_providers_shared.dll"),
    "DirectML": ("directml.dll", "directml_x64.dll"),
    "FastFlowLM": ("q4_npu_express.dll", "*_npu.dll"),
}


@dataclass
class Hook:
    id: str
    name: str
    target_dll: str          # DLL in which instrumentation hooks
    runtime: str             # runtime family name
    arch: str = "x64"
    privilege: str = "user"  # user | admin
    risk: str = "low"        # observed slowdown risk if active
    instruments: list[str] = field(default_factory=list)
    verifiable: str = ""     # how to confirm it is actually active
    # procedure strings (text only; the binary is never bundled)
    activation: str = ""
    deactivation: str = ""
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "target_dll": self.target_dll,
            "runtime": self.runtime, "arch": self.arch, "privilege": self.privilege,
            "risk": self.risk, "instruments": self.instruments,
            "verifiable": self.verifiable, "activation": self.activation,
            "deactivation": self.deactivation, "notes": self.notes,
        }


CATALOG: list[Hook] = [
    Hook(
        id="xrt_dispatch_tracer", name="XRT Dispatch Tracer",
        target_dll="xrt_coreutil.dll", runtime="AMD XRT",
        instruments=["run::start", "run::submit", "run::sync"],
        verifiable="DLL de trace chargee dans le process + compteur de submissions croissant",
        activation="injection LoadLibrary d'un module de trace (confirmation UI requise)",
        deactivation="dechargement du module + redemarrage du process (ou signal) sinon signaler redemarrage requis",
        notes="Peut ajouter un overhead host sur submit/wait; corriger avec le hook manager.",
    ),
    Hook(
        id="xdna_ctrlcode", name="XDNA ctrlcode tracer",
        target_dll="<runtime npa>", runtime="FastFlowLM/ggml-xdna",
        instruments=["TXN ctrlcode bytes", "buffer writes", "map/sync"],
        verifiable="journal TXN écrit + dump ctrlcodes",
        activation="injection du hook (p.ex. hook_v48_light.dll) - confirmee en UI",
        deactivation="retirer le hook; redemarrage du process si impossible",
        notes="Hook specifique runtime ggml-xdna (hors edition publique: spec catalogue).",
    ),
    Hook(
        id="bo_allocation", name="BO allocation tracer",
        target_dll="xrt_coreutil.dll", runtime="AMD XRT",
        instruments=["bo_alloc", "bo_free"],
        verifiable="compteur allocation croissant dans le log",
        activation="injection d'un module de trace BO (confirmation UI requise)",
        deactivation="dechargement + redemarrage si necessaire",
    ),
    Hook(
        id="bo_write", name="BO write tracer",
        target_dll="xrt_coreutil.dll", runtime="AMD XRT",
        instruments=["bo_write"],
        verifiable="log des ecritures BO",
        activation="injection module trace bo_write (confirmation UI requise)",
        deactivation="dechargement + redemarrage si necessaire",
    ),
    Hook(
        id="buffer_map_sync", name="Buffer map/sync tracer",
        target_dll="xrt_coreutil.dll", runtime="AMD XRT",
        instruments=["map", "sync"],
        verifiable="log map/sync",
        activation="injection module trace sync (confirmation UI requise)",
        deactivation="dechargement + redemarrage si necessaire",
    ),
    Hook(
        id="runlist", name="Runlist tracer",
        target_dll="xrt_coreutil.dll", runtime="AMD XRT",
        instruments=["runlist submit"],
        verifiable="log des runlists",
        activation="injection module trace runlist (confirmation UI requise)",
        deactivation="dechargement + redemarrage si necessaire",
    ),
    Hook(
        id="dispatch_timing", name="Dispatch timing",
        target_dll="multi", runtime="any",
        instruments=["dispatches", "durées submit/wait/npu/sync"],
        verifiable="CSV de profiling par kernel",
        activation="variables d'env du runtime + hook de trace (confirmation UI requise)",
        deactivation="retirer variables d'env; redemarrage du process",
    ),
    Hook(
        id="token_scope", name="Token scope correlation",
        target_dll="runtime", runtime="any",
        instruments=["TOKEN_BEGIN", "TOKEN_END"],
        verifiable="marqueurs TOKEN_* dans le journal runtime",
        activation="trace runtime togglée (confirmation UI requise)",
        deactivation="desactiver la trace",
    ),
]


def find(hook_id: str) -> Optional[Hook]:
    for h in CATALOG:
        if h.id == hook_id:
            return h
    return None


def as_list() -> list[dict[str, Any]]:
    return [h.as_dict() for h in CATALOG]