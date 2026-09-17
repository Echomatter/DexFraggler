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
