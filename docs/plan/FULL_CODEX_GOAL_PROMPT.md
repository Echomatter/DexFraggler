# DexFraggler — Full Codex Goal Prompt

This file is the single high-level goal prompt. It is intentionally comprehensive.

For implementation, pair it with **only the current phase file** and require Codex to stop at that phase's gate.

---

# DexFraggler ML + Structured Search Rebuild — Master Overview

## Mission

Rebuild DexFraggler as a focused Python/PyTorch research system that learns and searches the legal DX7 waveform space efficiently.

The system must learn three complementary relationships:

1. **Forward relationship:** legal DX7 patch parameters → native rendered waveform/features.
2. **Inverse relationship:** target waveform/features → multiple promising legal DX7 patch candidates.
3. **Compatibility relationship:** target waveform/features + candidate patch → expected native error / usefulness.

Then it must close the loop:

```text
target waveform
    ↓
inverse proposer
    ↓
multiple legal hypotheses
    ↓
structured multi-start search
    ↓
cheap compatibility / forward ranking
    ↓
native Dexed verification
    ↓
verified result + search trace
    ↓
permanent observation / derived target result
    ↓
active acquisition and later retraining
```

The trained models, structured search engine, reproducible data pipeline, and evaluation evidence are the deliverables of this research rebuild.

The old DexFraggler 32×32 application is not the architecture to preserve.

---

# Core design principles

## 1. Native truth remains the authority

The native Dexed Mark I renderer is the ground-truth oracle.

Learned models may:

- propose,
- rank,
- estimate,
- prioritize,
- predict,
- suggest search moves.

They may not declare a patch solved without native verification.

The existing native renderer/provenance work is valuable and should be preserved.

Current reference behavior to preserve unless the repository itself proves a newer contract:

- 48 kHz rendering,
- velocity 100,
- notes 45 / 57 / 69 (A2/A3/A4),
- 7,200-sample onset offset,
- 4,096-sample native capture,
- exact legal patch identity from the existing VCED/SysEx representation,
- executable/source provenance and SHA-256,
- deterministic rendering checks.

Do not silently redefine the oracle.

## 2. Learn from the Leaning Tower of Lire: remove fake degrees of freedom before searching

The block-stacking problem is useful here as a design analogy, not as a literal algorithm.

Its lesson is:

> When exact structure or an invariant can collapse a search dimension, use the structure instead of asking a searcher or neural network to rediscover it.

For DexFraggler this means creating an explicit **structural-reduction layer** before expensive search.

It should inventory and exploit only relationships that are proven and tested, including where useful:

- legal parameter domains,
- fixed research-profile parameters,
- DX7 algorithm routing topology,
- carrier/modulator roles,
- graph parent/child relationships,
- feedback membership,
- operator branches,
- exact symmetries or equivalent topology descriptions,
- parameters that can be analytically or deterministically fitted,
- validated sensitivity/Jacobian information,
- reversible canonical forms for search-state comparison.

Important boundary:

- exact legal patch identity is permanent and must never be merged merely because two patches sound similar,
- structural equivalence metadata may reduce duplicated search effort,
- a reduction must retain a reversible path to the original legal patch representation,
- do not invent a mathematical reduction because it seems plausible,
- every reduction requires tests or evidence.

The current analytic fitting/Jacobian machinery is therefore potentially valuable as a deterministic inner-search move generator even though the old application architecture is being retired.

## 3. Learn from AZDecrypt: a strong proposer is not the solver

AZDecrypt is useful as a search-design analogy because it combines:

- a strong fitness function,
- specialized solver/mutation families,
- repeated restarts,
- multiple candidate hypotheses,
- and, for some problems, an outer hill climber wrapped around an inner hill climber.

Translate that pattern into DexFraggler.

Do **not** build:

```text
waveform → one neural prediction → done
```

Build:

```text
waveform
   ↓
many plausible starts
   ↓
outer structural hypotheses
   ↓
inner numerical/discrete refinement
   ↓
stagnation detection / restart / family change
   ↓
native verification
```

The inverse model tells the solver where to start.

The solver handles ambiguity, local minima, discrete legal constraints, and competing structural explanations.

## 4. The search objective is native quality per expensive native render

CPU-only surrogate work can be plentiful.

Native renders are the expensive currency.

Every benchmark involving search must therefore show quality as a function of native budget.

Examples:

```text
native budget   native match quality
1               ...
4               ...
8               ...
16              ...
32              ...
64              ...
```

Do not claim a search improvement because it evaluates more native candidates.

## 5. Black-box target rule

External target waveforms, including generated wavetables, are black boxes.

The model-facing target contract is:

```text
2048 waveform samples
    ↓
features derived only from those samples
```

The model/search system must not receive:

- generator name,
- waveform recipe,
- seed,
- multiplex count,
- mathematical source family,
- saw/square/triangle labels unless the target itself is explicitly part of a labeled benchmark,
- generation order as a semantic hint,
- target difficulty labels from the generator,
- any explanation of how the waveform was made.

For bookkeeping, opaque target hashes, file IDs, table/frame indices, and experiment IDs are allowed, but they must never be model features.

Generated difficult wavetables are an adversarial curriculum/query set, not privileged labeled data.

## 6. Canonical waveform and wavetable sizes are fixed

Canonical periodic waveform frame:

```text
2048 samples
```

Canonical wavetable:

```text
256 frames × 2048 samples
```

A 256-frame wavetable is 256 real targets.

Do not reduce it to 32 frames.

Do not map frames to DX7 algorithms.

Do not recreate the old algorithm-row architecture.

Algorithm is an ordinary legal patch parameter and a structural feature of the same model/search system.

## 7. Permanent truth and target-specific experiment data are separate

Permanent knowledge:

```text
unique legal DX7 patch → actual native behavior
```

Derived experiment knowledge:

```text
target waveform × native observation → score
target waveform × candidate patch → search trace / ranking / verification result
```

One unique native patch should be rendered once under a fixed oracle version whenever possible, then reused against many targets.

For a 256-frame wavetable:

> Render the candidate once, then score that native observation against all 256 target frames.

Do not duplicate the native observation 256 times.

---

# Hard architectural decisions

- Python-first research system.
- PyTorch for learned models.
- Native Dexed Mark I rendering remains ground truth.
- Canonical waveform frame is 2048 samples.
- Canonical wavetable is 256 × 2048.
- All 256 frames are evaluated.
- Algorithm is a categorical patch parameter plus derived graph/topology features, not a row or separate model.
- Preserve phase-bearing harmonic information.
- One unique native patch creates one permanent observation.
- Target-specific similarity/search scores are derived experiment data.
- TensorBoard is the initial instrumentation UI.
- No product UI, plugin UI, VST/AUv3/LV2 deployment, or realtime-audio work during this rebuild.
- No backwards-compatibility shims for obsolete 32×32 DexFraggler architecture.
- Do not destroy unrelated existing repository work merely to avoid compatibility work; isolate the new research system cleanly.
- Do not make the system depend on the target generator.
- Do not make the inverse proposer the final solver.
- Do not claim global optimality or a proven waveform "ceiling" without a mathematical certificate.

---

# Critical execution rule

**Codex must never perform a long collection, training, active-learning, or search run as part of a build phase.**

Codex may perform only bounded correctness work:

- unit/integration tests,
- a few native renders,
- tiny fixture data generation,
- tiny training sanity checks,
- tiny bounded search tests,
- one short end-to-end smoke validation.

Every potentially long operation must be:

- exposed as an operator command,
- bounded by count/time/native-budget/disk limits,
- checkpointed,
- interruptible with Ctrl+C,
- resumable,
- explicit about output paths and experiment IDs.

No command may default to "run forever."

### Global smoke limits

Unless a test requires less:

- Native collection smoke: at most **64 new observations**.
- Forward-model smoke training: at most **3 epochs** on at most **2,048 observations**.
- Inverse-proposer smoke training: at most **3 epochs** on at most **2,048 observations**.
- Compatibility-model smoke training: at most **3 epochs** using data derived from at most **2,048 observations**.
- Search-engine smoke: at most **16 new native renders total**.
- Active-learning smoke cycle: at most **16 newly rendered patches**.
- Full-wavetable smoke solve: at most **8 new native renders**.

These prove mechanics only.

Codex must STOP after each phase gate and report the exact operator command for the meaningful experiment.

---

# Preserve from the current repository

Carry forward or wrap only components that remain truth or directly useful:

- legal DX7 patch validation,
- exact VCED/SysEx representation and identity,
- native Dexed renderer,
- native renderer provenance,
- A2/A3/A4 reference capture,
- native scoring mathematics,
- complex harmonic extraction,
- phase-aware normalization/alignment that survives validation,
- deterministic feature extraction,
- relevant tests,
- source/license/provenance material,
- calculation-model code that is demonstrably useful as a baseline or search move generator,
- validated analytic derivatives/Jacobian and damped fitting behavior where they remain correct.

Inspect current files before rewriting behavior. Likely useful sources include:

```text
native/
models/
runner/reference.mjs
public/core.mjs
docs/calculation-models.md
docs/analytic-fitting.md
```

Do not blindly transliterate JavaScript into Python. Preserve validated behavior with parity tests where it matters.

---

# Retire from the new research architecture

Do not preserve merely for compatibility:

- 32×32 Waveform Table architecture,
- 32-frame wavetable reduction,
- anchor columns,
- algorithm rows,
- Path / Analyzer / Interpolation workers as workflow concepts,
- named scans as the new dataset abstraction,
- row leases,
- tray app as research orchestration,
- custom activity/map UI,
- old scheduler abstractions,
- old predictor/retrieval system once replaced by measured baselines,
- product/plugin/realtime host concerns.

Old components may remain in the repository if unrelated work depends on them. They are not design constraints on the new Python research path.

---

# Canonical research objects

## CanonicalPatch

Contains:

- exact legal patch identity,
- exact VCED/SysEx bytes required by the native renderer,
- algorithm,
- feedback,
- six operators,
- coarse,
- fine,
- detune,
- oscillator mode,
- output level,
- and every additional parameter included in the chosen stationary-waveform research profile.

The implementation must explicitly separate:

1. free/searchable parameters,
2. fixed reference parameters,
3. derived structural/topology features.

Do not let dynamic envelope/LFO/etc. fields silently vary if the experiment is intended to model stationary timbre.

Different legal patches must remain distinct permanent observations.

## AlgorithmStructure

Derived from the legal algorithm, not independently user-authored.

Contains useful topology descriptors such as:

- carrier mask,
- modulator mask,
- parent/child adjacency,
- path depth,
- branch membership,
- feedback operator/path,
- operator role descriptors,
- topology/symmetry tags.

Start with transparent fixed descriptors.

Do not begin with a graph neural network unless a simpler representation demonstrably fails.

## NativeObservation

A permanent record from rendering one unique legal patch under fixed reference conditions.

Contains:

- canonical patch key,
- exact patch bytes,
- normalized patch parameters,
- algorithm structure/version,
- A2/A3/A4 native captures/descriptors,
- 2048-sample canonical periodic representation where applicable,
- complex phase-bearing harmonic coefficients,
- harmonic magnitudes,
- RMS/energy/peak,
- deterministic statistics,
- renderer provenance/hash,
- feature extractor version,
- acquisition source,
- timestamp,
- validity/degenerate classification.

## CanonicalWaveform

Contains only waveform-derived information:

- 2048 normalized periodic samples,
- phase-bearing harmonic representation,
- magnitudes,
- deterministic statistics,
- feature version.

No generator metadata.

## CanonicalWavetable

Shape:

```text
[256, 2048]
```

All frames are retained.

## TargetRecord

Opaque experiment target bookkeeping:

- target hash,
- source file hash if relevant,
- table/frame index for bookkeeping only,
- canonical waveform,
- feature version.

Generator provenance must not enter the model/search input.

## TargetPatchScore

Derived and reproducible:

- target hash,
- patch key / native observation key,
- scoring version,
- native similarity/error,
- pitch-specific values,
- alignment/phase data where required.

## SearchTrace

Every meaningful search run records enough information to explain how a result was reached:

- target hash,
- restart ID,
- search family,
- parent candidate,
- proposed candidate,
- move operator,
- structural hypothesis,
- surrogate score,
- compatibility score,
- native score if rendered,
- acceptance/rejection reason,
- best-so-far state,
- native budget consumed,
- random seed,
- model/checkpoint versions,
- search configuration version.

This trace is essential for debugging, hard-negative generation, reachability estimation, and active learning.

## TargetSolution

Derived experiment data, not permanent native truth:

- target hash,
- selected patch keys,
- native scores,
- best-so-far curve,
- native budget,
- search/model versions,
- estimated reachability fields,
- search trace reference.

---

# Data storage rules

Prefer append-friendly Parquet for immutable or append-only research data.

At minimum separate:

```text
native_observations/
target_records/
target_patch_scores/
search_traces/
target_solutions/
experiments/
checkpoints/
```

Requirements:

- exact patch-key deduplication,
- renderer version/provenance checks,
- feature-version checks,
- crash safety,
- atomic manifests/checkpoints,
- deterministic split assignment,
- protected final test set,
- no exact-patch leakage,
- explicit acquisition source,
- lineage/source grouping for mutation-derived observations where useful,
- a stricter family/lineage holdout benchmark in addition to the ordinary deterministic split.

Do not store generator recipe fields in target model inputs.

---

# Model 1 — Forward model

Purpose:

```text
legal patch → predicted native waveform/features
```

Start simple:

- categorical embeddings for discrete fields where useful,
- normalized scalar/discrete inputs,
- fixed algorithm topology descriptors,
- shared MLP trunk,
- phase-bearing harmonic/waveform output heads.

The first model should not be a transformer, diffusion model, giant autoregressive model, or GNN unless simpler models fail with evidence.

Evaluate:

- train/validation loss,
- per-pitch error,
- complex harmonic error,
- waveform correlation/residual,
- algorithm-specific error,
- structural-family error,
- worst regions,
- calibration where relevant.

The forward model is a cheap surrogate, not native truth.

---

# Model 2 — Inverse proposer

Purpose:

```text
target waveform → distribution over plausible legal patches
```

It is explicitly many-to-one / one-to-many.

Do not train or evaluate it as if there were exactly one correct patch.

Initial design:

- compact 1D waveform encoder,
- harmonic/statistics branch,
- shared latent representation,
- parameter-specific distribution heads,
- algorithm categorical head,
- structured/legal decoding.

Support configurable candidate generation:

- 16,
- 32,
- 64,
- 128,
- 256.

Track:

- legal candidate rate,
- unique candidate rate,
- structural diversity,
- algorithm diversity,
- patch diversity,
- duplicate collapse,
- native result quality after downstream search.

The known generating patch in a native observation is one valid witness, not the unique truth.

---

# Model 3 — Compatibility / energy scorer

Purpose:

```text
(target waveform, legal candidate patch) → expected native error / usefulness
```

This is the audio-search analogue of a strong fitness function.

It should be trained on:

- correct target/patch pairs,
- near misses,
- hard negatives,
- structurally plausible but wrong candidates,
- clearly wrong candidates,
- later search-generated failures and improvements.

Use existing native observations to derive pair labels without rerendering whenever possible.

A first compatibility model should be small and fast.

Benchmark it against the simpler alternative:

```text
patch → forward model → predicted waveform → deterministic target comparison
```

Keep the direct scorer only if it adds ranking quality, speed, or useful calibration.

Native verification remains final.

---

# Structural-reduction layer

Before or alongside learned search, create explicit deterministic structure utilities.

Required work:

1. enumerate every searchable parameter and legal value,
2. identify fixed reference fields,
3. derive topology features for all 32 algorithms,
4. identify exact symmetries/equivalences that can avoid duplicate search states,
5. preserve reversible mapping to exact patch bytes,
6. expose current analytic fitting/Jacobian functions as optional move generators when validated,
7. create tests proving reductions do not remove legal distinct solutions incorrectly.

Produce a machine-readable `structure_report`.

This layer should answer:

> Which parts of the apparent search space are real, and which parts can be represented more compactly without losing solutions?

---

# Structured search engine

The search engine sits between the proposer and native verification.

## Search starts

Seed restarts from multiple sources:

- top inverse-proposer samples,
- diverse proposer samples,
- nearest native observations,
- broad structured legal baseline,
- random legal baseline,
- selected historical strong candidates if provenance is valid.

Do not let every restart collapse immediately to one proposer mode.

## Outer structural moves

Examples of structural hypothesis changes:

- algorithm/topology family,
- effective active-operator pattern,
- carrier/modulator participation,
- coarse frequency-ratio family,
- feedback regime,
- oscillator mode where part of the research profile.

These moves are relatively large and may change the basin being searched.

## Inner refinement moves

Examples:

- output-level changes,
- fine-frequency changes,
- detune changes,
- feedback increment/decrement,
- nearby coarse changes,
- analytic level fitting,
- Jacobian-guided local proposals,
- local discrete perturbations around a strong patch.

Move sets must always emit legal candidates.

## Nested search behavior

Support:

- multiple concurrent/repeated restarts,
- preserved elites,
- per-family best candidates,
- stagnation detection,
- controlled restart,
- move-family adaptation,
- bounded beam or candidate pool,
- optional limited uphill/stochastic escape when justified,
- deterministic seeds for reproducibility.

Do not make one mutation distribution responsible for every kind of change.

## Scoring cascade

Prefer:

```text
legality / structural dedupe
    ↓
cheap compatibility scorer
    ↓
forward-model comparison
    ↓
candidate pool / beam
    ↓
native verification
```

Exact ordering may be benchmarked, but native work must remain bounded.

## Search benchmark

At fixed native budgets compare:

- proposer only,
- proposer + forward ranking,
- proposer + compatibility ranking,
- proposer + structured search,
- random legal,
- broad structured baseline,
- local mutation baseline,
- nearest-neighbor baseline if retained.

The main research question:

> Does structured model-guided search produce better native matches per native render?

---

# Reachability / representation-limit estimation

Arbitrary black-box targets may not be closely representable by the legal DX7 patch manifold.

Therefore distinguish:

- **search-limited:** better solutions probably exist but the solver is not finding them,
- **representation-limited:** evidence suggests the legal synth space itself may be the bottleneck,
- **uncertain:** insufficient evidence.

Do not claim a proven maximum unless one is mathematically certified.

The system may estimate reachability using:

- nearest known native manifold distance,
- ensemble/model disagreement,
- number and diversity of restarts,
- best-so-far improvement curve,
- plateau duration,
- disagreement between proposer/compatibility/native ranking,
- repeated failure of different structural families,
- search-trace history.

Any learned "ceiling" is budget-conditioned and heuristic.

Report wording must stay honest:

- `best_native_match_found`
- `best_known_at_budget`
- `estimated_attainable_range`
- `representation_limited_probability` or similar calibrated heuristic
- `confidence`
- `evidence`

Never label an empirical plateau as a theorem.

Failures are training data.

---

# Generated hard wavetable curriculum

The generated 256×2048 tables are valuable because they provide a broad, difficult, effectively unbounded pool of target waveforms outside the DX7 parameterization.

Use them as:

- black-box query targets,
- adversarial evaluation targets,
- active-learning curriculum,
- source of hard negatives,
- search stress tests.

Do not teach DexFraggler the generator.

The model sees the waveform, not the recipe.

Do not assume early/easy frames or later/hard frames based on table position.

Randomize training/query sampling when appropriate so generator ordering cannot become a shortcut.

A generated target becomes supervised search evidence only after native candidate evaluation.

Verified patches still enter the permanent dataset only as normal patch → native observations.

Target/patch relationships remain derived experiment data.

---

# Full 256×2048 wavetable solving

A wavetable solve is a joint budget-allocation problem, not 256 separate brute-force searches.

Workflow:

1. ingest all 256 frames,
2. compute waveform-only features,
3. generate proposals for every frame,
4. merge all candidate pools,
5. deduplicate exact patch identities,
6. score each candidate against all target frames cheaply,
7. estimate which native render would improve the largest/most important set of frames,
8. select a bounded candidate,
9. native-render it once,
10. score that native result against all 256 frames,
11. update frame bests,
12. optionally launch structured refinement around high-value candidates,
13. continue until native budget is exhausted.

Candidate selection should consider expected **coverage/improvement across the whole table**, not just one frame.

Report:

- native renders consumed,
- average frame match,
- median frame match,
- worst frame match,
- score distribution,
- percentage above configured thresholds,
- number of unique selected patches,
- frame coverage per patch,
- best-so-far quality vs native budget,
- wall-clock time,
- comparison to baselines,
- representation-limited/uncertain flags where supported.

Do not use generator metadata or interpolation assumptions to solve the table.

---

# CLI target

The mature research CLI should support concepts equivalent to:

```text
dexfrag doctor

dexfrag dataset inspect
dexfrag dataset coverage
dexfrag collect

dexfrag train-forward
dexfrag evaluate-forward

dexfrag train-proposer
dexfrag evaluate-proposer

dexfrag train-compat
dexfrag evaluate-compat

dexfrag structure audit

dexfrag search
dexfrag evaluate-search

dexfrag acquire-active
dexfrag evaluate-reachability

dexfrag solve <wav>
dexfrag evaluate-wavetable

dexfrag monitor
```

Exact names may vary if the resulting CLI is clearer, but the operator workflow must remain obvious.

---

# Phase sequence

1. **Foundation + structural inventory**
   - native truth,
   - canonical objects,
   - black-box target boundary,
   - storage,
   - topology descriptors,
   - structure audit.

2. **Dataset acquisition**
   - broad/resumable collection,
   - coverage,
   - lineage,
   - splits,
   - negative/degenerate handling.

3. **Forward model**
   - patch → native waveform/features.

4. **Inverse proposer**
   - waveform → multiple legal patch hypotheses.

5. **Compatibility scorer + structured search**
   - target/patch fitness,
   - outer/inner moves,
   - multiple restarts,
   - fixed-native-budget search benchmark.

6. **Active learning + reachability**
   - hard-target acquisition,
   - search-trace learning,
   - generated black-box curriculum,
   - empirical search-limited vs representation-limited triage.

7. **Full wavetable solving**
   - all 256 frames,
   - global candidate pool,
   - shared native renders,
   - quality-vs-budget benchmark.

Every phase has a hard STOP gate.

---

# Definition of success

The rebuild succeeds when there is reproducible evidence that:

1. native observations are deterministic and trustworthy,
2. the forward model predicts useful native behavior,
3. the inverse proposer produces diverse legal candidates,
4. compatibility/forward ranking orders candidates usefully,
5. structured multi-start search beats simpler baselines at the same native budget,
6. active acquisition improves model/search performance more efficiently than uninformed acquisition,
7. the system can identify at least some likely search-limited vs likely representation-limited targets without pretending to prove a global optimum,
8. a full 256×2048 wavetable can be solved under a fixed native budget with every native render reused across all 256 targets,
9. hard generated waveforms are handled with no generator metadata,
10. every long run is bounded, checkpointed, interruptible, and resumable.

The final research benchmark is not:

> "Did the neural network recover the original hidden patch?"

It is:

> "Given an arbitrary 2048-sample target, how efficiently can DexFraggler discover one or more legal DX7 patches whose native output matches it, and how honestly can it distinguish solver weakness from likely representation limits?"

---

# Out of scope until the research works

Do not spend this rebuild on:

- VST3,
- AUv3,
- LV2,
- production plugin UI,
- realtime audio-thread constraints,
- final product packaging,
- model quantization,
- ONNX/libtorch deployment,
- consumer sample-import UX,
- licensing strategy for distributed model weights,
- rewriting the existing application for appearance,
- compatibility shims for the old 32×32 workflow.

Those are later productization decisions.

---

# Required handoff discipline

The operator should give Codex only:

1. this master overview,
2. the current phase file,
3. access to the repository.

Future phase files are planning context for the human, not permission for Codex to continue.

At every STOP gate Codex must report:

- what changed,
- what existing code was preserved,
- tests run,
- smoke limits actually consumed,
- output/report paths,
- known risks,
- exact operator command for the meaningful run,
- exact evidence the operator should bring back,
- confirmation that the next phase was not started.


---

# Codex execution wrapper

# Codex Handoff Prompt

Use this as the wrapper prompt each time a phase is handed to Codex.

---

You are working in the existing **Echomatter/DexFraggler** repository.

Read and obey:

1. `00_MASTER_OVERVIEW.md`
2. the **single current phase file** I provide with it

Inspect the current repository before changing it. The repository already contains validated native-rendering, scoring, SysEx/patch, analytic-fitting, and plugin/application work. Preserve validated ground-truth behavior and do not casually rewrite or delete unrelated work.

## Your assignment

Implement **only the current phase**.

Do not begin a later phase even if the current phase finishes cleanly.

The master overview is authoritative when a current implementation detail conflicts with the retired 32×32 DexFraggler architecture.

## Non-negotiable architecture

- Python/PyTorch research path.
- Native Dexed Mark I renderer remains ground truth.
- Canonical target frame = **2048 samples**.
- Canonical wavetable = **256 × 2048**.
- All 256 frames are real targets.
- No 32-frame reduction.
- No anchor/algorithm-row architecture.
- Algorithm is an ordinary legal patch parameter plus derived topology features.
- Preserve phase-bearing information.
- Exact patch identity is permanent.
- Native observation data and target-specific derived scores/search traces are separate.
- The inverse proposer generates starts; it is not the final solver.
- Structured search must eventually use multiple restarts, structural outer moves, local inner moves, cheap scoring, and native verification.
- Black-box target input contains waveform-derived information only. Never depend on generator recipe/provenance.
- Never claim a global optimum or proven representation ceiling without mathematical proof.
- No VST/AUv3/LV2/product UI work in this rebuild.

## Execution limits

Do not perform long collection, training, search, or active-learning runs.

Obey the smoke limits in the master/current phase.

Every meaningful long operation must instead be exposed as an operator command that is:

- bounded,
- checkpointed,
- interruptible,
- resumable,
- deterministic when seeded,
- explicit about output/report paths.

No unbounded defaults.

## Engineering style

Before implementation:

1. inspect existing relevant modules and tests,
2. identify what can be reused,
3. identify what is retired architecture,
4. make the smallest clean architectural change that satisfies the current phase,
5. preserve provenance/licenses.

Prefer:

- transparent data contracts,
- deterministic tests,
- simple models first,
- evidence-driven complexity,
- reversible changes,
- explicit versioning.

Do not hide a data or model problem with a much larger model.

## Required STOP report

When the current phase is complete, STOP and report:

1. files/modules created or changed,
2. current-repo components preserved/reused,
3. tests run and results,
4. smoke limits actually consumed,
5. generated reports/checkpoints/data paths,
6. known risks/failures,
7. exact operator command for the meaningful run,
8. exact evidence the operator should bring back,
9. confirmation that you did **not** start the next phase.

Do not continue past the current STOP gate.

