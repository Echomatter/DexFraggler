# Phase 1 — Native Truth + Canonical Data + Structural Inventory

## Objective

Create the smallest trustworthy Python research foundation and identify exact structure that can reduce later search.

This phase establishes:

```text
legal DX7 patch
    ↓
native Dexed render
    ↓
canonical waveform/features
    ↓
permanent observation

legal algorithm/patch
    ↓
derived topology + exact search structure
```

**Do not build or meaningfully train neural models in this phase.**
**Do not begin broad data collection.**
**Do not begin search optimization.**

---

# Required stack

- Python 3.12+
- PyTorch installed and importable
- NumPy
- SciPy where useful
- PyArrow / Parquet
- TensorBoard
- pytest
- `uv` or an equivalent simple environment manager

Keep dependencies minimal.

---

# Inspect current repository first

Before changing architecture, inspect existing validated components.

At minimum inspect:

```text
native/
models/
runner/reference.mjs
public/core.mjs
docs/calculation-models.md
docs/analytic-fitting.md
tests/
```

Preserve behavior that is already tested rather than recreating it from memory.

Do not reimplement Dexed in Python.

Do not delete unrelated plugin/application work merely because it is out of scope.

---

# Native renderer boundary

Retain the native Dexed Mark I renderer as authority.

Create a clean Python API similar to:

```python
render_patch(patch) -> NativeObservation
render_batch(patches) -> list[NativeObservation]
```

The adapter must expose/record:

- executable hash,
- renderer/source provenance,
- sample rate,
- note(s),
- velocity,
- onset offset,
- capture duration,
- exact patch bytes,
- actionable failures.

Preserve current reference conditions unless repository verification establishes a newer explicit contract:

- 48 kHz,
- velocity 100,
- notes 45 / 57 / 69,
- offset 7,200 samples,
- capture 4,096 samples.

Do not silently normalize away information that current native scoring depends on.

---

# Canonical patch

Define one canonical Python patch representation.

At minimum include:

- algorithm,
- feedback,
- six operators,
- coarse,
- fine,
- detune,
- oscillator mode,
- output level,
- every additional parameter included in the stationary-waveform research profile,
- exact legal patch bytes / identity.

Explicitly classify parameters as:

```text
searchable
fixed reference
derived
```

If envelopes, LFO, key scaling, velocity sensitivity, or other fields are held constant for stationary waveform research, document the exact values and validate them.

Different legal patches must never be merged merely because they sound similar.

---

# Exact patch identity

Patch identity must be reproducible from exact legal bytes.

Provide:

```python
patch_key(patch) -> stable key
validate_patch(patch)
encode_patch(patch) -> exact bytes
decode_patch(bytes) -> patch
```

Requirements:

- round trip is exact,
- identity is deterministic,
- no lossy normalization changes identity,
- exact duplicates are detectable before native render.

---

# Algorithm structure

Create a transparent derived descriptor for each of the 32 algorithms.

At minimum consider:

- carrier mask,
- modulator mask,
- adjacency / parent-child routing,
- path depth,
- branch membership,
- feedback location/path,
- operator role labels,
- topology signature.

This descriptor is a feature and search aid.

Algorithm remains a legal patch parameter.

Do **not** recreate algorithm rows or 32 separate model pipelines.

---

# Structural-reduction audit

Create a machine-readable report and tests covering:

1. legal parameter ranges,
2. fixed parameters in the research profile,
3. exact topology descriptors,
4. any exact symmetries/equivalences used for search dedupe,
5. any analytically fitted parameters,
6. reversible mapping back to exact legal patch state.

The rule is:

> Only reduce a dimension when the reduction is exact, reversible, or explicitly limited to search-state equivalence.

Do not merge permanent observations due to structural or sonic similarity.

If current analytic Jacobian/fitting code is retained, establish parity tests before using it later as a search move generator.

---

# Canonical waveform

Use **2048 periodic samples**.

Retain:

- normalized samples,
- phase-bearing harmonic representation,
- complex sine/cosine coefficients or equivalent complex coefficients,
- magnitudes,
- RMS/energy,
- peak,
- deterministic spectral statistics,
- feature extractor version.

Do not discard phase.

Implement one authoritative feature extractor and test determinism.

---

# Canonical wavetable

Support:

```text
256 frames × 2048 samples
```

All 256 frames must ingest.

No 32-frame reduction.
No anchors.
No algorithm-row mapping.

The target model input must be waveform-derived only.

---

# Black-box target boundary test

Create a target adapter that can ingest arbitrary 2048-sample frames and 256×2048 tables.

The model-facing target record must not contain generator recipe fields.

Allowed bookkeeping:

- target hash,
- source file hash,
- frame index,
- experiment ID.

Not allowed as model features:

- seed,
- recipe,
- mathematical waveform family,
- generator name,
- difficulty label,
- multiplex count,
- hidden creation metadata.

Add a test proving the feature pipeline is a pure function of waveform samples + feature version.

---

# Observation storage

Define append-friendly Parquet storage.

Permanent observation fields:

- patch identity,
- exact patch bytes,
- patch parameters,
- algorithm structure/version,
- A2/A3/A4 native captures/descriptors,
- canonical waveform/features,
- renderer provenance,
- feature version,
- acquisition source,
- validity/degenerate class,
- timestamp.

Also define separate schemas/directories for:

- target records,
- target/patch derived scores,
- search traces,
- target solutions,
- experiment manifests.

Do not duplicate native observations per target.

---

# Initial CLI

Implement concepts equivalent to:

```text
dexfrag doctor
dexfrag dataset inspect
dexfrag structure audit
dexfrag monitor
```

`dexfrag doctor` must validate the complete local environment and perform one bounded native render.

`dexfrag structure audit` should emit the structural report without starting search.

---

# Instrumentation

Set up:

```text
datasets/
experiments/
checkpoints/
runs/
```

TensorBoard smoke logging should prove:

- scalar logging,
- waveform/plot logging,
- configuration logging.

---

# Tests

At minimum:

- patch legality,
- patch encode/decode round trip,
- exact patch-key stability,
- Python → native invocation,
- reference condition determinism,
- renderer hash/provenance capture,
- 2048-sample canonical extraction,
- phase-bearing harmonic extraction,
- 256×2048 wavetable ingestion,
- black-box target leakage test,
- algorithm topology descriptors for all 32 algorithms,
- structural-reduction reversibility where used,
- Parquet write/read round trip,
- TensorBoard logging smoke test.

If analytic fitting/Jacobian is carried forward:

- parity against current validated implementation on fixtures,
- legal output after quantization,
- failure path returns safe unchanged/no-op candidate rather than corrupt state.

---

# Bounded validation only

Codex may perform:

- one or a few native renders,
- fixture generation,
- tests,
- structure-report generation.

No data-collection run.

No neural training.

---

# STOP gate

Stop when:

1. `dexfrag doctor` passes.
2. Python can render a legal patch natively.
3. Native provenance and exact patch identity are stable.
4. One native observation becomes deterministic canonical features.
5. A `[256, 2048]` wavetable ingests without reduction.
6. Target features contain no generator provenance.
7. All 32 algorithm topology descriptors exist.
8. Structural audit is machine-readable and tested.
9. Observation/target/search schemas write and read correctly.
10. TensorBoard smoke logging works.
11. Tests pass.
12. README documents the Phase 2 operator action.

### Required phase report

Report:

- modules created/replaced,
- preserved native/current-repo components,
- exact reference render conditions,
- structure-audit findings,
- tests run,
- `dexfrag doctor` summary,
- risks,
- exact command for Phase 2 smoke/real collection.

**Do not begin Phase 2 automatically.**
