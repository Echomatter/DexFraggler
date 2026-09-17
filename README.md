# DexFraggler

A from-scratch research rebuild of the DX7 patch-search project, replacing
the retired `Echomatter_DexFraggler` JavaScript/plugin codebase. This repo
follows the phased plan in `docs/plan/` (see `docs/plan/00_MASTER_OVERVIEW.md`
for the mission statement, and `docs/plan/00_PHASE_0_BOOTSTRAP.md` +
`docs/plan/ERRATA_AND_REVISIONS.md` for what this session added/clarified).

The core idea: a native, bit-exact DX7 (Dexed Mark I engine) renderer
produces permanent ground-truth audio observations; everything else
(features, forward/inverse models, structured search) is Python/PyTorch
research code built on top of that ground truth, kept strictly separate
from disposable, regenerable derived data.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -e .[dev]
# CPU-only PyTorch used in this environment (no CUDA device available):
.\.venv\Scripts\pip.exe install torch --index-url https://download.pytorch.org/whl/cpu
```

## Verify the toolchain (Phase 1 STOP-gate)

```powershell
.\.venv\Scripts\python.exe -m pytest -q                 # 38 tests
.\.venv\Scripts\python.exe native\smoke_protocol_check.py
.\.venv\Scripts\dexfrag.exe doctor
```

`dexfrag doctor` checks: Python/numpy/torch/pyarrow/TensorBoard
availability, all 32 DX7 algorithm topologies present, one live native
render at the exact reference contract, and one deterministic canonical
2048-sample frame extraction.

## Native renderer provenance & licensing

`native/bin/DexfragglerReference.exe` is a prebuilt binary (SHA-256
`d67045da4b058bb1c7ff62cc347e5cfbd3ea67e260475bb10a7a00cc04d2b5e2`) ported
from the retired repository. `native/source-provenance.json` records the
exact upstream commit and per-file hashes it was built from.
`native/README.md` documents its stdin/stdout line protocol in full. Because
the renderer's engine is derived from GPL-licensed DX7 emulation code (see
`native/licenses/`), this repository is licensed **GPL-3.0-or-later**
(`LICENSE`).

The reference contract, enforced by `src/dexfrag/native.py`, is fixed:
48 kHz sample rate, velocity 100, notes 45/57/69, 7200-sample offset,
4096-sample capture, no gain normalization. Any deviation from this
contract is treated as an error, not a warning — all permanent observation
data depends on this contract being exact and stable.

## Package layout (`src/dexfrag/`)

| Module | Purpose |
|---|---|
| `patch.py` | Canonical `Patch`/`Operator` model, validation, exact VCED/SysEx codec, `patch_key` identity |
| `algorithms.py` | 32 DX7 algorithm topology descriptors + derived structural features (carrier/modulator masks, depth, feedback warm-mask, topology signature) |
| `native.py` | `NativeRenderer` subprocess wrapper enforcing the exact reference contract, with SHA-256 provenance |
| `features.py` | Canonical 2048-sample phase-bearing frame extraction (see errata doc §1) + black-box target-feature boundary enforcement |
| `storage.py` | PyArrow Parquet schemas separating permanent native observations from derived target/search data |
| `splits.py` | Deterministic train/validation/test split assignment + lineage-family grouping + benchmark holdout |
| `budget.py` | Persistent, resumable native-render budget ledger (count/time/disk caps) |
| `mutate.py` | Four mutation families for local-mutation acquisition |
| `acquisition.py` | Four acquisition sources: broad structured, random legal, structure-aware, local mutation |
| `collector.py` | Resumable/crash-safe/deduplicated collection loop tying the above together |
| `cli.py` | `dexfrag doctor \| structure-audit \| dataset-inspect \| dataset-coverage \| collect \| monitor` |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

38 tests cover patch round-trip/legality across all 32 algorithms, algorithm
topology structural invariants, live native-renderer contract validation
(skipped only if the binary is unavailable), canonical frame extraction
determinism/periodicity, Parquet storage round-trip/dedup, and a
TensorBoard scalar-logging smoke test. A further 29 tests (67 total) cover
deterministic split/lineage assignment, the render budget ledger, mutation
families, acquisition sources, and the end-to-end resumable/deduplicated
collector.

## Data acquisition (Phase 2)

```powershell
.\.venv\Scripts\dexfrag.exe collect datasets\main.parquet --seed 42 `
  --broad-structured 5000 --random-legal 5000 --structure-aware 5000 --local-mutation 5000 `
  --max-renders 20000
.\.venv\Scripts\dexfrag.exe dataset-coverage datasets\main.parquet
```

`dexfrag collect` is resumable (already-rendered exact patches are skipped),
crash-safe (periodic flush + a persistent `<dataset>.budget.json` ledger),
and never exceeds an explicit `--max-renders` / `--max-seconds` /
`--max-dataset-bytes` cap — no unbounded default is wired in. See
`docs/plan/PHASE_2_REPORT.md` for the full STOP-gate report, including a
real bounded 64-observation smoke run and operator-ready collection
profiles (calibration / capped-count / capped-duration / capped-disk /
overnight / resume).

## Status

Phase 0 (bootstrap), Phase 1 (foundation), and Phase 2 (acquisition
machinery: splits, budget ledger, mutation families, acquisition sources,
resumable collector) are implemented and passing their STOP-gate checks —
see `docs/plan/PHASE_2_REPORT.md`. Phase 3 (forward-model training) has not
started: it should not begin until the operator has run a real (non-smoke)
collection and reviewed its coverage report.
