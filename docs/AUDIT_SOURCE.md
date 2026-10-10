# Audit du code source existant (référence : `Documents/nitro`)

But : extraire les fonctionnalités réutilisables pour XPU Observer, en **supprimant toute
dépendance au PC d'origine** (Acer, Nitro, Radeon 880M, RTX 5070, chemins absolus).

Statuts : **REUSE** = repris quasi tel quel (adapté portable) · **ADAPT** = logique reprise,
dépendances à retirer · **EXCLUDE** = hors périmètre public / spécifique machine.

## Collecte NPU (`acer_nitro_app.py`)

| Fonction | Statut | Notes portabilité |
|---|---|---|
| `query_xrt_smi` | ADAPT | Garde le parsing xrt-smi. `XRT_SMI` en dur → découverte via `shutil.which` + `${SystemRoot}/System32/AMD`. Subprocess bloquant → isoler dans provider. |
| `scan_npu_kernels` / `_npu_kernel_dirs` | ADAPT | Garde le scan `.xclbin`. `GGML_XDNA_CACHE_DIR` + `%LOCALAPPDATA%/ggml-xdna/xclbin` sont déjà génériques ; retirer les chemins `E:\`. |
| `PDHMonitor` | REUSE | `pdh.dll` pur, générique. La classification LUID par signature (NVIDIA/NPU/iGPU) est portable. Aucune dépendance machine. |
| `MetricsCollector` | ADAPT | Garde le split fast/slow + le verrou. Retirer la persistance `HKCU\Environment` du profileur (effet de bord global → non désiré dans un outil public). |
| `_collect_xrt` | ADAPT | Garde le calcul dispatches/s, ratio, tokens/s. Détection runtime par DLL = heuristique → à marquer comme telle. |
| `_collect_pdh` | REUSE | 2 lignes, générique. |
| `_collect_processes` | ADAPT | Fusion psutil + nvidia-smi + xrt. Retirer `npu_dlls` spécifiques si absents. |
| `_collect_kernels` | REUSE | Générique (lecture seule du cache). |
| `_build_npu_trace` | ADAPT | Garde le principe d'événements de transition. Durées internes DLL restent des hypothèses (documenté). |
| `_collect_token_scope` | REUSE | Lecture TOKEN_BEGIN/END — portable. |
| `_collect_cpu_ram` | ADAPT | psutil OK. RAPL via `ECController.read_rapl_watts` dépend de WinRing0 → **EXCLUDE** du cœur, optionnel. |
| `_collect_optimus` | ADAPT | Garde `nvidia-smi display_active` + `OptimusController.get_mux_mode` → MUX est spécifique Acer → à généraliser en simple « quel GPU pilote l'affichage ». |

## Hooks (`hook_manager.py`, `v11`, `v14`, + `hook_*_capture.py`)

| Élément | Statut | Notes |
|---|---|---|
| `hook_manager.inject` (CreateRemoteThread+LoadLibraryA) | ADAPT | Réutilisable mais **jamais automatique** : confirmation obligatoire, PID autorisé seulement. |
| `hook_manager.find_process` / `inject_auto` | ADAPT | Générique. Cible par nom de process. |
| `acer_nitro_app_v11._hook_status` / `_hook_ctrlcodes` | ADAPT | Parsing du log v48 + mapping taille→op = **spécifique à un runtime** → à déplacer en *plugin de catalogue*, pas dans le cœur. |
| `acer_nitro_app_v14` (`/hook/inject`, `/hook/status` étendu) | ADAPT | Motif route+confirmation à reprendre. |
| `hook_capture_ctrlcode.py`, `hook_bo_write_capture.py`, `hook_map_sync_capture.py`, `hook_flm_sync_capture.py`, `hook_flm_capture.py`, `hook_runlist_capture.py` | EXCLUDE (référence) | Ces scripts vivent côté `E:\trixdna_test` (runtime ggml-xdna). Ils servent de **specs de hooks** ; ne pas redistribuer sans autorisation (cf. §Sécurité). |

## Diagnostics complémentaires

| Fichier | Statut | Notes |
|---|---|---|
| `npu_ram_diag.py` (`drv_*`, `ram_*`, `npu_pdh_engine`) | ADAPT | `drv_query/sc_status/dacl/files/used_by` = inspection service/driver NPU → génériques, utiles pour provider « driver status ». Retirer suppositions de noms de service codés en dur. |
| `npu_cross_analyze.py` (`analyze_csv`, `decode_isa`, `check_weights`, `kv_budget`, `nan_hypothesis`) | EXCLUDE du cœur | Spécifique ggml-xdna/AM-101. Peut devenir plugin optionnel. |
| `perf_mode.py` (EC, CPU/GPU/NPU/ram apply) | EXCLUDE | Modifie EC/MSR/registres → hors édition publique (§Sécurité). |
| `mcp/nitro_mcp.py` | ADAPT | Motif bridge MCP → API HTTP à reprendre ; outils hook spécifiques à retirer. |

## Fonctions du catalogue `gralle` (référence externe, non redistribuée)

`npu_monitor.dll`, `ioctl_trace.py`, `trace_export.py`, `perf_fusion.py`, `npu_profiler.py`,
`dashboard.py`, `npu_tracer_v2.py` → servent de spec fonctionnelle pour les modules
`hooks/` et `diagnostics/`. Non copiées (code non audité licence).

## Conclusion d'audit

- **Réutilisable directement** : `PDHMonitor`, `_collect_pdh`, `_collect_kernels`, `_collect_token_scope`, `scan_npu_kernels` (portabilisé).
- **À adapter** : tous les collecteurs xrt/process (isolation subprocess, découverte de chemins).
- **À exclure du cœur public** : EC/MSR/WinRing0, apply_*, scripts ggml-xdna spécifiques.
- **Règle imposee au nouveau code** : chaque métrique porte `source` + `validity` ; activité WDDM ≠ occupation silicium XDNA2 ; existence d'une fonction ≠ activée.
