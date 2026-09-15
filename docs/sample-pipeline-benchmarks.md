# Sample-to-DX7 benchmark boundary

Run the repeatable CPU baseline with:

```powershell
npm run benchmark:sample -- --rounds 5
```

The harness reports preparation time for single-cycle, wavetable, and pitched-sample imports; retrieval and predictor proposal time; and the current phase-aware native score cost. Use `--output .runtime/sample-pipeline-benchmark.json` when a machine-local report is useful. The report is intentionally not committed because timings are host-specific.

The proposal benchmark uses deterministic synthetic descriptor records so it does not depend on the size or contents of a local native dataset. Those timings validate bounded computation only. They are not retrieval quality results. Quality comparisons must use the same held-out native dataset, renderer binary hash, target set, candidate limits, and row budget.

Native scoring is the acceptance boundary: every retrieval or predictor proposal is still measured by the native Dexed Mark I reference before it can become a cell champion. The native timing excludes renderer startup and covers one capture against one imported target. A production comparison should also record cache hits, unique exact patch keys, direct versus interpolated target cohorts, coverage, and weak-cell recovery.
