# START HERE — User Guide

## What this pack is

This is the revised DexFraggler research plan.

It preserves the original Python/PyTorch rebuild and adds the missing pieces:

- exact structural reduction before brute search,
- a direct compatibility/energy scorer,
- AZDecrypt-style multi-start structured search,
- outer structural vs inner numerical moves,
- restart/stagnation logic,
- empirical reachability / representation-limit triage,
- black-box hard-target curriculum,
- global 256-frame wavetable budget allocation.

The old five-phase pack is preserved inside `_original_recovered_pack/` so nothing has been lost.

---

# Which file do I give Codex?

For the first pass, give Codex:

```text
FULL_CODEX_GOAL_PROMPT.md
01_PHASE_1_FOUNDATION_STRUCTURE.md
```

Tell it:

> Implement Phase 1 only. Stop at the gate and give me the operator commands and report.

After that, the simplest ongoing handoff is:

```text
00_MASTER_OVERVIEW.md
CODEX_HANDOFF_PROMPT.md
[current phase file]
```

Do not authorize the next phase until you have run the meaningful operator experiment from the current phase.

---

# Phase map

```text
Phase 1
Native truth + canonical data + structural inventory
        ↓
Phase 2
Real native observation corpus
        ↓
Phase 3
Forward model: patch → waveform
        ↓
Phase 4
Inverse proposer: waveform → many legal starts
        ↓
Phase 5
Compatibility scorer + structured multi-start search
        ↓
Phase 6
Active learning + hard targets + reachability
        ↓
Phase 7
Full 256×2048 wavetable benchmark
```

---

# What changed from the original plan?

The original architecture was:

```text
native observations
    ↓
forward model
    ↓
inverse proposer
    ↓
active learning
```

That was missing an explicit solver layer.

The revised architecture is:

```text
native observations
    ↓
forward model
    ↓
inverse proposer
    ↓
MULTIPLE STARTS
    ↓
STRUCTURED SEARCH
    ├─ outer structural moves
    ├─ inner local refinement
    ├─ compatibility scoring
    ├─ forward scoring
    ├─ restarts
    └─ preserved elites
    ↓
native verification
    ↓
search trace + active learning
```

That search layer is the largest conceptual change.

---

# What is the "Lire" part?

It is a design rule:

> If exact structure can remove a search dimension, remove it before training/search.

For DexFraggler that means:

- algorithm topology is explicit,
- carrier/modulator roles are explicit,
- fixed parameters are not needlessly searched,
- exact symmetries can prevent duplicate search work,
- validated analytic fitting can become a move operator,
- no model should be forced to rediscover facts we already know exactly.

It does **not** mean merging two distinct legal DX7 patches merely because they sound similar.

---

# What is the AZDecrypt part?

It is the search strategy:

> Good guesses + good fitness + specialized mutations + restarts beat one giant blind guess.

The proposer gives the starts.

The searcher changes them.

The compatibility/forward models tell the searcher which cheap candidates look promising.

The native engine decides what is actually better.

When a basin stalls, search restarts from a different hypothesis.

---

# What is the ML part?

There are three learned jobs.

## Forward

```text
patch → predicted native waveform/features
```

Useful for cheap simulation/ranking.

## Inverse proposer

```text
waveform → multiple legal patch hypotheses
```

Useful for putting the search close to promising basins.

## Compatibility scorer

```text
waveform + patch → expected native error
```

Useful as a very fast search fitness function.

The compatibility model must be benchmarked against simply using the forward model and comparing its predicted waveform.

If it adds no value, it does not get to stay merely because it was planned.

---

# What about my generated wavetables?

They are ideal hard targets, but DexFraggler must be blind to how they were made.

It gets:

```text
2048 samples
```

It does not get:

```text
recipe
seed
generator identity
waveform class
multiplex count
difficulty
"this frame is easy"
```

A full table is:

```text
256 × 2048
```

All 256 frames are used.

The system must solve the waveform, not reverse-engineer your generator.

---

# Why not train directly on the generated tables?

At first they do not have a correct DX7 patch label.

So they are challenge/query targets.

The permanent supervised truth remains:

```text
legal patch → native render
```

When search tests a patch against a generated target:

- the patch's native render becomes reusable permanent observation data,
- the target/patch match becomes derived experiment data,
- the successful/failed search trace becomes useful training evidence.

This keeps the corpus clean.

---

# How do I know if a bad result means the solver sucks or DX7 can't make the shape?

You do not know from one score.

The revised plan explicitly tracks reachability evidence.

Example:

```text
best found = 93%
```

Possible interpretations:

- search keeps improving with budget → probably search-limited,
- many diverse restarts all plateau near 93% → possibly representation-limited,
- models disagree badly / uncertainty is high → uncertain.

The system is allowed to estimate.

It is not allowed to call the estimate a proven mathematical ceiling.

---

# The most important benchmark

For one target:

```text
native renders used → best native match
```

For a full wavetable:

```text
global native renders used → overall 256-frame quality
```

Every method should be compared at the same native budget.

That is how you tell whether the smarter machinery is actually smarter.

---

# The most important full-table optimization

Do not spend a separate native budget on each of 256 frames.

Instead:

1. propose across all frames,
2. merge candidate patches,
3. dedupe,
4. estimate which patch helps the most frames,
5. render that patch once,
6. score it against all 256 frames.

One native render can improve many targets.

---

# What do I physically do after Codex finishes a phase?

Read its STOP report.

It should give you:

- tests,
- smoke results,
- a command,
- output/report location,
- what evidence to inspect.

Run that operator command.

Then bring the report back here.

Do not ask Codex to "keep going while it has time."

The phase gates exist so you can catch a bad foundation before spending hours training the wrong thing.

---

# Quick decision gates

## Phase 1 → 2

Proceed only if native truth, exact identity, features, structure report, and 256×2048 import are trustworthy.

## Phase 2 → 3

Proceed only if the corpus is broad enough and collection is stable.

## Phase 3 → 4

Proceed only if the forward model is useful for ranking candidates.

## Phase 4 → 5

Proceed only if the proposer generates diverse legal candidates with useful native results.

## Phase 5 → 6

Proceed only if structured search beats simpler baselines at equal native budget.

## Phase 6 → 7

Proceed only if active acquisition/reachability machinery is producing useful evidence rather than chasing noise.

## Phase 7

Run the real fixed-budget wavetable benchmark.

---

# If something fails

Do not automatically make the neural network bigger.

Use the evidence to decide which layer failed:

```text
bad native data?
bad feature extraction?
coverage hole?
forward model?
proposer collapse?
compatibility ranking?
search move set?
restart policy?
representation limit?
```

Change one layer at a time and rerun the relevant fixed benchmark.

---

# First action

Start with:

```text
FULL_CODEX_GOAL_PROMPT.md
01_PHASE_1_FOUNDATION_STRUCTURE.md
```

Have Codex implement Phase 1 only and stop.
