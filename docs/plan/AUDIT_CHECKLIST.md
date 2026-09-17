# DexFraggler ML + Structured Search Phase Pack — Audit Checklist

## Audit result

This pack preserves the original ML rebuild constraints and adds the missing structured-search/reachability architecture.

No Codex phase requires a long run.

All meaningful collection, training, search, and active acquisition remains operator-started after a hard STOP gate.

---

# Original constraints preserved

## Ground truth

- legal DX7 patch representation,
- exact patch identity,
- VCED/SysEx,
- native renderer,
- renderer provenance/hash,
- A2/A3/A4,
- phase-bearing harmonic data,
- native verification as final authority.

## Canonical data

- 2048-sample waveform,
- 256×2048 wavetable,
- no 32-frame reduction,
- algorithm is ordinary patch data, not a row,
- Parquet observation schema,
- permanent observation vs derived target-score separation.

## Dataset quality

- exact deduplication,
- crash safety,
- resume,
- acquisition source,
- degenerate/silent classification,
- coverage reports,
- deterministic splits,
- protected test data,
- leakage prevention.

## Forward model

- simple first architecture,
- categorical/discrete encoding,
- checkpoint/resume,
- TensorBoard,
- held-out evaluation,
- per-algorithm analysis,
- overfit/no-learning signals.

## Inverse proposer

- multimodal candidate generation,
- legality validation,
- diversity metrics,
- forward-surrogate ranking,
- fixed native-budget evaluation.

## Active learning

- uncertainty/failure-driven acquisition,
- comparison to non-active baselines,
- permanent reuse of native observations.

## Wavetable evaluation

- all 256 frames,
- candidate-pool deduplication,
- one native render scored against all 256 frames,
- fixed native budgets,
- quality and coverage metrics.

## Operator safety

- bounded commands,
- Ctrl+C expectation,
- checkpoints,
- resume,
- no unbounded defaults,
- hard STOP gates.

---

# New constraints added

## Black-box target rule

- model/search sees waveform-derived input only,
- no generator recipe,
- no seed,
- no generation family,
- no hidden difficulty,
- no generator-specific labels,
- no generator ordering as semantic input.

## Structural reduction / Lire principle

- inventory exact search structure before learning,
- derive algorithm topology features,
- distinguish searchable/fixed/derived fields,
- exact/reversible reductions only,
- permanent patch identity never merged by sound or structural similarity,
- current analytic/Jacobian math may be retained as validated move operators.

## AZDecrypt-style search layer

- inverse proposer is not the final solver,
- multiple restarts,
- distinct search families,
- outer structural moves,
- inner refinement moves,
- preserved elites,
- stagnation detection,
- restart logic,
- fixed native-render budgets,
- full search traces.

## Compatibility / energy scorer

- target + patch → expected native error/usefulness,
- hard-negative pair construction,
- benchmark against forward-derived deterministic scoring,
- keep only if useful.

## Reachability

- distinguish search-limited vs likely representation-limited vs uncertain,
- empirical/budget-conditioned only,
- no false global-optimum claims,
- failures retained as training evidence.

## Hard target curriculum

- generated wavetables used as black-box query/adversarial targets,
- all 256 frames retained,
- no provenance leakage,
- verified patches enter permanent observation corpus,
- target/patch solutions remain derived data.

## Joint wavetable budget allocation

- global candidate pool,
- exact dedupe,
- candidate utility across all 256 frames,
- every native render rescored against all 256,
- quality vs global native budget.

---

# Smoke-run caps

## Phase 1

- Neural training: none.
- Large collection: none.
- Allowed: tests, a few renders, structure audit.

## Phase 2

- New native observations: **≤64**.

## Phase 3

- Forward training: **≤3 epochs** and **≤2,048 observations**.

## Phase 4

- Proposer training: **≤3 epochs** and **≤2,048 observations**.

## Phase 5

- Compatibility training: **≤3 epochs**, data derived from **≤2,048 observations**.
- Structured-search smoke: **≤16 new native renders total**.

## Phase 6

- Active-learning smoke: **≤16 new native observations**.
- Reachability should reuse stored traces where possible.

## Phase 7

- Full-wavetable smoke: **≤8 new native renders total**.

---

# Completeness checks

Before declaring the pack complete, confirm:

### Native/data
- [ ] exact patch key
- [ ] exact renderer hash/provenance
- [ ] A2/A3/A4
- [ ] 2048 canonical representation
- [ ] phase-bearing features
- [ ] 256×2048 import
- [ ] Parquet round trip
- [ ] target/native data separation

### Structure
- [ ] topology descriptors all 32 algorithms
- [ ] fixed/searchable/derived parameters identified
- [ ] reduction reversibility tests
- [ ] no permanent identity merging
- [ ] analytic moves parity-tested if retained

### Acquisition
- [ ] resume
- [ ] Ctrl+C
- [ ] count/time/disk bounds
- [ ] exact dedupe
- [ ] degenerate classification
- [ ] lineage
- [ ] coverage
- [ ] deterministic split
- [ ] stricter lineage/family benchmark

### Forward
- [ ] checkpoint/resume
- [ ] TensorBoard
- [ ] validation
- [ ] family holdout
- [ ] ranking usefulness

### Proposer
- [ ] multi-candidate output
- [ ] legal candidates
- [ ] diversity
- [ ] fixed native-budget evaluation

### Compatibility
- [ ] hard negatives
- [ ] forward-derived baseline
- [ ] ranking/calibration evaluation

### Search
- [ ] diverse starts
- [ ] outer moves
- [ ] inner moves
- [ ] restarts
- [ ] stagnation
- [ ] preserved elites
- [ ] native budget enforcement
- [ ] trace persistence
- [ ] equal-budget baselines

### Reachability
- [ ] budget-conditioned
- [ ] empirical only
- [ ] uncertainty
- [ ] search-limited/representation-limited/uncertain
- [ ] no "proven ceiling" wording

### Black-box targets
- [ ] no generator metadata enters model
- [ ] opaque hashes/indices only for bookkeeping
- [ ] generated targets initially unlabeled
- [ ] verified patch observations remain permanent truth

### Wavetable
- [ ] all 256 frames
- [ ] global candidate pool
- [ ] exact dedupe
- [ ] global candidate utility
- [ ] one render → 256 scores
- [ ] fixed global native budget
- [ ] quality-vs-budget report

---

# Items intentionally deferred

These remain out of scope until research evidence justifies productization:

- VST/AUv3/LV2 implementation,
- production plugin UI,
- realtime audio-thread constraints,
- final wavetable instrument architecture,
- trained-model deployment packaging,
- quantization,
- ONNX/libtorch,
- distributed-weight licensing strategy,
- final consumer sample-import UX.

---

# Handoff discipline

Give Codex only:

1. `00_MASTER_OVERVIEW.md`
2. the current phase file
3. `CODEX_HANDOFF_PROMPT.md` as wrapper

Do not authorize future phases early.
