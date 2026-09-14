# Performance and retained-results review — 2026-09-14

The active table snapshot contains **1,024 current, native-measured cells** across 32 DX7 algorithms and 32 targets. It was captured at 2026-09-14T21:06:48.604Z. Every cell has 7–8 focused search visits. The targets run from triangle through square to saw, with detune disabled.

The accompanying [numerical report](./performance-review-2026-09-14.json) contains the complete distributions by algorithm, target, and pitch. It contains no scan names, scan identifiers, credentials, local runtime paths, or captured audio.

## Accuracy and remaining error

| Measure | Result |
| --- | ---: |
| Mean native match | 98.8696% |
| Median native match | 99.2101% |
| Lowest native match | 94.6648% |
| Cells at or above 99% match | 590 / 1,024 |
| Mean normalized residual RMS | 13.6810% |
| Largest normalized residual RMS | 32.2269% |

Match is the minimum correlation across MIDI notes 45, 57, and 69. Native loss is the largest squared normalized residual across those notes. Residual RMS is sqrt(1 - match²): 99% correlation still corresponds to about 14.1% residual RMS. A high match score does not imply an indistinguishable waveform.

The saw end remains the weakest region. The anchor columns show:

| Slice | Target | Mean match | Lowest match |
| --- | --- | ---: | ---: |
| 1 | triangle | 99.5921% | 99.2988% |
| 16 | square | 99.1836% | 98.4037% |
| 32 | saw | 96.8157% | 94.6648% |

The weakest cells are:

| Algorithm | Slice | Match | Residual RMS |
| --- | --- | ---: | ---: |
| 18 | 32 | 94.6648% | 32.2269% |
| 31 | 32 | 95.0855% | 30.9636% |
| 30 | 32 | 95.3313% | 30.1983% |
| 7 | 32 | 95.4250% | 29.9010% |
| 15 | 32 | 95.4293% | 29.8872% |
| 18 | 31 | 95.4858% | 29.7062% |

The lowest average algorithm rows are 30, 32, and 6, at 98.3434%, 98.3763%, and 98.4077%. These are useful candidates and remain part of the table. Their relative weakness justifies more search; it does not justify deleting them or relaxing the objective.

MIDI note 45 limits 575 cells, note 57 limits 143, and note 69 limits 306. All three pitches therefore contribute useful constraints. Reducing validation to one pitch would change the acceptance standard.

## Surrogate versus native results

The stored model and native champions use the same patch in only 329 of 1,024 cells. Their displayed scores also use different objectives. The average displayed gap of 0.0558 percentage points is therefore **not** a measured same-patch surrogate error. Performance work must validate the actual native objective and preserve both candidate streams.

## Observed live throughput

The existing runner log records 428 completed row intervals during a 3593.004-second window ending 2026-09-14T21:08:37.036Z. Those intervals contain 6,926 three-pitch captures:

| Measure | Observed result |
| --- | ---: |
| Native captures per second | 1.928 |
| Target comparisons per second | 61.68 |
| Completed rows per minute | 7.147 |
| Median row interval | 8.167 s |
| Mean row interval | 8.395 s |

This is end-to-end historical throughput, including network and checkpoint time. It is not an isolated math benchmark. A capture serves all 32 targets in its algorithm row. Focused visits, model evaluations, and three-pitch captures measure different work and should not be compared as interchangeable counters.

## Implemented CPU improvements

The native scorer keeps the same full-Nyquist objective and 1e-10 phase tolerance. A tighter proven phase bound retains each interval's endpoint slope; contiguous projection accumulation keeps the same floating-point addition order. Display-only target means are evaluated at the winning phase.

Across 64 recent champions spanning all 32 algorithms, 192 note captures and all 32 targets (6,144 comparisons), seven alternating-order repetitions gave:

| Native CPU stage | Before median | After median |
| --- | ---: | ---: |
| Prepare pitch transforms | 1,215.07 ms | 761.92 ms |
| Score all targets | 1,403.03 ms | 1,056.22 ms |

The sum of these medians fell 30.6%. Phase subdivisions fell from 147,384 to 75,870 per round. Projection moments were bit-identical; maximum score difference was 7.77e-16 and maximum phase difference 1.78e-15 radians. See the [native benchmark data](native-performance-2026-09-14.json). `scripts/benchmark-native-score.mjs` can repeat the CPU comparison with a prior scorer and a downloaded table.

The proposal model now shares one candidate FFT and normalized magnitude vector across every target in a row. The objective retains every bin and its original arithmetic order. All 1,024 current champion waveforms and 32,768 score records matched the previous implementation exactly. Across 96 recent patches, five alternating-order repetitions measured:

| Model CPU stage | Before median | After median | Speedup |
| --- | ---: | ---: | ---: |
| Score 96 rows of 32 targets | 1,872.43 ms | 400.93 ms | 4.67× |
| Render and score those rows | 1,894.92 ms | 477.24 ms | 3.97× |

See the [model benchmark data](model-performance-2026-09-14.json). These are isolated CPU stages with the live runner and other host activity present. They do not establish a 4.67× improvement in the complete scheduler, which also includes native rendering and network/checkpoint time.

Restarting now merges all valid saved model elites into the candidate pool; it previously restored only the first. Stale-target candidates are rescored. The native champion remains independent, and neither metric versions nor stored results are invalidated. The standalone calculation API and corpus exporter are documented in [calculation-models.md](calculation-models.md).

## Recoverable older results

An earlier table used the same anchors and metric but belongs to a **different retained scan**. The newer snapshot exceeds that table in 1,001 cells and ties it in six. Seventeen cells in the older scan remain stronger; this comparison does not establish regression inside the newer scan.

All 17 historical candidates were remeasured in a separate native renderer against every target in their algorithm row. Exact capture caching reduced this to five distinct renders. All 17 original scores reproduced exactly, and the candidates improve 17 cells relative to the captured active snapshot. The largest cell gain is 0.190825 percentage points. Their aggregate potential mean-table gain is 0.001997 percentage points.

The five distinct older patches were imported as seeds into the same active scan after the updated runner was loaded. The runner remeasured them under its existing monotonic checkpoint rules. At 21:21:08 UTC all seeds had been consumed, all 17 cells matched or exceeded the recovered measurements, and none of the 1,024 saved cells had regressed against the snapshot taken before the upgrade. Twenty-one cells had improved during recovery and resumed search. The original named scans remain available, and the runner resumed at its existing BelowNormal priority.

## Validation boundaries

The export and counter snapshot were read sequentially while the runner continued, so their timestamps differ slightly. The inactive scan was not switched or modified. Recovery verification compares the saved pre-upgrade and post-upgrade exports; subsequent search can improve them further.

Local validation passed all 58 JavaScript tests using a freshly rebuilt native renderer, the native CTest engine suite, and the protocol/source-manifest smoke test. Standalone scoring and export of the 1,024-cell table into a 1,469-candidate research corpus also succeeded. The Windows web build exhausted machine commit memory in both ordinary and single-thread attempts; the clean-clone web build passed on GitHub. Clean-checkout verification also exposed mixed upstream line endings that Git had normalized. Vendored files now preserve their exact recorded bytes through `.gitattributes`, without changing engine code or weakening the source-hash check. GitHub Actions checks both the web build and a fresh Windows source build.

The native engine uses 48 kHz audio, velocity 100, a 7,200-sample onset offset, and a 4,096-sample capture at each of three pitches. This supports the current stationary-waveform fitting prototype. It does not establish release-tail, modulation, full-keyboard, or real-time VST performance.

A pre-publication audit inspected 198 tracked paths and 288 historical blob versions reachable from Git references. It found no current configured worker/session credential values or matched private-key, GitHub-token, or long credential-header patterns. Private runtime/config path patterns were absent from the tracked files. This limited local check is not an exhaustive external secret-scanner audit.
