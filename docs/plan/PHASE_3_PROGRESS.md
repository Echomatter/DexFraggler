# Phase 3 — Forward PyTorch Model (STOP report)

Branch: `phase-3-forward-model`. Phase 3 pipeline is **implemented and
validated**. No real forward training was performed; this is a pipeline/sanity
report, not trained ranking-quality evidence.

---

## Architecture

**ForwardModel** (`src/dexfrag/forward_model.py`, 1,659,664 parameters):

- **Inputs**: categorical algorithm embedding (33-entry, dim=16) + normalized
  feedback (1) + normalized operators (30) + deterministic SHA-256 topology
  hash features (8) = 55-dimensional conditioning vector.
- **Trunk**: two 256-wide ReLU layers (shared across all 32 algorithms).
- **Head**: linear projection to `[B, 3, 2048]` phase-bearing waveforms at
  native amplitude (no output normalization; phase and amplitude pass through).
- **Determinism**: pure feed-forward MLP, no dropout/sampling layers, seeded
  Python/torch/numpy + cudnn deterministic mode.

Input encoding:

| Field | Type | Normalization |
|---|---|---|
| algorithm | 1..32 categorical | `nn.Embedding(33, 16)` |
| feedback | 0..7 long | `/ 7` → `[0, 1]` |
| operators | `[B, 6, 5]` long | columns `/ (31, 99, 14, 1, 99)` |
| topology_signature | str per algorithm | SHA-256 first 8 bytes → `/ 255` |

---

## Loss components

`forward_loss` (`src/dexfrag/forward_metrics.py`):

1. **waveform_mse**: `mean((pred - target)^2)` — direct time-domain residual.
2. **complex_harmonic_mse**: `mean(|FFT(pred - target)|^2)` — Parseval-redundant
   with waveform MSE; reported separately for transparency, not independent
   information.
3. **correlation_loss**: centered cosine similarity `(1 - corr)` averaged over
   notes; constant pairs get zero penalty.

Total: `loss = waveform_mse + complex_harmonic_mse + correlation_loss` (equal
weights 1/1/1).

---

## Ranking evaluation

`ranking_metrics` (`src/dexfrag/forward_metrics.py`):

- Pairwise ordering accuracy (native ties excluded, predicted ties = half credit).
- Top-1 regret (predicted best vs native best MSE to target).
- Random expected regret (uniform-random baseline for comparison).
- Deterministic, double-precision, no Monte Carlo noise.

`evaluate_ranking` (`src/dexfrag/forward_eval.py`):

- Disjoint target/candidate pools by key (self-matches excluded).
- Candidate pool hard-capped at 500 per target.
- Deterministic seeded shuffle for target/candidate selection.

---

## Synthetic sanity smoke results

**Full test suite**: **132 passed** (CPU, torch 2.14.0, no CUDA).

| Test group | Count |
|---|---|
| forward_data (audit + loader) | 21 |
| forward_metrics (loss + ranking) | 10 |
| forward_model (encoding + forward) | 11 |
| forward_training (train + checkpoint) | 8 |
| forward_training_tensorboard (TB + interrupt) | 4 |
| forward_eval (grouped + ranking) | 4 |
| existing Phase 2 tests | 74 |

**smoke_train** (corpus-free, 10 steps, batch_size=4):

- Loss: 1.055 (finite).
- Gradients: all parameters updated.
- Checkpoint: save/resume round-trip verified.
- TensorBoard: scalars logged and readable via EventAccumulator.

**Loss trajectory** (30 synthetic steps, random targets):

- All 6 sampled losses finite (range 1.022–1.047).
- No consistent decrease expected on random noise targets; on real data with
  consistent parameter→waveform mappings, loss should decrease.

**Interrupt safety**: KeyboardInterrupt during training saves `last.pt` for the
current epoch before re-raising (verified by test).

---

## Commands

### Metadata audit (read-only, no training)

```powershell
.\.venv\Scripts\python.exe -m dexfrag.forward_data datasets\main.parquet
```

### Train forward model (operator meaningful training)

```powershell
.\.venv\Scripts\python.exe -m dexfrag.cli train-forward datasets\main.parquet `
  --checkpoint-dir checkpoints\forward `
  --epochs 50 --batch-size 16 --learning-rate 0.001 `
  --device auto --seed 42
```

Add `--max-steps 2048` for a bounded sanity run. TensorBoard:

```powershell
tensorboard --logdir runs
```

### Evaluate forward model (protected test split)

```powershell
.\.venv\Scripts\python.exe -m dexfrag.cli evaluate-forward datasets\main.parquet `
  checkpoints\forward\best.pt `
  --max-targets 32 --max-candidates 500 --device cpu --seed 0
```

---

## Operator report template

After meaningful training, bring back:

1. Training summary JSON (from `train-forward` stdout).
2. Evaluation JSON (from `evaluate-forward` stdout).
3. TensorBoard screenshot or scalar CSV.
4. Whether validation loss decreased.
5. Whether ranking pairwise accuracy is meaningfully > 0.5.
6. Whether top-1 regret is meaningfully < random expected regret.

If ranking is not useful, remain in Phase 3 and adjust architecture/training.

---

## Files changed

### New Phase 3 modules (untracked)

| File | Purpose |
|---|---|
| `src/dexfrag/forward_data.py` | Audit + ForwardDataset |
| `src/dexfrag/forward_metrics.py` | Loss + ranking metrics |
| `src/dexfrag/forward_model.py` | ForwardModel MLP |
| `src/dexfrag/forward_training.py` | Train engine + checkpoints + TB |
| `src/dexfrag/forward_eval.py` | Protected evaluation + ranking |
| `tests/test_forward_data.py` | 21 data tests |
| `tests/test_forward_metrics.py` | 10 metric tests |
| `tests/test_forward_model.py` | 11 model tests |
| `tests/test_forward_training.py` | 8 training tests |
| `tests/test_forward_training_tensorboard.py` | 4 TB/interrupt tests |
| `tests/test_forward_eval.py` | 4 eval tests |

### Modified Phase 2 files

| File | Change |
|---|---|
| `src/dexfrag/cli.py` | +`train-forward`, +`evaluate-forward` commands |
| `src/dexfrag/collector.py` | +`progress_callback` (GUI support) |
| `src/dexfrag/storage.py` | +shard mode dedup fix, +same-batch dedup fix |

---

## Limitations and blockers

1. **No real training performed.** `datasets/main.parquet` is present and the
   metadata audit passes. The real-corpus sanity run has not yet been
   executed.
2. **CUDA unchecked.** All tests ran on CPU. `resolve_device("auto")` falls
   back to CPU when CUDA is unavailable; no GPU training was validated.
3. **Benchmark grouping is lineage-based**, not topology-disjoint. Sparse
   held-out coverage (59 benchmark rows, several algorithms absent) limits
   per-algorithm generalization claims.
4. **No uncertainty proxy.** Phase 3 plan mentions a simple uncertainty/error
   proxy (dropout, ensemble, error head). Not implemented; deferred to avoid
   dominating Phase 3 scope.
5. **Validation loss in training loop** uses mean-per-batch loss, not
   ranking metrics. Ranking evaluation is a separate post-training command.

---

## STOP gate checklist

| Requirement | Status |
|---|---|
| Pipeline implemented | ✓ |
| Tiny sanity smoke passes | ✓ (synthetic, 132 tests) |
| Checkpoint/resume works | ✓ |
| TensorBoard works | ✓ |
| Evaluation includes ranking usefulness | ✓ (evaluate-forward command) |
| Operator command documented | ✓ (above) |

> **Operator gate (pending after code fixes):** the operator gate requires a
> real-corpus sanity run (3 epochs, 2048 obs) with decreasing loss, a
> checkpoint artifact, and TensorBoard events. These are pending.
