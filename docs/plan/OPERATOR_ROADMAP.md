# DexFraggler ML + Structured Search Operator Roadmap

This is the human/operator guide.

You do not need to understand PyTorch internals to run the project.

Your job is to move the research through a controlled evidence loop:

```text
Codex builds one phase
    ↓
Codex STOPs
    ↓
you run a bounded real experiment
    ↓
you inspect the report / TensorBoard
    ↓
you bring the evidence back
    ↓
we decide whether the next phase is justified
```

The most important rule:

> Never let collection, training, search, or active learning become a black box that simply runs forever.

Every meaningful run should have:

- a command,
- an experiment ID,
- a native/count/time/disk budget,
- a checkpoint path,
- a stopping rule,
- a report to inspect,
- safe Ctrl+C behavior,
- resume support.

---

# How to hand the pack to Codex

For each phase, give Codex only:

1. `00_MASTER_OVERVIEW.md`
2. the current phase file
3. repository access

Use `CODEX_HANDOFF_PROMPT.md` as the wrapper prompt.

Do not give future phase documents as permission to continue.

If Codex finishes the current phase early, it should STOP, not "helpfully" start the next one.

---

# Before Phase 1

Give Codex:

```text
00_MASTER_OVERVIEW.md
01_PHASE_1_FOUNDATION_STRUCTURE.md
CODEX_HANDOFF_PROMPT.md
```

Its job is foundation only.

When it stops, run the documented tests and:

```text
dexfrag doctor
dexfrag structure audit
```

## You want to see

- Python environment passes.
- PyTorch imports.
- accelerator status is known.
- native renderer is found.
- one legal patch renders.
- exact patch identity is stable.
- renderer hash/provenance is recorded.
- feature extraction is deterministic.
- `[256, 2048]` import works.
- target model input contains no generator metadata.
- all 32 algorithm topology descriptors exist.
- Parquet storage is writable.
- TensorBoard smoke logging works.

## Do not proceed if

- native output is flaky,
- patch identity changes,
- feature extraction changes between runs,
- wavetable import reduces frames,
- structure audit makes unproven equivalence claims,
- model-facing target data contains generator provenance.

Foundation errors multiply later.

---

# Phase 2 — First Real Data Collection

After Codex implements Phase 2, it should give you a bounded collection command.

## Start with calibration

Run a small profile first.

Measure:

- renders/minute,
- disk growth,
- duplicate rate,
- silent/degenerate rate,
- algorithm coverage,
- topology coverage,
- renderer stability.

Watch:

```text
dexfrag dataset coverage
```

and TensorBoard if useful.

## What good looks like

- observation count rises,
- duplicates are skipped without rerender,
- every algorithm receives observations,
- structural coverage is not concentrated in one easy family,
- renderer failures are rare and visible,
- degenerate data is classified,
- disk growth is understandable,
- Ctrl+C leaves a resumable state.

## Then do the first meaningful bounded collection

Choose one explicit limit:

- observation count,
- wall-clock,
- disk.

Do not start with unlimited.

## Bring back

- total unique observations,
- duration,
- dataset size,
- render rate,
- observations per algorithm,
- structural coverage report,
- acquisition-source distribution,
- degenerate percentage,
- duplicate percentage,
- split/lineage report,
- errors/warnings.

### Decision

> Is the corpus broad and trustworthy enough to train a useful forward surrogate?

If no, stay in Phase 2.

---

# Phase 3 — First Forward-Model Training

Codex should have run only the tiny 3-epoch smoke.

You run the real bounded training experiment.

Start monitoring:

```text
dexfrag monitor
```

Then use the exact `train-forward` command/config Codex provides.

## Watch

- training loss,
- validation loss,
- family/lineage holdout,
- waveform overlays,
- harmonic predictions,
- algorithm/topology error,
- candidate-ranking usefulness.

## Healthy

- train loss improves,
- validation loss improves,
- waveform/harmonic predictions improve,
- ranking of candidate patches correlates with native ranking.

## Overfitting

- train improves,
- validation worsens.

Let early stopping act or stop the run.

## No learning

- train/validation are flat,
- predictions remain meaningless.

Do not "just run longer."

Likely causes:

- bad input encoding,
- bad normalization,
- loss mismatch,
- weak dataset coverage,
- wrong output representation,
- architecture too small/incorrect.

## Bring back

- best checkpoint,
- train/validation curves,
- family holdout,
- held-out metrics,
- native vs predicted examples,
- per-algorithm/topology errors,
- ranking benchmark,
- experiment summary.

### Decision

> Is the forward model useful enough to rank patches better than uninformed scoring?

If no, remain in Phase 3.

---

# Phase 4 — Inverse Proposer Training

The proposer should output many legal hypotheses.

Do not judge it primarily by whether it recovers the exact hidden patch.

The true question is:

> Does it put strong native solutions into the candidate pool efficiently?

Run a bounded meaningful training job.

Use:

- checkpoints,
- early stopping,
- max steps/epochs,
- candidate-count config.

## Watch

- legal candidate rate,
- unique candidate rate,
- algorithm diversity,
- topology diversity,
- duplicate collapse,
- native match quality after forward ranking.

## Important benchmark

You want:

```text
native budget     best native quality
1                 ...
4                 ...
8                 ...
16                ...
32                ...
64                ...
```

Compare proposer-derived candidates to random/structured/retrieval baselines.

## Bring back

- proposer report,
- legality/diversity,
- candidate distributions,
- quality-vs-budget chart,
- success examples,
- failure examples,
- examples where a good candidate was proposed but poorly ranked.

### Decision

> Is the proposer producing useful starting basins for search?

If no, stay in Phase 4.

---

# Phase 5 — Compatibility Scorer + Structured Search

This is the major new phase.

The proposer is now only the starting-point generator.

The search engine should test many cheap hypotheses while spending a controlled number of native renders.

## First: train/evaluate compatibility

Run the bounded real compatibility training config.

The key comparison is:

```text
direct compatibility scorer
vs
forward model → predicted waveform → target comparison
```

If the direct scorer is worse and not substantially faster, do not force it into the pipeline merely because it exists.

## Then: run fixed-budget search benchmarks

Use the same target set and same native budgets for all methods.

Suggested budgets:

```text
1
4
8
16
32
64
```

Methods should include:

- random legal,
- structured random,
- local mutation,
- retrieval,
- proposer only,
- proposer + forward,
- proposer + compatibility,
- full structured search.

## What to inspect

- quality vs native budget,
- move-family success,
- outer vs inner moves,
- restart productivity,
- how often search stalls,
- whether restarts find new basins,
- surrogate/native disagreement,
- whether analytic/Jacobian moves help,
- whether all restarts collapse to one mode.

## Warning signs

### Search looks good only with more native renders

That is not an efficiency win.

### All starts collapse to the same algorithm/family

Diversity/restart policy is failing.

### Surrogate says "better" and native repeatedly says "worse"

The scorer/forward model needs more data in that region.

That disagreement is useful Phase 6 acquisition evidence.

## Bring back

- compatibility ranking report,
- fixed-budget benchmark,
- search-trace summary,
- move success rates,
- restart statistics,
- best/worst targets,
- surrogate/native disagreement examples.

### Decision

> Does structured model-guided search beat simpler baselines at the same native-render budget?

If no, improve Phase 5 before adding more automation.

---

# Phase 6 — Active Learning + Reachability

Now let evidence tell the system where it is weak.

Use bounded cycles:

```text
acquire
↓
stop
↓
inspect
↓
retrain/resume
↓
evaluate
↓
decide
```

Do not build one endless self-training loop.

---

# Using the generated hard wavetables

Treat them as black-box challenge targets.

DexFraggler gets:

```text
2048 samples
```

It does not get:

- recipe,
- seed,
- generation method,
- waveform label,
- hidden "difficulty",
- multiplex information.

If a table has easy-looking frames early and strange frames later, do not tell the model that ordering means anything.

Let the waveform itself be the evidence.

## What to learn from hard targets

For each target ask:

- Did the proposer miss?
- Did search start in the wrong family?
- Did the scorer mis-rank?
- Did many diverse restarts plateau at the same mediocre quality?
- Did more native budget keep improving?
- Is the target simply far from known native waveforms?

Failures are useful.

---

# Reachability output

Do not interpret "best found" as "true maximum."

You want a practical triage:

```text
likely search-limited
likely representation-limited
uncertain
```

with:

- native budget,
- restart diversity,
- improvement curve,
- uncertainty,
- evidence.

If a target gets 93%:

- 93% + strong ongoing improvement = probably search-limited.
- 93% + many diverse exhausted basins = possibly representation-limited.
- 93% + weak models/high disagreement = uncertain.

That is the useful distinction.

## Bring back

- active selections,
- why they were selected,
- new observations,
- before/after model/search metrics,
- hard-target examples,
- reachability triage examples,
- misclassifications or questionable estimates.

### Decision

> Is active acquisition actually improving held-out search efficiency, or only collecting more of what the system already understands?

---

# Phase 7 — Full 256×2048 Wavetable Benchmark

This is the full concept.

The system must:

1. ingest 256 frames,
2. propose for every frame,
3. merge candidates,
4. dedupe exact patches,
5. score candidates across the whole table,
6. choose the highest global utility render,
7. native-render once,
8. score that render against all 256 frames,
9. update bests,
10. repeat until the global native budget is exhausted.

Do not run 256 separate native searches.

## First smoke

Codex itself may spend only 8 native renders.

That only proves orchestration.

## Your real benchmark

Run the same target with budgets such as:

```text
8
16
32
64
```

Hold models/config constant.

## Inspect

- average frame quality,
- median,
- worst frame,
- score distribution,
- thresholds,
- unique selected patches,
- frame coverage per patch,
- quality vs native budget,
- render reuse factor,
- wall-clock,
- baseline comparison,
- reachability flags.

## The key chart

```text
global native budget → table quality
```

This is the practical measure of whether the entire architecture works.

---

# How to think about dataset size

Do not choose a magical giant number up front.

Use staged growth:

```text
collect enough to learn
↓
train
↓
find failure regions
↓
collect deliberately
↓
retrain
```

The useful question is:

> Does the next batch of native observations improve held-out model/search performance?

Not:

> Have I reached one million examples?

---

# How to think about training time

Training time is not a success metric.

Prefer:

- validation,
- family holdout,
- early stopping,
- checkpoints,
- ranking/search benchmarks.

If validation has stopped improving, stop.

---

# How to think about search time

Search time alone is not the main metric either.

Native renders are the expensive currency.

A search that evaluates a million cheap surrogate candidates but uses only eight native renders may be excellent.

A search that gets slightly better quality by using 500 native renders is not automatically better.

Always compare at fixed native budgets.

---

# Normal mature operating loop

Once all phases exist:

```text
1. Environment
   dexfrag doctor

2. Dataset
   dexfrag dataset coverage

3. Collect when needed
   dexfrag collect ...

4. Forward model
   dexfrag train-forward ...

5. Proposer
   dexfrag train-proposer ...

6. Compatibility scorer
   dexfrag train-compat ...

7. Search benchmark
   dexfrag evaluate-search ...

8. Active acquisition when justified
   dexfrag acquire-active ...

9. Real target / wavetable
   dexfrag solve ...

10. Monitor
   dexfrag monitor
```

Every operation should be safely interruptible.

If it cannot checkpoint/resume, treat that as an engineering defect.

---

# What to bring back after each real run

## After collection

> Here is my Phase 2 dataset/coverage report. Is the corpus broad enough for forward training?

## After forward training

> Here are the Phase 3 validation, family-holdout, and ranking metrics. Is the forward model useful enough to proceed?

## After proposer training

> Here are the candidate diversity and fixed-native-budget results. Is the proposer putting strong solutions into the pool?

## After search

> Here are the equal-native-budget baselines, move stats, restart stats, and search traces. Is structured search really winning?

## After active acquisition

> Here is what the system chose, why it chose it, and the before/after search performance. Is it learning useful failure regions?

## After wavetable evaluation

> Here is the 256×2048 benchmark at fixed native budgets. Where is the bottleneck now?

That keeps every engineering decision tied to evidence.
