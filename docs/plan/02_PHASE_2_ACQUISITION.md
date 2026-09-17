# Phase 2 — Dataset Acquisition + Coverage + Lineage

## Objective

Build a robust collector capable of creating a large, diverse native DX7 observation corpus.

This phase builds the machinery.

**Codex must not perform the long collection run.**

---

# Collector commands

Implement concepts equivalent to:

```text
dexfrag collect
dexfrag dataset inspect
dexfrag dataset coverage
```

The collector must be:

- append-friendly,
- resumable,
- crash-safe,
- deduplicated by exact patch identity,
- bounded by configurable count/time/disk limits,
- deterministic when seeded,
- safe to interrupt with Ctrl+C,
- explicit about renderer and feature versions,
- explicit about acquisition source,
- explicit about parent/lineage for mutation-derived samples.

---

# Acquisition sources

Support at least:

## Broad structured exploration

Cover legal parameter space intentionally.

Use the Phase 1 structural report.

Avoid naïve independent uniform sampling when it produces mostly silent/degenerate patches.

Do not over-prune merely because a region looks weird.

## Random legal exploration

Required baseline and diversity source.

## Local mutation

Mutate around existing valid observations.

Record parent patch / acquisition lineage.

Use several mutation families rather than one undifferentiated random nudge.

## Structure-aware exploration

Sample across:

- algorithms/topologies,
- carrier/modulator patterns,
- coarse ratio families,
- feedback regimes,
- output-level patterns,
- other free research-profile parameters.

This is acquisition coverage, not an optimizer.

## Historical import

Optionally import trustworthy existing DexFraggler native observations after validating:

- exact patch identity,
- renderer provenance,
- feature provenance,
- reference conditions.

Do not import old target scores as native truth.

---

# Degenerate and failure handling

Do not silently discard failures.

Classify attempts/observations such as:

- valid,
- silent,
- near-silent,
- clipped/invalid,
- unstable/nonstationary for the chosen profile,
- render failure,
- duplicate.

Silent and poor patches may still be informative.

The collector should expose their rate and let acquisition policies avoid wasting nearly all compute on them.

Store enough metadata to reproduce or investigate failures without polluting the valid observation table.

---

# Coverage instrumentation

Report at least:

- total unique observations,
- observations by algorithm,
- observations by algorithm topology/structure,
- observations by acquisition source,
- observations by lineage/family,
- duplicate attempts,
- silent/degenerate rate,
- key parameter histograms,
- carrier-count/output-level distributions,
- coarse/fine/detune distributions,
- feedback distribution,
- spectral/harmonic diversity summaries,
- collection rate,
- dataset disk size,
- renderer version distribution,
- feature-version distribution.

Make coverage visible in CLI and TensorBoard where useful.

---

# Dataset splits

Create stable train/validation/test assignment.

Requirements:

- deterministic,
- no exact patch leakage,
- reproducible after append,
- final test set protected.

Additionally create a stricter benchmark split or grouping that prevents trivial leakage from local mutation families.

Examples:

- acquisition lineage grouping,
- seed-family grouping,
- structural-family holdout experiment.

Do not allow a mutation child in test to be judged as "generalization" if a nearly identical parent is in train without clearly labeling that benchmark.

---

# Native observation vs target pair data

This phase collects:

```text
patch → native behavior
```

It does **not** need generated target wavetables to create permanent truth.

Target/patch scores can later be derived from native observations without rerendering.

Do not contaminate the dataset schema with target-generator metadata.

---

# Bounded Codex smoke test

Codex may collect at most **64 new native observations**.

Use the tiny set only to verify:

- resume,
- dedupe,
- lineage,
- failure classification,
- coverage reporting,
- split assignment,
- Parquet append behavior,
- version/provenance handling.

Do not interpret it as a real training corpus.

---

# Operator-ready profiles

Provide documented bounded configurations for:

- quick calibration,
- capped observation count,
- capped wall-clock duration,
- capped disk usage,
- extended/overnight run,
- resume.

No unbounded default.

---

# STOP gate

Stop when:

1. collection can run, stop, and resume,
2. exact duplicates are not rerendered,
3. mutation lineage is recorded,
4. split assignment is stable,
5. stricter family/lineage holdout can be generated,
6. coverage reports include structural coverage,
7. degenerate/failure handling is visible,
8. acquisition source is recorded,
9. bounded smoke collection passes,
10. operator instructions explain the first meaningful collection.

### Required phase report

Report:

- smoke observation count,
- valid/degenerate/failure counts,
- duplicate behavior,
- observed throughput,
- dataset size,
- coverage gaps,
- split/lineage policy,
- schema/version information,
- exact operator collection command,
- exact report the operator should bring back before Phase 3.

**Do not run a long collection automatically.**
**Do not begin forward-model implementation until the operator has collected and reviewed a real corpus.**
