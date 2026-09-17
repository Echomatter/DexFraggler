# Phase 5 — Compatibility Scorer + AZDecrypt-Style Structured Search

## Objective

Add the missing layer between "propose" and "native verify."

Build:

```text
target
  ↓
multiple proposer starts
  ↓
structured multi-start search
  ↓
cheap compatibility / forward scoring
  ↓
bounded native verification
```

This phase is where DexFraggler stops treating the inverse model as the solver.

---

# Part A — Compatibility / energy scorer

## Purpose

Learn:

```text
(target waveform, candidate patch) → expected native error / candidate usefulness
```

This model should act like a fast fitness function.

It is never native truth.

---

# Pair-data construction

Use existing native observations to derive labels without rerendering.

Example:

```text
target = native waveform from observation A
candidate = patch from observation B
label = deterministic native target/observation score
```

Sample pair types deliberately:

- correct/self pairs,
- very strong alternatives,
- near misses,
- same-algorithm hard negatives,
- same-topology hard negatives,
- different-algorithm plausible negatives,
- clearly wrong negatives,
- silent/degenerate negatives when useful.

Avoid a training set dominated by trivial wrong pairs.

Later, add search-generated hard negatives.

---

# Compatibility model

Start small.

Possible structure:

- target waveform encoder,
- candidate patch/topology encoder,
- fusion MLP,
- predicted native loss / rank score,
- optional uncertainty/calibration head.

Benchmark against:

```text
candidate patch
    ↓
forward model
    ↓
predicted waveform
    ↓
deterministic target comparison
```

The direct compatibility model must earn its place.

Keep it if it improves:

- ranking accuracy,
- throughput,
- calibration,
- or search quality.

---

# Compatibility smoke training

Codex may train at most:

- **3 epochs**
- on pair data derived from at most **2,048 native observations**.

No long run.

---

# Part B — Structured search

## Search starts

Create diverse initial states from:

- highest proposer ranks,
- diversity-selected proposer samples,
- nearest native observations,
- structured legal baseline,
- random legal baseline,
- validated historical strong candidates where appropriate.

Each restart must have an ID and source.

Do not let every start immediately collapse to the same mode.

---

# Outer search — structural hypotheses

Implement distinct large-move operators for hypotheses such as:

- algorithm/topology change,
- effective active-operator pattern,
- carrier/modulator participation,
- coarse frequency-ratio family,
- feedback regime,
- oscillator mode if searchable.

These are basin-changing moves.

Do not encode them as just "mutate a random integer."

---

# Inner search — local refinement

Implement distinct smaller moves such as:

- output-level ± changes,
- fine-frequency changes,
- detune changes,
- feedback ± changes,
- nearby coarse ratio changes,
- operator activation/deactivation via legal output-level behavior,
- validated analytic level fitting,
- Jacobian-guided proposals,
- local mixed discrete moves.

All candidates must remain legal.

---

# Use current analytic math where it helps

Inspect existing analytic/Jacobian/fitting code.

If parity is established, expose it as one move family.

Do not make it mandatory.

Benchmark:

- ordinary discrete refinement,
- analytic refinement,
- hybrid.

The structural-search architecture must not depend on a fragile port.

---

# Search state

Each state should carry:

- exact patch,
- structural signature,
- cheap scores,
- native score if known,
- parent,
- move operator,
- restart/family ID,
- visit count / stagnation metadata.

---

# Multi-start behavior

Support:

- multiple restarts,
- preserved global elite,
- preserved per-family elites,
- bounded beam/candidate pool,
- stagnation detection,
- restart on plateau,
- move-family adaptation,
- deterministic seeded runs,
- controlled stochastic/uphill escape only when bounded and measurable.

Do not discard good candidates merely because a different restart becomes active.

---

# Candidate dedupe

Dedupe exact patch identity before native render.

Search-state structural equivalence may prevent redundant exploration, but exact legal patch identities remain distinct in permanent data.

---

# Scoring cascade

Benchmark variants around:

```text
legal candidate
    ↓
structural duplicate/filter checks
    ↓
compatibility scorer
    ↓
forward-model score
    ↓
candidate pool / beam
    ↓
native verification
```

Use cheap scoring aggressively.

Use native rendering sparingly.

---

# Native acceptance

Native verification is final.

A surrogate improvement that fails native verification is not a solved improvement.

Log disagreement.

Disagreement is useful Phase 6 active-learning data.

---

# Search trace schema

Record:

- target,
- restart,
- search family,
- parent candidate,
- proposed patch,
- move type,
- cheap scores,
- native score if rendered,
- acceptance,
- best-so-far,
- native budget,
- model/checkpoint versions,
- structure/search versions,
- seed.

Search traces must survive process interruption.

---

# Search baselines

At identical native budgets compare:

1. random legal,
2. broad structured random,
3. local mutation,
4. nearest-neighbor/retrieval,
5. proposer only,
6. proposer + forward ranking,
7. proposer + compatibility ranking,
8. proposer + structured search,
9. proposer + structured search + analytic moves.

Do not compare methods that spent different native budgets without clearly normalizing.

---

# Search metrics

Report:

- best native match,
- median best match across targets,
- worst target,
- quality vs native budget,
- native renders,
- cheap candidates evaluated,
- restarts used,
- family diversity,
- time,
- surrogate/native rank correlation,
- surrogate/native disagreement,
- move operator success rate,
- improvement contribution by move family,
- plateau/restart behavior.

---

# Bounded Codex search smoke

At most:

- **16 new native renders total**.

Use a very small target set.

The purpose is to prove:

- proposer start handoff,
- search move legality,
- trace persistence,
- restarts,
- scorer integration,
- native verification,
- budget enforcement.

Do not claim search quality from the smoke result.

---

# STOP gate

Stop when:

1. compatibility training/evaluation works,
2. hard-negative pair generation works,
3. structured outer/inner move families exist,
4. multi-start/restart logic works,
5. exact dedupe works,
6. search traces persist,
7. native budget enforcement is tested,
8. fixed-budget baselines run,
9. bounded smoke stays within 16 new native renders,
10. operator commands for meaningful search benchmarking are documented.

### Required phase report

Report:

- compatibility architecture and ranking metrics,
- whether compatibility adds value over forward-derived scoring,
- search move families,
- search/restart configuration,
- smoke native budget used,
- trace/report paths,
- baseline methods,
- exact operator command for the real fixed-budget search benchmark,
- evidence to bring back.

**Do not begin active acquisition automatically.**
