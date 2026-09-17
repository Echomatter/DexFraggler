# Phase 6 — Active Learning + Hard Black-Box Targets + Reachability Estimation

## Objective

Close the learning loop and use failures intelligently.

Build:

```text
current dataset/models/search
        ↓
choose informative targets / patches
        ↓
bounded native verification
        ↓
append permanent observations
        ↓
retain derived search evidence
        ↓
retrain later
```

Also build honest empirical triage for:

- likely search-limited targets,
- likely representation-limited targets,
- uncertain targets.

Do **not** claim mathematical proof of the DX7 waveform manifold boundary.

---

# Active acquisition sources

Use signals such as:

- forward-model uncertainty,
- proposer uncertainty,
- compatibility uncertainty,
- forward/compatibility/native disagreement,
- proposer collapse,
- weak structural coverage,
- weak parameter coverage,
- repeated search failure,
- repeated search plateau,
- high-value black-box targets,
- search regions where one native render can resolve many candidate rankings.

Every new rendered patch becomes a normal permanent `NativeObservation`.

Record acquisition source.

---

# Generated hard wavetables

Treat generated wavetables as a black-box query corpus.

Input visible to the model/search:

```text
2048 samples per frame
```

Nothing else about construction.

Do not provide:

- generator identity,
- seed,
- recipe,
- waveform names,
- source family,
- multiplex count,
- "easy/hard" labels,
- privileged ordering information.

Opaque table/frame IDs are for bookkeeping only.

Randomize query ordering where useful.

---

# What generated targets are and are not

They are initially:

```text
target waveform → unknown best legal patch
```

Therefore they are not ordinary supervised patch labels.

Use them for:

- evaluation,
- adversarial curriculum,
- active target selection,
- search stress testing,
- hard-negative generation.

After search/native verification:

- rendered patches enter the permanent patch→native corpus,
- target/patch scores remain derived experiment data,
- target solution bundles can help later proposer/search training.

Do not duplicate native observations because one patch was evaluated against many generated targets.

---

# Search-trace learning

Use Phase 5 traces to mine:

- successful move operators,
- failed move operators,
- surrogate/native disagreements,
- hard negatives,
- structural basins,
- restart productivity,
- local neighborhoods with unexplained error.

This is the main feedback channel for improving:

- proposer,
- compatibility scorer,
- active acquisition,
- move scheduling.

Do not let the system blindly reinforce only its existing best basin.

---

# Reachability / representation-limit estimation

## The problem

A poor best match can mean:

1. the solver is weak,
2. the models are weak,
3. the target is underrepresented in training,
4. the legal DX7 manifold cannot reproduce it closely,
5. or some combination.

The system should estimate which explanation is plausible.

## Evidence

Use:

- best native match found,
- native budget,
- number/diversity of restarts,
- algorithm/topology diversity explored,
- best-so-far improvement slope,
- time/steps since last improvement,
- nearest known native observation distance,
- model uncertainty,
- surrogate/native disagreement,
- repeated failure across different search families,
- results from higher-budget benchmark runs.

## Honest outputs

Prefer fields such as:

```text
best_native_match_found
native_budget
search_diversity
estimated_attainable_range
representation_limited_probability
search_limited_probability
uncertain_probability
confidence
evidence_summary
```

Names may vary.

The estimate is empirical and budget-conditioned.

Do not use the word "proven ceiling" without a proof.

Best found is evidence, not an upper bound on the true optimum.

---

# Reachability model

Do not start with an elaborate neural model.

First implement a transparent estimator from search evidence.

Only add a learned reachability/ceiling model after enough search traces exist.

If a learned model is added:

- train on budget-aware trace summaries,
- avoid pretending best-known = true optimum,
- calibrate on held-out targets,
- report uncertainty.

---

# Baseline active acquisition comparison

Compare active acquisition with:

- broad structured acquisition,
- random legal acquisition,
- local mutation acquisition.

Measure downstream benefit:

- forward validation,
- proposer quality,
- compatibility ranking,
- search quality at fixed native budget,
- hard-target quality.

Active learning is not assumed better.

---

# Safe operator rhythm

Do not run acquisition and retraining forever in one opaque loop.

Use:

```text
acquire bounded batch
    ↓
stop
    ↓
inspect
    ↓
retrain/resume
    ↓
evaluate
    ↓
decide whether another batch is justified
```

This makes regressions visible.

---

# Bounded Codex smoke

Codex may add at most:

- **16 new native observations**.

Reachability smoke should preferably reuse stored search traces.

If additional native renders are absolutely necessary, they must fit within the same bounded smoke budget rather than adding a second unbounded allowance.

---

# STOP gate

Stop when:

1. active target/patch selection works,
2. black-box target adapter proves no generator metadata enters models,
3. new observations append safely,
4. search traces are mined into hard negatives/evidence,
5. active acquisition is benchmarkable against non-active baselines,
6. empirical reachability triage produces honest budget-conditioned output,
7. smoke adds no more than 16 native observations,
8. long-run acquire/retrain steps are documented but not launched.

### Required phase report

Report:

- acquisition policy,
- selected smoke cases,
- why each was selected,
- new observations,
- before/after metrics if available,
- reachability estimator design,
- examples classified search-limited / representation-limited / uncertain,
- caveats,
- exact operator commands for bounded active cycles,
- evidence to bring back before Phase 7.

**Do not begin product/plugin work.**
