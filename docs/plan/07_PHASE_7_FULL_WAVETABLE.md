# Phase 7 — Full 256×2048 Wavetable Solving + Final Research Benchmark

## Objective

Make the complete system solve a canonical wavetable under a fixed native-render budget.

Input:

```text
[256, 2048]
```

All 256 frames are real targets.

The system must not reduce them to 32.

The system must not infer anything from how the wavetable was generated.

---

# Core principle

Do not run 256 independent brute-force searches.

Treat the table as a joint candidate-coverage problem.

A single legal patch may match many frames.

A single native render can therefore update all 256 frame scores.

---

# Required workflow

1. ingest all 256 frames,
2. compute waveform-only canonical features,
3. propose candidate patches for every frame,
4. merge all proposal pools,
5. deduplicate exact patch identities,
6. rank each candidate against all 256 targets cheaply,
7. estimate global candidate utility,
8. choose a candidate under the global native budget,
9. native-render it once,
10. score the native observation against all 256 frames,
11. update per-frame bests,
12. use structured search/refinement around high-value regions,
13. continue until global native budget is exhausted,
14. save a complete result/report.

---

# Global candidate utility

The allocator should consider expected improvement across the table.

Potential transparent objective:

```text
sum of predicted positive improvement over current frame bests
```

with optional secondary pressure toward:

- worst frames,
- uncovered frames,
- diversity,
- uncertainty.

Do not overcomplicate before a simple global-utility rule is benchmarked.

---

# Search integration

Structured search can still operate around frame-specific hypotheses, but native rendering is globally budgeted.

A candidate discovered for frame 91 may also improve frames 12, 66, 92, and 180.

Every verified native render must be scored against the complete target set.

---

# Candidate pooling rules

Track:

- source frame(s),
- proposer score,
- compatibility score,
- forward score,
- search restart/family,
- exact patch key,
- predicted table-wide utility.

Dedupe exact patch keys before native render.

Do not dedupe merely because two patches are sonically similar.

---

# Budgets

Support explicit global native budgets such as:

- 8,
- 16,
- 32,
- 64,
- larger operator-selected bounded values.

Never default to unlimited.

---

# Baselines

At equal native budgets compare:

- random legal global candidates,
- broad structured global candidates,
- proposer only,
- proposer + forward ranking,
- proposer + compatibility ranking,
- proposer + structured search,
- active-learned current system.

If an older DexFraggler search baseline is practical, include it as evidence without forcing compatibility architecture.

---

# Metrics

Report at minimum:

- native renders consumed,
- average frame native match,
- median frame native match,
- worst frame native match,
- score distribution,
- thresholds reached,
- frame index of worst cases,
- number of unique selected patches,
- frame coverage per selected patch,
- best-so-far table quality vs native budget,
- wall-clock time,
- cheap candidate evaluations,
- search restarts/families used,
- representation-limited/search-limited/uncertain indicators where available,
- comparison to equal-budget baselines.

Also report:

- `render_reuse_factor`: how many target scores each native render produced,
- proof/assertion that every verified native render was scored against all 256 targets.

---

# Output artifacts

Produce a result bundle containing:

- input target hashes,
- config,
- model/checkpoint versions,
- dataset manifest,
- renderer provenance,
- selected legal patches,
- per-frame best patch assignment,
- per-frame scores,
- table-wide score curves,
- search traces,
- reachability estimates,
- baseline comparison,
- human-readable summary.

---

# Bounded Codex smoke

The Codex smoke may perform at most:

- **8 new native renders total** for the full table.

This proves orchestration only.

It does not establish final quality.

---

# Final operator benchmark

After Codex stops, the operator runs bounded benchmarks at increasing budgets, for example:

```text
8
16
32
64
```

Use the same target and model checkpoints for a clean quality-vs-budget comparison.

Do not change multiple variables between budget points unless the experiment explicitly tests them.

---

# STOP gate

Stop when:

1. `[256, 2048]` input works,
2. all 256 frames remain present,
3. candidate pools merge globally,
4. exact candidates dedupe,
5. global utility selection works,
6. structured search integrates with the global budget,
7. each native render is scored against all 256 targets,
8. smoke uses no more than 8 new native renders,
9. final report bundle is produced,
10. equal-budget baselines are runnable,
11. operator commands are documented.

### Required phase report

Report:

- smoke native budget,
- render reuse evidence,
- result/report paths,
- table-wide metrics,
- baseline status,
- exact commands for operator benchmarks,
- remaining bottlenecks,
- research conclusions supported by evidence only.

**Do not begin VST/plugin/product implementation automatically.**
