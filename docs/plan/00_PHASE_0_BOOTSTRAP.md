# Phase 0 — Fresh-Repository Bootstrap (added to the rebuild pack)

This phase did not exist in the original pack because it assumed an
already-populated `Echomatter/DexFraggler` repository. This is a fresh
repository (`DexFraggler`, no prior git history), so Phase 0 exists to
establish the concrete engineering foundation Phase 1 depends on. **This
phase is complete** as of the initial bootstrap session; later phases
build on what is described here rather than re-deriving it.

## What was ported from the retired Echomatter_DexFraggler repository

Only the following were copied, and only in the form described:

- **`native/bin/DexfragglerReference.exe`** — the prebuilt native Dexed
  Mark I reference renderer, copied byte-for-byte (SHA-256
  `d67045da4b058bb1c7ff62cc347e5cfbd3ea67e260475bb10a7a00cc04d2b5e2`).
  We do **not** have a C/C++ toolchain (no `cmake`, no MSVC Build Tools)
  in this environment, so the executable is vendored as a binary artifact
  rather than rebuilt from source, exactly as the retired repository's own
  `DEXFRAGGLER_NATIVE_EXE` override mechanism already supported.
- **`native/source-provenance.json`** — the exact upstream commit and
  per-file SHA-256 manifest the executable was built from.
- **`native/README.md`** and **`native/licenses/`** (GPL-3.0-or-later and
  Apache-2.0 texts, plus the third-party DX7 core README) — provenance and
  license compliance for redistributing the combined executable.
- **`native/smoke_protocol_check.py`** — adapted (paths only) end-to-end
  protocol/audio smoke test: verifies 110/220/440 Hz tuning, finite bounded
  PCM, determinism, and malformed-input handling of the exact binary in
  this repository.
- The **VCED/SysEx byte layout, fixed research-profile bytes, and 32
  algorithm topology descriptors** were re-derived line-for-line from the
  validated JavaScript source (`public/core.mjs`, `public/algorithms.mjs`)
  into a new, independent Python implementation
  (`src/dexfrag/patch.py`, `src/dexfrag/algorithms.py`). No JavaScript
  files were copied; the *behavior* (exact byte offsets, checksum formula,
  32-algorithm edge/carrier/feedback tables) was preserved and is covered
  by round-trip and topology tests.

Nothing else from the old repository (its Next.js app, SQLite scheduler,
JUCE/LV2 plugin scaffolding, desktop tray app, or its own JS optimizer) was
ported. The old 32×32 architecture is retired, per the mission statement in
`00_MASTER_OVERVIEW.md`.

## What Phase 0 built

```text
DexFraggler/
  pyproject.toml         # Python 3.12+ project, torch/numpy/scipy/pyarrow/tensorboard/typer
  .venv/                 # local virtual environment (numpy, scipy, pyarrow,
                          # pytest, tensorboard, typer, torch==2.14 CPU build)
  native/
    bin/DexfragglerReference.exe
    source-provenance.json
    licenses/{LICENSE-GPL-3.0,LICENSE-APACHE-2.0,THIRD_PARTY_DX7_README.md}
    smoke_protocol_check.py
  src/dexfrag/
    patch.py             # Patch/Operator dataclasses, validate/encode/decode, patch_key
    algorithms.py         # 32 algorithm topology descriptors + structural audit report
    native.py             # NativeRenderer subprocess wrapper + reference-contract validation
    features.py           # canonical_frame() 2048-sample extraction + black-box target boundary
    storage.py             # Parquet observation schema + atomic append/read
    cli.py                 # `dexfrag doctor|structure-audit|dataset-inspect|monitor`
  tests/                  # 38 passing tests (patch, algorithms, native, features, storage, tensorboard)
  docs/plan/              # this rebuild pack, plus PHASE_0 and ERRATA docs
  datasets/ experiments/ checkpoints/ runs/   # empty, gitignored working directories
```

## STOP-gate verification performed in this session

Ran and passed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q            # 38 passed
.\.venv\Scripts\python.exe native\smoke_protocol_check.py
.\.venv\Scripts\dexfrag.exe doctor                  # all 8 checks ok:true
.\.venv\Scripts\dexfrag.exe structure-audit --out docs\plan\phase1-structure-audit.json
```

`dexfrag doctor` confirms: Python 3.13.2, numpy 2.5.3, torch 2.14.0+cpu
(CUDA not available on this machine), pyarrow 25.0.1, TensorBoard scalar
logging, all 32 algorithm topologies present, one live native render at the
exact reference contract (48 kHz / velocity 100 / notes 45,57,69 / offset
7200 / capture 4096), and one deterministic 2048-sample canonical frame
extraction.

## Decisions this bootstrap made explicit (see ERRATA_AND_REVISIONS.md)

1. The exact **2048-sample canonicalization contract**: a phase-bearing
   truncated Fourier-series reconstruction referenced to the equal-tempered
   nominal note frequency, with a `periodicity_ratio` diagnostic. See
   `src/dexfrag/features.py` module docstring for the full contract and
   `ERRATA_AND_REVISIONS.md` item 1 for why this was necessary before any
   later phase could proceed.
2. The **research voice profile** (which VCED bytes are fixed vs.
   searchable) is now an explicit, tested constant table in
   `src/dexfrag/patch.py` (`RESEARCH_PROFILE_NOTES`, `_OPERATOR_FIXED_PREFIX`,
   `_VOICE_FIXED_PREFIX/_SUFFIX`), not an assumption.
3. Licensing: the combined system is GPL-3.0-or-later (see `LICENSE`)
   because it wraps and redistributes the GPL-licensed native renderer.

## What Phase 0 explicitly did not do

- Did not begin Phase 2 data collection.
- Did not train any model.
- Did not implement search.
- Did not rebuild the native executable from source (no C++ toolchain
  available in this environment); if a future session needs to modify the
  native engine itself, install CMake + MSVC Build Tools and use
  `native/vendor/` sources from the retired repository as the starting
  point, or re-derive from upstream Dexed/`msfa`.
