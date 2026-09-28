# DexFraggler — Master TODO

Last updated: 2026-09-28. Evidence-backed; items marked ✅ are done, ⬜ pending, 🔒 gated.

---

## 0. URGENT — Save the work (everything since commit 92950b0 is uncommitted)

- ⬜ **Commit the current state** via the save panel. Uncommitted: `cli.py` (doctor refactor + `operator-gui` + `train-ranker`/`evaluate-ranker`), `forward_model.py` (v2 harmonic head + 512 trunk), `forward_training.py` (version guard), `test_forward_model.py`, `test_forward_training.py`, new `operator_app.py` + `test_operator_app.py`, new `ranker.py` + `test_ranker.py`.
- ⬜ Decide fate of `checkpoints/ranker/` (selected under the broken anchor=pool val metric — discredited; `ranker-v2/` is the honest run).

## 1. The decision that gates everything

**Five model variants have now failed the ranking gate identically** (test protocol, 32 targets × 83 candidates):

| Model | Pairwise (gate > 0.60) | Top-1 regret (random 0.0035) | Fit quality |
|---|---|---|---|
| forward v1 (256, raw head) | 0.562 | 0.00163 | train sim 0.634 |
| forward v2 (256, harmonic) | 0.526 | 0.00209 | train sim 0.625 |
| forward v3 (512, harmonic) | abandoned | — | train sim 0.583 (worse) |
| ranker (two-tower, honest val) | 0.557 | 0.0057 | ListNet ≈ ln(32) |

- 🔒 **Root cause (evidence-based): data scale, not architecture.** 2,523 valid training rows (~64/algorithm) cannot teach fine-grained patch→waveform-distance ordering to any of these model classes. Every variant can't even fit training data.
- ⬜ **DECIDE (user):** (a) collect more valid rows first [recommended], (b) accept v1 as the weak-but-real surrogate (2.2× better than random top-1) and start proposer work now, (c) one more model experiment.

## 2. Data collection — the highest-lever action

- ⬜ **Bounded collection run** (app tab 3, or `dexfrag collect --max-renders N`). Valid rows are ~23% of renders; corpus needs to roughly 2–5× (target: 5k–12k valid rows) before retraining any ranker/forward model.
- ⬜ Bring back: observation count, valid-row yield, duplicates skipped, per-algorithm coverage, render rate.
- ⬜ After collection: retrain ranker (tab 4, same folder — resumes) → tab 5 gate. The ranker directly optimizes the gate metric and is the right architecture once data suffices.

## 3. Phase 3 / 3b — model work (blocked on §1/§2)

- ✅ Pipeline: train/eval/resume/TB/version-guards all tested (195+ tests green).
- ✅ Ranker built, wired into app tabs 4–5, honest val metric (disjoint pools — the anchor=pool version inflated accuracy by ~0.21 and was fixed).
- ⬜ Retrain ranker on the enlarged corpus; gate: pairwise > 0.60 AND top-1 regret < random.
- ⬜ If gate passes: retrain proposer against the ranker surrogate (tab 6/7 use it).
- ⬜ If gate fails again at 10k+ valid rows: escalate to the plan's next lever (hard-negative triplet loss, larger batches) — do not keep widening.

## 4. Phase 4 — Inverse proposer (code done; evidence thin)

- ✅ Proposer trained (2 epochs, best_val 6.71) and adequately evaluated: proposer 0.325 vs random 0.203 / structured 0.210 / retrieval 0.715 (`reports/phase4-adequate-8x8.json`).
- ✅ STOP-gate mechanics all exist (legality 100%, diversity, budget curve, resume, TB).
- ⬜ **Meaningful proposer training** (plan: operator runs it; tab 6, epochs 20–50, patience) — currently only a 2-epoch run exists.
- ⬜ Proposer retrain against the best available surrogate once §1 is decided.
- ⬜ Black-box target exam (tab 8): generate mystery wavetables → ingest → evaluate proposer vs retrieval where memorization can't win.
- ⬜ Write the Phase 4 STOP report per `04_PHASE_4_INVERSE_PROPOSER.md` (architecture, params, legality/diversity, bounded native result, failure examples, exact commands).

## 5. Phases 5–7 — locked until gates pass

- 🔒 Phase 5 (compatibility scorer + structured search): needs proposer results reviewed.
- 🔒 Phase 6 (active learning): needs search traces.
- 🔒 Phase 7 (full 256×2048 wavetable benchmark): final exam.
- ⬜ Do not start; the app's tab 10 shows the unlock evidence for each.

## 6. Housekeeping

- ⬜ Delete or archive orphaned artifacts: `checkpoints/forward/`, `checkpoints/forward-v2/`, `checkpoints/forward-v3/`, `checkpoints/ranker/` (superseded), `checkpoints/inverse-proposer-v2-broken/` (diverged, -2.14e18).
- ⬜ Clean `datasets/*.tmp` stale downloads (~400 MB).
- ⬜ Update `docs/plan/PHASE_3_PROGRESS.md` with the v2/v3/ranker evidence table and the data-scale verdict (it still says "no real forward training was performed").
- ⬜ Note: `.gitignore` has `checkpoints/*.pt` which does NOT match subdirectories — checkpoints are untracked-but-not-ignored; decide whether to fix the pattern or keep saving via the panel.
- ⬜ `forward-operator/last.pt` (50-epoch resume) has a different git commit than `best.pt` — provenance inconsistency, harmless but worth knowing.

## 7. Test & verification status (last full run)

- ✅ 181 passed + 1 CUDA skip (pre-ranker); +14 ranker tests and +10 operator-app tests green after that.
- ✅ `dexfrag doctor` all 8 checks OK; `operator-gui` registered.
- ⬜ Full-suite re-run after the next commit (native-render tests exceed the 120 s shell timeout — run in chunks with `--basetemp`).
