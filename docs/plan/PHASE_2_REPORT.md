# Phase 2 Report — Acquisition, Splits, Budget Ledger

## Modules created

- `src/dexfrag/splits.py` — deterministic split assignment + lineage-family
  grouping + independent benchmark-holdout flag (design pinned down in
  `ERRATA_AND_REVISIONS.md` §4).
- `src/dexfrag/budget.py` — persistent, resumable native-render budget
  ledger with count/time/disk caps (design pinned down in same section).
- `src/dexfrag/mutate.py` — four distinct mutation families:
  `single_parameter_nudge`, `operator_block_swap`, `algorithm_hop`,
  `feedback_sweep`.
- `src/dexfrag/acquisition.py` — four acquisition sources: `broad_structured
  _exploration` (topology-cycling, carrier-level-biased), `random_legal
  _exploration` (baseline diversity), `structure_aware_exploration`
  (algorithm × coarse-ratio-family × feedback-regime sweep), `local_mutation`
  (mutates around previously valid observations, recording parent + lineage
  root).
- `src/dexfrag/collector.py` — the resumable/crash-safe/deduplicated
  collection loop (`collect()`), validity classification
  (`classify_validity`), and failure logging.
- `src/dexfrag/cli.py` — added `dexfrag collect` and `dexfrag
  dataset-coverage` commands; extended `dataset-inspect`.
- `src/dexfrag/storage.py` — extended `NATIVE_OBSERVATION_SCHEMA` with
  `lineage_root_key`, `benchmark_holdout`, `split_scheme_version`.

## Tests run

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

**67 passed** (38 Phase 1 + 29 new: `test_splits.py`, `test_budget.py`,
`test_mutate.py`, `test_acquisition.py`, `test_collector.py`). The collector
tests use the real vendored native renderer (skipped only if the binary is
missing) and directly verify: budget-capped stopping, resumability/dedup
across repeated calls, deterministic split/lineage assignment, validity
classification against the real schema, budget-ledger persistence across
calls, mutation-parent reuse, and failure-log writing on synthetic render
errors.

## Bounded 64-observation smoke collection (real, not simulated)

Operator command used (repeatable):

```powershell
.\.venv\Scripts\dexfrag.exe collect datasets\phase2_smoke.parquet --seed 100 `
  --broad-structured 20 --random-legal 20 --structure-aware 16 --local-mutation 8 --max-renders 64
```

Ran twice back-to-back (first call rendered 56/64 since `local_mutation`
had no valid parents yet and yielded 0 candidates; a follow-up call with
`--structure-aware 8 --max-renders 64` used the remaining 8 units of budget
headroom, for **64 total native renders across the whole smoke exercise**,
matching the plan's cap exactly).

- **Total observations**: 64 (`dataset_rows: 64`).
- **Validity**: 63 `unstable`, 1 `near_silent`, 0 `silent`, 0 `clipped`,
  0 `valid`, 0 `render_failure`.
- **By source**: `broad_structured` 20, `random_legal` 20, `structure_aware`
  24, `local_mutation` 0 (no valid parents were available — see finding
  below).
- **By split**: train 60, validation 2, test 2 (roughly matches the 90/5/5
  target at this tiny sample size).
- **Duplicate/resume behavior verified**: re-running the exact same
  command (same seed, same plan) produced `duplicates_skipped: 56,
  rendered: 0` — proving exact-identity dedup and full resumability.
- **Budget cap verified**: a third call with `--max-renders 64` was
  immediately refused with `stopped_reason: "renders_attempted cap reached
  (64/64)."` and rendered nothing — proving the bounded-collection
  guarantee holds against the persistent ledger, not just in-process state.
- **Provenance**: 100% of rows carry the same `binary_sha256` and
  `feature_version` (`dexfrag-canonical-frame-v1`), confirmed via `dexfrag
  dataset-coverage`.
- **Lineage**: `unique_lineage_families: 64` (every row is its own family
  root, since no mutation occurred), `mutation_derived_rows: 0`.
- **Throughput**: ~6.3 renders/second on this machine (56 renders in
  8.86s + 8 renders in 1.55s).
- **Dataset size**: ~11.1 MB for 64 rows including raw 4096-sample
  waveforms (`--no-waveforms` roughly halves this; not used here so the
  smoke corpus is maximally inspectable).

## Finding: naive coarse-ratio sampling mostly produces "unstable" patches

**This is a real corpus property, not a bug.** Verified directly (outside
the collector, no budget consumed): `blank_patch()` (a hand-tuned,
harmonically coherent one-carrier patch) renders with `periodicity_ratio`
≈ 1.0 at all three notes, matching `dexfrag doctor`'s canonical-frame check.
But patches from `structure_aware_exploration`, which assigns each
operator's `coarse` ratio independently at random, measured
`periodicity_ratio` between 0.001 and 0.56 — i.e. genuinely **not**
periodic at the played note's nominal fundamental within one 4096-sample
capture. This is expected DX7 behavior: six independently-chosen coarse
ratios do not generally produce a waveform periodic at the note's own
pitch; they can produce content periodic at a much lower composite
frequency (well outside the capture window) or effectively non-stationary
beating. The `unstable` classification is doing exactly what it's supposed
to: flagging this rather than silently mislabeling it as `valid`.

**Consequence for later phases (not resolved here, flagged for the
operator/Phase 3):** with the current acquisition sources' naive coarse
sampling, the corpus will skew heavily toward `unstable` and starve
`local_mutation` of parents (as seen in this smoke run: 0 valid → 0
mutation candidates). Two non-exclusive options for whoever runs the real
Phase 2 collection at scale:
1. Accept the natural distribution and let the forward model learn from a
   majority-`unstable` corpus (matches "don't over-prune weird regions").
2. Add a fifth, explicitly "coherent-ratio" acquisition source (e.g. shared
   or low-integer coarse across operators) to reliably seed `local_mutation`
   with periodic parents, without removing the naturally-inharmonic rows
   from the dataset.

## STOP-gate checklist

1. collection can run, stop, and resume — ✅ verified above.
2. exact duplicates are not rerendered — ✅ verified (56/56 duplicates on resume).
3. mutation lineage is recorded — ✅ mechanism implemented and unit-tested
   with the real renderer (`test_collector.py`); not exercised in the smoke
   corpus itself because no valid parents existed (see finding above).
4. split assignment is stable — ✅ `lineage_root_key`/`split` verified
   deterministic in `test_splits.py` and present in the real smoke rows.
5. stricter family/lineage holdout can be generated — ✅
   `benchmark_holdout()` implemented, tested, present in schema
   (0 flagged in this tiny 64-row sample, as expected at ~2% rate).
6. coverage reports include structural coverage — ✅
   `dexfrag dataset-coverage` reports by-algorithm, by-topology-signature,
   by-feedback, lineage-family count, provenance/version distributions.
7. degenerate/failure handling is visible — ✅ validity classes reported;
   render failures write to `<dataset>.failures.jsonl` (unit-tested with a
   synthetic renderer failure; none occurred in the real smoke run).
8. acquisition source is recorded — ✅ `acquisition_source` column, reported
   in coverage.
9. bounded smoke collection passes — ✅ exactly 64 native renders performed
   across the whole exercise, cap enforced on a third attempt.
10. operator instructions explain the first meaningful collection — ✅ see
    "Operator-ready profiles" below.

## Operator-ready profiles

No unbounded default is wired into `dexfrag collect` — `--max-renders`,
`--max-seconds`, and `--max-dataset-bytes` are all optional and independent;
omitting all three means no cap, which the CLI help text calls out
explicitly.

```powershell
# Quick calibration (a few seconds, tiny bounded run):
dexfrag collect datasets\calibration.parquet --seed 1 `
  --broad-structured 8 --random-legal 8 --structure-aware 8 --local-mutation 0 --max-renders 24

# Capped observation count (e.g. 5,000 new renders this session):
dexfrag collect datasets\main.parquet --seed 2 `
  --broad-structured 2000 --random-legal 2000 --structure-aware 1500 --local-mutation 1500 `
  --max-renders 5000

# Capped wall-clock duration (e.g. a 30-minute run regardless of count):
dexfrag collect datasets\main.parquet --seed 2 `
  --broad-structured 100000 --random-legal 100000 --structure-aware 100000 --local-mutation 100000 `
  --max-seconds 1800

# Capped disk usage (e.g. stop once the dataset file reaches 2 GB):
dexfrag collect datasets\main.parquet --seed 2 `
  --broad-structured 100000 --random-legal 100000 --structure-aware 100000 --local-mutation 100000 `
  --max-dataset-bytes 2000000000

# Extended/overnight run (combine a generous time cap with a hard count cap
# as a safety net):
dexfrag collect datasets\main.parquet --seed 2 `
  --broad-structured 50000 --random-legal 50000 --structure-aware 50000 --local-mutation 50000 `
  --max-seconds 28800 --max-renders 200000

# Resume: identical command, same dataset path -- already-rendered exact
# patches are skipped automatically; the budget ledger (<dataset>.budget.json)
# carries the cumulative renders_attempted forward across the whole cap.
```

## Exact next operator command

Before starting a real (non-smoke) corpus, decide whether to add the
"coherent-ratio" acquisition source discussed above. Then run, e.g.:

```powershell
dexfrag collect datasets\main.parquet --seed 42 `
  --broad-structured 5000 --random-legal 5000 --structure-aware 5000 --local-mutation 5000 `
  --max-renders 20000
dexfrag dataset-coverage datasets\main.parquet
```

Bring back the `dataset-coverage` JSON output (algorithm/topology/validity/
split/lineage distributions and throughput) before Phase 3 (forward model)
implementation begins, per the pack's STOP-gate discipline.

**Phase 3 (forward-model implementation) has not started and should not
start until the operator has reviewed a real (non-smoke) corpus.**
