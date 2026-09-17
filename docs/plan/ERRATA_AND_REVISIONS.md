# Errata & Revisions to the Rebuild Pack

This document records where the fresh implementation clarified, resolved,
or diverged from the attached `DexFraggler_ML_Search_Rebuild_Pack`, based
on the plan review performed before implementation began. Treat this as an
addendum layered on top of the original phase docs — it does not replace
them.

## 1. Resolved: 4096-sample capture vs. "2048-sample canonical frame"

**Gap:** The pack's Phase 1 doc specifies a 2048-sample canonical periodic
frame as the model input/output unit, but the only validated ground truth
(the native renderer) captures 4096 raw samples per note, unnormalized,
starting 7200 samples after note-on. The pack never defined the mapping
between the two.

**Resolution (implemented in `src/dexfrag/features.py::canonical_frame`):**

1. Nominal fundamental = the equal-tempered frequency of the rendered MIDI
   note (`440 * 2**((note-69)/12)`). DX7 coarse/fine/detune parameters
   modify *operator* frequencies relative to the note being played, not the
   note's own pitch, so the note's ET frequency is the correct phase-locking
   reference, not a value derived from patch parameters.
2. Direct-summation (not FFT-bin) Fourier projection of the full 4096-sample
   capture onto sin/cos bases at each harmonic of that nominal fundamental,
   band-limited by both a `max_harmonics` parameter and Nyquist.
3. Synthesize a canonical N-sample (default 2048) frame by evaluating the
   truncated Fourier series at N equally spaced phase points. This is
   deterministic and phase-bearing (preserves relative phase between
   harmonics, required for the plan's non-black-box internal telemetry).
4. A `periodicity_ratio` diagnostic (harmonic-model-explained energy over
   total capture energy) is returned alongside the frame so that inharmonic
   or non-periodic captures are flagged rather than silently corrupted.

**Known accepted limitation:** because 4096 samples at an arbitrary note
frequency does not span an integer number of periods, the rectangular-window
direct-summation projection has real spectral leakage (empirically ~0.4–0.8%
amplitude error on a synthetic 220 Hz test tone). This is not a bug; the
test suite tolerance (`tests/test_features.py`, `1e-2`) reflects it
explicitly rather than papering over it with a tighter, false tolerance. If
Phase 3 forward-model training later needs tighter fidelity, revisit with a
windowing function or exact-period-locked capture instead of the raw
rectangular window over the full 4096-sample capture.

## 2. Resolved: black-box target boundary is now enforced, not just documented

**Gap:** The pack repeatedly states target patches/synthesis recipes must
never leak into model-visible features ("black-box rule"), but had no
mechanism to catch a violation.

**Resolution:** `features.py` defines `FORBIDDEN_TARGET_KEYS` and
`ALLOWED_TARGET_BOOKKEEPING_KEYS`; `black_box_target_features()` raises
`FeatureError` on any forbidden key. This is exercised by
`tests/test_features.py`. Any later phase's dataset-generation code should
route target-derived dictionaries through this function.

## 3. Resolved: permanent truth vs. derived/experiment data separation

**Gap:** The pack's data-management principle ("native renders are
permanent; everything derived, e.g. search targets/scores, is
disposable/regenerable") was a stated rule with no schema enforcement.

**Resolution:** `src/dexfrag/storage.py` defines three separate PyArrow
schemas: `NATIVE_OBSERVATION_SCHEMA` (permanent, keyed by patch identity +
render contract), `TARGET_RECORD_SCHEMA`, and `TARGET_PATCH_SCORE_SCHEMA`
(derived). They are physically different tables/files by construction, not
just a naming convention.

**Caveat carried forward, not yet resolved:** `append_observations()`
currently does full read + dedup + atomic rewrite rather than true
incremental Parquet append (PyArrow has no safe partial-file append). This
is acceptable at Phase 1/2 smoke scale (thousands of rows) but will not
scale to Phase 2's full acquisition target; Phase 2 must shard by file
before doing high-volume collection. **This is an open item for whoever
implements Phase 2**, not resolved here.

## 4. Still open / deferred to their owning phase (not resolved by Phase 0)

These were flagged in the original plan review and are **intentionally not
decided yet** — they require design work at the start of their respective
phase, informed by data Phase 0 does not produce:

- **Dataset split strategy** (Phase 2): the pack does not specify how
  train/val/test splits stay stable as data accumulates incrementally.
  Recommendation carried forward: immutable hash-based assignment on
  `patch_key` (already implemented, see `patch.py::patch_key`) plus explicit
  lineage/family grouping so that near-duplicate patches don't leak across
  splits. Not implemented — Phase 2's responsibility.
- **Native render budget/accounting** (Phase 2): the pack references
  compute budgets for native calls without a ledger mechanism. Needs a
  counter/quota implementation before large-scale collection begins.
- **Inverse-proposer training objective** (Phase 4): the pack describes the
  proposer's role but not its loss function precisely enough to implement
  without ambiguity (single best patch vs. distribution vs. top-k
  retrieval-style ranking). Needs to be pinned down at the start of Phase 4.
- **Compatibility/search pair-schema versioning** (Phase 5): schema for
  compatibility pairs should be versioned from the start given the rest of
  the pipeline's emphasis on reproducibility; not yet defined.
- **Reachability calibration** (Phase 6) and **Phase 7 compute bounds**:
  both need concrete numeric budgets pinned down against real measured
  native-render throughput once Phase 2 has run for a while — premature to
  fix now.

## 5. Environment / reproducibility notes

- No C/C++ build toolchain (cmake, MSVC Build Tools) was available in this
  environment; the native renderer is vendored as a prebuilt binary with
  full SHA-256 provenance rather than rebuilt from source. See
  `00_PHASE_0_BOOTSTRAP.md`.
- Python 3.13.2, CPU-only PyTorch (`2.14.0+cpu`) — no CUDA device available
  in this environment. Phase 3+ training will be CPU-bound here; if GPU
  training is needed, it must happen in a different environment with the
  same `pyproject.toml` dependency pins.
