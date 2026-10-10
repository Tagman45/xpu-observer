"""PDH provider — WDDM 'GPU Engine' counters (pdh.dll, ctypes only).

IMPORTANT (documented limitation): PDH reports activity *declared to WDDM*, which is
NOT the same as exact physical occupancy of XDNA2 compute units. Consumers must treat
`npu.load_pct` from PDH as an estimate whose source is 'pdh:wddm'.
"""
from __future__ import annotations

import ctypes
import re
from typing import Any

from ..core.metrics import Metric, mk


class PDH:
    """Enumerate GPU Engine instances, classify LUIDs by engine signature, read util.

    Classification:
      - NPU:   every engine of the LUID is Compute
      - dGPU NVIDIA: has OFA / VideoEncode / JPEG_Decode engines
      - other: remainder (integrated AMD/iGPU, other)
    Instances appear/disappear with processes -> periodic rebuild.
    """
    PDH_MORE_DATA = 0x800007D2
    PDH_FMT_DOUBLE = 0x00000200
    REBUILD_EVERY = 20

    def __init__(self) -> None:
        self.ok = False
        self._q = ctypes.c_void_p(0)
        self._handles: dict[str, ctypes.c_void_p] = {}
        self._tags: dict[str, str] = {}
        self._n = 0
        try:
            self._setup()
            self._rebuild()
            self.ok = bool(self._handles)
        except Exception:  # noqa: BLE001
            self.ok = False

    @staticmethod
    def _setup() -> None:
        pdh = ctypes.windll.Pdh
        pdh.PdhOpenQueryW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                      ctypes.POINTER(ctypes.c_void_p)]
        pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                              ctypes.c_ulong,
                                              ctypes.POINTER(ctypes.c_void_p)]
        pdh.PdhEnumObjectItemsW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_ulong, ctypes.c_ulong]
        pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        pdh.PdhGetFormattedCounterValue.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(PDH_FMT_COUNTERVALUE)]

    class PDH_FMT_COUNTERVALUE(ctypes.Structure):
        _fields_ = [("CStatus", ctypes.c_ulong), ("dwValue", ctypes.c_ulonglong)]

    def _rebuild(self) -> None:
        pdh = ctypes.windll.Pdh
        if self._q:
            pdh.PdhCloseQuery(self._q)
        self._q = ctypes.c_void_p(0)
        self._handles.clear()
        self._tags.clear()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._q)) != 0:
            return
        cc = ctypes.c_ulong(0)
        ci = ctypes.c_ulong(0)
        rc = pdh.PdhEnumObjectItemsW(None, None, "GPU Engine", None,
                                     ctypes.byref(cc), None,
                                     ctypes.byref(ci), 1, 0) & 0xFFFFFFFF
        if rc not in (0, self.PDH_MORE_DATA) or ci.value == 0:
            self.ok = False
            return
        bufc = ctypes.create_unicode_buffer(cc.value + 2)
        bufi = ctypes.create_unicode_buffer(ci.value + 2)
        if pdh.PdhEnumObjectItemsW(None, None, "GPU Engine", bufc,
                                   ctypes.byref(cc), bufi,
                                   ctypes.byref(ci), 1, 0) != 0:
            self.ok = False
            return
        raw = ctypes.string_at(ctypes.cast(bufi, ctypes.c_void_p), ctypes.sizeof(bufi))
        insts = [s for s in raw.decode("utf-16-le", "ignore").split("\x00") if s]
        luid_eng: dict[str, set] = {}
        for inst in insts:
            m = re.search(r"luid_0x[0-9a-fA-F]+_(0x[0-9a-fA-F]+)_phys_\d+_eng_\d+_(.*)$", inst)
            if m:
                luid_eng.setdefault(m.group(1), set()).add(m.group(2).lower())
        cls = {}
        for luid, engrains in luid_eng.items():
            if engrains and all(("compute" in e) for e in engrains):
                cls[luid] = "npu"
            elif any(("ofa" in e) or ("video_encode" in e) or ("jpeg_decode" in e)
                     for e in engrains):
                cls[luid] = "dgpu"
            else:
                cls[luid] = "igpu"
        for inst in insts:
            m = re.search(r"(luid_0x[0-9a-fA-F]+_(0x[0-9a-fA-F]+)_phys_\d+)_eng_\d+_(.*)$", inst)
            if not m:
                continue
            prefix, luid, eng = m.group(1), m.group(2), m.group(3)
            tag = cls.get(luid)
            if not tag:
                continue
            counter = r"\GPU Engine(*)\Utilization Percentage"
            path = f"{counter[: counter.index('*')]}{prefix}_eng_{eng}{counter[counter.index('*') + 1:]}"
            try:
                h = ctypes.c_void_p(0)
                if pdh.PdhAddEnglishCounterW(self._q, path, 0, ctypes.byref(h)) == 0 and h:
                    self._handles.setdefault(tag, []).append(h)
                    self._tags[path] = tag
            except Exception:  # noqa: BLE001
                pass
        pdh.PdhCollectQueryData(self._q)
        self.ok = bool(self._handles)

    def read(self) -> dict[str, float]:
        """Return {npu: pct, igpu: pct, dgpu: pct} utilizations (0..100). Sums engines."""
        out = {"npu": 0.0, "igpu": 0.0, "dgpu": 0.0}
        if not self.ok:
            return out
        self._n += 1
        if self._n % self.REBUILD_EVERY == 0:
            self._rebuild()
        pdh = ctypes.windll.Pdh
        pdh.PdhCollectQueryData(self._q)
        for tag, hdls in self._handles.items():
            total = 0.0
            found = 0
            for h in hdls:
                val = self.PDH_FMT_COUNTERVALUE()
                typ = ctypes.c_ulong(0)
                if pdh.PdhGetFormattedCounterValue(h, self.PDH_FMT_DOUBLE,
                                                   ctypes.byref(typ),
                                                   ctypes.byref(val)) == 0:
                    try:
                        v = ctypes.cast(ctypes.addressof(val),
                                        ctypes.POINTER(ctypes.c_double)).contents.value
                    except Exception:  # noqa: BLE001
                        continue
                    if v is not None and v >= 0:
                        total += v
                        found += 1
            if tag in out and found:
                out[tag] = min(100.0, total)
        return out

    def close(self) -> None:
        try:
            ctypes.windll.Pdh.PdhCloseQuery(self._q)
        except Exception:  # noqa: BLE001
            pass
        self.ok = False


_pdh_instance: PDH | None = None


def get_pdh() -> PDH:
    global _pdh_instance
    if _pdh_instance is None:
        _pdh_instance = PDH()
    return _pdh_instance


def collect() -> tuple[list[Metric], dict[str, Any]]:
    p = get_pdh()
    raw = p.read()
    m = [
        mk("npu.load_pct", raw["npu"], "%", source="pdh:GPU Engine",
           note="WDDM-declared activity, not physical XDNA2 occupancy"),
        mk("igpu.load_pct", raw["igpu"], "%", source="pdh:GPU Engine"),
        mk("dgpu.load_pct", raw["dgpu"], "%", source="pdh:GPU Engine"),
    ]
    return m, {"pdh": raw}