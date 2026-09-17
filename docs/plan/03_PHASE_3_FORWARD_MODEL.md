# Phase 3 — Forward PyTorch Model

## Objective

Build and validate:

```text
legal DX7 patch parameters + derived structure
        ↓
predicted native waveform/features
```

The forward model is the first learned surrogate.

It must become useful enough to rank candidate patches cheaply.

**Codex builds the training system and performs only a tiny sanity run.**
**The operator performs meaningful training separately.**

---

# Preconditions

Before implementation, inspect the real Phase 2 dataset report.

Confirm:

- a real corpus exists,
- exact patch identity is stable,
- schema is stable,
- renderer/feature versions are coherent,
- train/validation/test split exists,
- lineage/family holdout exists or has an explicit plan,
- obvious coverage failures are understood.

If not, stop and report the blocker.

Do not compensate for bad data with model complexity.

---

# Inputs

Use the complete canonical searchable patch state.

Include:

- algorithm as a categorical parameter,
- free operator parameters,
- feedback,
- fixed/normalized reference fields where needed for completeness,
- fixed algorithm topology descriptors.

Encode categorical/discrete parameters appropriately.

Do not create 32 separate models by default.

Do not treat algorithm as a row index.

---

# Initial architecture

Start simple.

Preferred first attempt:

- categorical embeddings where useful,
- normalized scalar/discrete features,
- topology descriptor inputs,
- shared MLP trunk,
- output heads for phase-bearing waveform/harmonic representation.

Do not begin with:

- transformer,
- diffusion,
- giant autoregressive network,
- graph neural network,

unless a simpler model demonstrably fails.

---

# Outputs

Choose the simplest representation that supports accurate native comparison.

Candidate initial outputs:

- complex harmonic coefficients at A2/A3/A4,
- canonical periodic waveform samples,
- or a justified multi-head combination.

Preserve phase.

Predictions must be comparable to native observations using a deterministic evaluation function.

---

# Losses

Use transparent losses.

Potential components:

- complex coefficient error,
- waveform residual,
- normalized correlation loss,
- spectral magnitude error,
- pitch-balanced aggregation.

Do not optimize only a magnitude spectrum if phase-bearing reconstruction is required.

Keep loss components logged separately.

---

# Training system

Implement:

```text
dexfrag train-forward
dexfrag evaluate-forward
dexfrag monitor
```

Support:

- CPU,
- CUDA when available,
- deterministic seeds,
- train/validation loaders,
- protected test evaluation,
- checkpoint save/resume,
- best-validation checkpoint,
- experiment configuration capture,
- git commit capture,
- dataset manifest/version capture,
- feature/scorer version capture,
- TensorBoard logging,
- safe Ctrl+C checkpoint.

Never overwrite the only known-good checkpoint.

---

# Metrics

At minimum:

- training loss,
- validation loss,
- protected held-out test metrics only when explicitly invoked,
- per-pitch error,
- complex-harmonic error,
- waveform correlation/residual,
- error by algorithm,
- error by topology/structural family,
- error by important parameter regions,
- family/lineage holdout performance,
- calibration if the model emits uncertainty.

TensorBoard should include representative:

- good predictions,
- median predictions,
- poor predictions,
- native vs predicted waveform overlays,
- native vs predicted harmonics,
- algorithm/family error summaries.

---

# Uncertainty

Add a simple uncertainty/error proxy if practical.

Examples:

- small ensemble,
- dropout-based estimate,
- error head,
- distance-to-training-data proxy.

Do not make uncertainty machinery dominate Phase 3.

It becomes useful later for active acquisition and search triage.

---

# Tiny Codex sanity run only

At most:

- **3 epochs**
- **2,048 observations**

Purpose only:

- batches load,
- gradients flow,
- losses are finite,
- checkpointing works,
- resume works,
- TensorBoard works,
- evaluation works.

Label the result as smoke/sanity only.

---

# Operator configuration

Provide a bounded real-training config with:

- max epochs,
- max steps,
- early stopping,
- patience,
- batch size,
- checkpoint frequency,
- device selection,
- optional wall-clock limit.

Training must be interruptible/resumable.

Prefer validation-driven early stopping over huge arbitrary epoch counts.

---

# Forward-model acceptance question

Do not ask:

> Does it reproduce every sample perfectly?

Ask:

> Is it accurate enough that candidate ranking based on predicted native behavior is meaningfully better than uninformed ranking?

Create a ranking-oriented evaluation in addition to raw prediction loss.

For held-out target waveforms and candidate patches, measure whether the forward model preserves the useful ordering of candidates.

---

# STOP gate

Stop after:

1. pipeline is implemented,
2. tiny sanity run passes,
3. checkpoint/resume works,
4. TensorBoard works,
5. evaluation includes ranking usefulness,
6. operator command is documented.

### Required phase report

Report:

- architecture,
- parameter count,
- input/output representation,
- loss components,
- smoke dataset size,
- smoke epochs,
- whether loss moved correctly,
- checkpoint path,
- TensorBoard path,
- ranking-evaluation method,
- exact operator command for meaningful training,
- exact metrics/report to bring back.

**Do not perform meaningful forward training automatically.**
**Do not begin the inverse proposer until the operator has reviewed real forward-model results.**
