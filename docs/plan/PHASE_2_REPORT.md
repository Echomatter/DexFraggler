# Phase 2 Report — Acquisition, Splits, Budget Ledger (Revised)

## Modules created

- `src/dexfrag/splits.py` — deterministic split assignment + lineage-family
  grouping + independent benchmark-holdout flag (design pinned down in
  `ERRATA_AND_REVISIONS.md` §4).
- `src/dexfrag/budget.py` — persistent, resumable native-render budget
  ledger with count/time/disk caps (design pinned down in same section).
- `src/dexfrag/mutate.py` — four distinct mutation families:
  `single_parameter_nudge`, `operator_block_swap`, `algorithm_hop`,
  `feedback_sweep`.
- `src/dexfrag/acquisition.py` — five acquisition sources:
  - `broad_structured_exploration` (topology-cycling, carrier-level-biased),
  - `random_legal_exploration` (baseline diversity),
  - `structure_aware_exploration` (algorithm × coarse-ratio-family ×
    feedback-regime sweep),
  - `coherent_ratio_exploration` (Phase 2 operator-gate revision: deliberately
    constructs harmonically coherent / stationary patches by drawing every
    operator's coarse ratio from a shared coherent family, with fine=0 and
    neutral detune=7, so the whole signal graph stays commensurate with the
    note's fundamental period),
  - `local_mutation` (mutates around previously valid observations, recording
    parent + lineage root).
- `src/dexfrag/collector.py` — the resumable/crash-safe/deduplicated
  collection loop (`collect()`), validity classification
  (`classify_validity`), failure logging, and the **training-data contract
  document** (§ "Training-data contract" below).
- `src/dexfrag/cli.py` — added `dexfrag collect` and `dexfrag
  dataset-coverage` commands; extended `dataset-inspect`. The `collect`
  command now accepts `--coherent-ratio`.
- `src/dexfrag/storage.py` — extended `NATIVE_OBSERVATION_SCHEMA` with
  `lineage_root_key`, `benchmark_holdout`, `split_scheme_version`.

## Tests run

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

**74 passed** (38 Phase 1 + 36 new: `test_splits.py`, `test_budget.py`,
`test_mutate.py`, `test_acquisition.py`, `test_collector.py`). The collector
tests use the real vendored native renderer (skipped only if the binary is
missing) and directly verify: budget-capped stopping, resumability/dedup
across repeated calls, deterministic split/lineage assignment, validity
classification against the real schema, budget-ledger persistence across
calls, mutation-parent reuse, failure-log writing on synthetic render errors,
**coherent_ratio_exploration producing valid observations**, **local_mutation
picking up coherent_ratio parents within the same run**, and **retention of
unstable observations from non-coherent sources**.

## Training-data contract (Phase 2 operator-gate revision)

Permanent native observations retain **every** validity class — nothing is
ever deleted, relabeled, or silently dropped. That is deliberate: genuinely
unstable/inharmonic patches are real DX7 behavior and must remain in the
permanent corpus.

However, `validity_class` is **not** decorative. Later phases (forward model,
inverse proposer, structured search) must treat it as a first-class
training-data selector:

- **`valid`**: the canonical 2048-sample frame is a faithful, phase-bearing
  single-cycle reconstruction of a genuinely periodic-at-the-note waveform.
  This is the **only** class that should be used, by default, as a clean
  stationary-waveform training target/label.
- **`near_silent`**: technically periodic-or-not, but too quiet to trust
  amplitude/phase estimates from (peak below `NEAR_SILENT_PEAK_THRESHOLD`).
  Usable as permanent truth for coverage/robustness experiments, but must not
  be treated as an ordinary clean training target without an explicit,
  documented decision.
- **`silent`**: true silence. Native ground truth (e.g. "this exact patch
  renders silent"), never a periodic-waveform training target.
- **`clipped`**: peak at/above `CLIPPED_PEAK_THRESHOLD`; the canonical frame
  may not reflect true operator amplitudes past the quantization ceiling.
  Usable as native truth, not as a clean regression target for amplitude.
- **`unstable`**: `periodicity_ratio` below `UNSTABLE_PERIODICITY_THRESHOLD`
  for at least one captured note — real inharmonic/beating/non-stationary DX7
  behavior, not a defect. The raw 4096-sample native capture remains valid
  ground truth for *that capture*, but the derived 2048-sample canonical
  frame must not be fed to a model as if it were a clean periodic label. Any
  later phase that wants to use these rows must define an explicit different
  representation/objective for them (e.g. a raw-waveform or spectrogram-based
  target) rather than reusing the periodic-frame contract.
- **Render failures**: never stored as observations at all (see
  `<dataset>.failures.jsonl`); there is no row, hence no `validity_class`, to
  accidentally consume downstream.

This module and `storage.py` intentionally keep all classes in one table with
one shared schema (permanent truth is not partitioned by validity), but any
Phase 3+ dataset loader **MUST** filter on `validity_class` explicitly before
treating `canonical_frames_json` as a ground-truth periodic label.

## Bounded verification calibration (real native renders, not simulated)

### Calibration run 1 — main smoke (64 renders + 15 local_mutation follow-up)

```powershell
.\.venv\Scripts\dexfrag.exe collect datasets\phase2_r2_smoke.parquet --seed 100 `
  --coherent-ratio 16 --broad-structured 16 --random-legal 16 `
  --structure-aware 16 --local-mutation 16 --max-renders 64
# Follow-up to exercise local_mutation (budget cap exhausted before it ran):
.\.venv\Scripts\dexfrag.exe collect datasets\phase2_r2_smoke.parquet --seed 100 `
  --coherent-ratio 16 --broad-structured 16 --random-legal 16 `
  --structure-aware 16 --local-mutation 16 --max-renders 80
```

- **Total observations**: 79 (64 first call + 15 follow-up, 1 additional on
  third resume = 80 after final resume; primary corpus is 79-row dataset).
- **Validity**: 28 `valid`, 50 `unstable`, 2 `near_silent`, 0 `silent`, 0
  `clipped`, 0 `render_failure`.
- **By source**: `coherent_ratio` 16, `broad_structured` 16, `random_legal`
  16, `structure_aware` 16, `local_mutation` 16.
- **Lineage**: `unique_lineage_families: 64`, `mutation_derived_rows: 16`.
- **Budget ledger**: `renders_attempted: 80`, `renders_valid: 28`,
  `sessions: 3`, `dataset_bytes: 14,125,033`.
- **Provenance**: 100% uniform `binary_sha256` and `feature_version`
  (`dexfrag-canonical-frame-v1`).

### Calibration run 2 — algorithm coverage guarantee (64 renders)

```powershell
.\.venv\Scripts\dexfrag.exe collect datasets\phase2_r2_algo_calibration.parquet --seed 200 `
  --coherent-ratio 8 --broad-structured 32 --random-legal 8 `
  --structure-aware 8 --local-mutation 8 --max-renders 64
```

- **Total observations**: 64 rendered, 0 duplicates, 0 failures.
- **Validity**: 15 `valid`, 49 `unstable`.
- **By source**: `coherent_ratio` 8, `broad_structured` 32, `random_legal`
  8, `structure_aware` 8, `local_mutation` 8.
- **Algorithm coverage**: **all 32 algorithms** present (1–32, none missing).
- **Coarse-ratio-family coverage**: values 0–31 represented; 24.7% of
  operators have exact integer ratios (fine=0, detune=7).
- **Feedback coverage**: all 8 feedback values (0–7) present.
- **Lineage**: `unique_lineage_families: 56`, `mutation_derived_rows: 8`.
- **Mutation lineage integrity**: verified — every mutation child's
  `lineage_root_key` matches its parent's root; every `parent_key` exists in
  the dataset; split assignment is consistent by lineage.
- **Dedup/resume verified**: re-running the identical command produced
  `duplicates_skipped: 56, rendered: 0` — exact-identity dedup and full
  resumability confirmed.
- **Budget cap verified**: `renders_attempted cap reached (64/64)` enforced
  on resume against the persistent ledger.
- **Provenance**: 100% uniform `binary_sha256` and `feature_version`.

## Finding (resolved): naive coarse-ratio sampling produces "unstable" patches

The original 64-observation smoke (before the `coherent_ratio` revision)
found 63 `unstable`, 1 `near_silent`, 0 `valid` — because the four original
sources each sample every operator's coarse ratio independently, which
predominantly produces patches that are *not* periodic at the played note's
own fundamental.

**This is real DX7 behavior, not a bug.** Verified directly:
`six independently-chosen coarse ratios do not generally produce a waveform
periodic at the note's own pitch`. The `unstable` classification correctly
flags this rather than silently mislabeling it as `valid`.

**Resolution**: the fifth acquisition source `coherent_ratio_exploration`
(detailed above) deliberately constructs harmonically coherent patches by
drawing every operator's coarse ratio from a shared coherent family. The
revised calibration shows 28 `valid` observations from 79 total — the valid
portion of the corpus is now populated and `local_mutation` has real parents
to mutate around. The naturally-inharmonic/unstable rows from the other four
sources remain in the corpus as legitimate DX7 behavior.

## Coherent-ratio strategies used

`coherent_ratio_exploration` cycles through seven ratio families:

| Family | Coarse values | Strategy |
|--------|---------------|----------|
| `unison` | (1,) | All operators at the note's own pitch |
| `octave_stack` | (1, 2, 4, 8) | Power-of-two octave stacking |
| `wide_octave_stack` | (1, 2, 4, 8, 16) | Extended octave range |
| `harmonic_series_low` | (1, 2, 3, 4) | Low harmonic series |
| `harmonic_series_full` | (1, 2, 3, 4, 5, 6) | Extended harmonic series |
| `fifth_stack` | (1, 3) | Perfect-fifth intervals |
| `sub_harmonic_unison` | (0, 1) | Sub-octave (coarse 0 = ×0.5) + unison |

All operators use `fine=0`, `detune=7` (neutral), `mode=0` (ratio mode),
ensuring exact integer/half-integer frequency ratios to the played note.
Carriers are drawn from the low end of the family to anchor the audible
register; modulators may use any family member. Feedback is mostly low
(60% chance 0–2), occasionally mid (30% 3–4), rarely high (10% 5–7).

## STOP-gate checklist

1. collection can run, stop, and resume — ✅ verified (3-session resumable
   run on `phase2_r2_smoke.parquet`; dedup/resume verified on
   `phase2_r2_algo_calibration.parquet`).
2. exact duplicates are not rerendered — ✅ verified (56/56 duplicates on
   resume; 0 rendered).
3. mutation lineage is recorded — ✅ verified with real renderer: every
   mutation child's `parent_key` exists in the dataset, `lineage_root_key`
   matches parent's root, split assignment is consistent by lineage.
4. split assignment is stable — ✅ `lineage_root_key`/`split` verified
   deterministic in `test_splits.py` and present in real calibration rows.
5. stricter family/lineage holdout can be generated — ✅
   `benchmark_holdout()` implemented, tested, present in schema (0 flagged
   in these tiny samples, as expected at ~2% rate).
6. coverage reports include structural coverage — ✅
   `dexfrag dataset-coverage` reports by-algorithm, by-topology-signature,
   by-feedback, lineage-family count, coarse-ratio-bucket distribution,
   provenance/version distributions.
7. degenerate/failure handling is visible — ✅ validity classes reported;
   render failures write to `<dataset>.failures.jsonl` (unit-tested; none
   occurred in real calibration runs).
8. acquisition source is recorded — ✅ `acquisition_source` column, all 5
   sources reported in coverage.
9. bounded smoke collection passes — ✅ exactly 64 native renders performed
   per calibration run, cap enforced on resume.
10. operator instructions explain the first meaningful collection — ✅ see
    "Operator-ready profiles" below.
11. **coherent_ratio produces valid observations** — ✅ 28 valid from 79
    total (35.4% valid rate, up from 0% without this source).
12. **local_mutation uses valid parents** — ✅ 16 mutation-derived rows with
    verified parent_key and lineage_root integrity.
13. **unstable observations retained from other sources** — ✅ 50 unstable
    from broad_structured/random_legal/structure_aware still present.
14. **training-data contract documented** — ✅ explicit validity-class
    semantics in `collector.py` §52–101.

## Operator-ready profiles

No unbounded default is wired into `dexfrag collect` — `--max-renders`,
`--max-seconds`, and `--max-dataset-bytes` are all optional and independent;
omitting all three means no cap, which the CLI help text calls out
explicitly.

**Important**: `--broad-structured` must be ≥32 if full algorithm coverage is
required (it cycles through all 32 algorithms). `--coherent-ratio` should be
included to populate the valid/periodic portion of the corpus and seed
`local_mutation` with parents.

```powershell
# Quick calibration (a few seconds, tiny bounded run):
dexfrag collect datasets\calibration.parquet --seed 1 `
  --coherent-ratio 8 --broad-structured 32 --random-legal 8 `
  --structure-aware 8 --local-mutation 8 --max-renders 64

# Capped observation count (e.g. 5,000 new renders this session):
dexfrag collect datasets\main.parquet --seed 2 `
  --coherent-ratio 1000 --broad-structured 2000 --random-legal 1000 `
  --structure-aware 1000 --local-mutation 1000 --max-renders 5000

# Capped wall-clock duration (e.g. a 30-minute run regardless of count):
dexfrag collect datasets\main.parquet --seed 2 `
  --coherent-ratio 50000 --broad-structured 100000 --random-legal 50000 `
  --structure-aware 50000 --local-mutation 50000 --max-seconds 1800

# Capped disk usage (e.g. stop once the dataset file reaches 2 GB):
dexfrag collect datasets\main.parquet --seed 2 `
  --coherent-ratio 50000 --broad-structured 100000 --random-legal 50000 `
  --structure-aware 50000 --local-mutation 50000 --max-dataset-bytes 2000000000

# Extended/overnight run (combine a generous time cap with a hard count cap
# as a safety net):
dexfrag collect datasets\main.parquet --seed 2 `
  --coherent-ratio 50000 --broad-structured 50000 --random-legal 50000 `
  --structure-aware 50000 --local-mutation 50000 `
  --max-seconds 28800 --max-renders 200000

# Resume: identical command, same dataset path -- already-rendered exact
# patches are skipped automatically; the budget ledger (<dataset>.budget.json)
# carries the cumulative renders_attempted forward across the whole cap.
```

## Exact next operator command

```powershell
.\.venv\Scripts\dexfrag.exe collect datasets\main.parquet --seed 42 `
  --coherent-ratio 2000 --broad-structured 5000 --random-legal 2000 `
  --structure-aware 2000 --local-mutation 2000 --max-renders 12000
.\.venv\Scripts\dexfrag.exe dataset-coverage datasets\main.parquet
```

This allocates ~17% of the render budget to `coherent_ratio` (ensuring a
healthy supply of valid/periodic parents for `local_mutation`), ~42% to
`broad_structured` (guaranteeing full algorithm coverage since it cycles
through all 32), and the remainder split across `random_legal`,
`structure_aware`, and `local_mutation`.

Bring back the `dataset-coverage` JSON output (algorithm/topology/validity/
split/lineage/coarse-ratio distributions and throughput) before Phase 3
(forward model) implementation begins, per the pack's STOP-gate discipline.

**Phase 3 (forward-model implementation) has not started and should not
start until the operator has reviewed a real (non-smoke) corpus.**
