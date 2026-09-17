# Phase 4 — Inverse Proposer

## Objective

Build:

```text
2048-sample target waveform/features
        ↓
multiple plausible legal DX7 patch hypotheses
```

The proposer is a **proposal generator**, not the final solver.

DX7 synthesis is many-to-one.

A target may have:

- many good patches,
- one narrow family of good patches,
- no very close legal patch.

Do not model the task as one unique regression target.

**Codex performs only a tiny sanity training run.**
**The operator performs meaningful proposer training separately.**

---

# Preconditions

Review the real Phase 3 report.

Proceed only if the forward model is useful for cheap candidate ranking.

If not, improve Phase 2/3 first.

Do not hide a bad surrogate inside a more complicated inverse model.

---

# Input boundary

The proposer sees:

- 2048 waveform samples,
- phase-bearing waveform-derived harmonics,
- deterministic waveform statistics.

It must not see:

- target generator name,
- recipe,
- seed,
- creation family,
- generator difficulty,
- privileged labels.

Add tests around the dataset/model adapter.

---

# Initial architecture

Start compact:

- small 1D CNN or similarly small waveform encoder,
- harmonic/statistics branch,
- shared latent representation,
- parameter-specific output heads.

Predict distributions for:

- algorithm,
- feedback,
- each operator's searchable parameters.

Use categorical/ordinal treatment where appropriate.

Use Phase 1 topology metadata to inform decoding or feature embeddings, but do not create 32 separate models.

---

# One-to-many training rule

A native observation provides:

```text
waveform ← one known legal patch
```

That patch is one valid witness.

It is not proof that other legal patches are wrong.

Therefore:

- do not score exact hidden-patch recovery as the main success metric,
- do not use naive all-parameter MSE as if there were one correct point,
- train distributions or multiple hypotheses,
- evaluate downstream native quality.

Later, verified alternative solutions may be added to derived target-solution data and used to improve proposer training without duplicating native observations.

---

# Multi-solution output

Support candidate counts such as:

- 16,
- 32,
- 64,
- 128,
- 256.

Candidate generation may use:

- sampling,
- beam search,
- structured top-k decoding,
- diversity-aware decoding.

Every candidate must pass canonical DX7 validation.

Track:

- legality rate,
- unique candidate rate,
- exact duplicate collapse,
- algorithm diversity,
- topology diversity,
- parameter diversity,
- pairwise distance among hypotheses.

---

# Surrogate ranking

Integrate the Phase 3 forward model:

```text
target
  ↓
proposer
  ↓
candidate set
  ↓
forward surrogate
  ↓
predicted target similarity ranking
```

Native renderer remains final authority.

This phase does not yet implement the full structured search engine.

---

# Baselines

Evaluate the proposer against:

- random legal candidate generation,
- broad structured candidate generation,
- nearest native observation / nearest-neighbor retrieval,
- old retained predictor if cheap to preserve as a benchmark.

Do not rely on exact-patch recovery.

---

# Native-budget evaluation

For a held-out native observation:

1. hide the patch,
2. use waveform/features only,
3. propose candidates,
4. deduplicate,
5. rank by forward model,
6. native-render a bounded set,
7. measure native similarity.

Evaluate at budgets such as:

- 1,
- 4,
- 8,
- 16,
- 32,
- 64.

The important chart:

```text
native budget → best native match
```

---

# Failure examples

Save examples where:

- proposer misses the generating algorithm family,
- proposer generates low diversity,
- forward ranker chooses poor candidates,
- strong candidate exists low in proposer rank,
- target appears far from the learned/native manifold.

These become Phase 5/6 evidence.

---

# Tiny Codex sanity run only

At most:

- **3 epochs**
- **2,048 observations**

Then a very small bounded inference/native verification test.

Mechanics only.

---

# Operator controls

Provide:

- checkpoint/resume,
- early stopping,
- max epochs,
- max steps,
- wall-clock limit,
- candidate count,
- random seed,
- fixed native evaluation budget.

---

# STOP gate

Stop when:

1. proposer training works end-to-end,
2. candidates are legal,
3. diversity is measurable,
4. forward ranking works,
5. bounded native verification works,
6. checkpoints/resume work,
7. TensorBoard diagnostics exist,
8. native-budget comparison exists.

### Required phase report

Report:

- architecture,
- parameter count,
- smoke behavior,
- legality/diversity,
- bounded native result,
- failure examples,
- exact operator training command,
- exact post-training evaluation command.

**Do not run long proposer training automatically.**
**Do not implement the Phase 5 structured search engine until meaningful proposer results are reviewed.**
