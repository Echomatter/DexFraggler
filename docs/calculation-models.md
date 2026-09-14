# Reusing the calculation models

DexFraggler is an offline patch-search prototype for a future wavetable-remix instrument using Dexed. It currently produces legal static DX7 patches and measured matches to ideal waveform blends. It does not yet provide a VST, a trained predictor, or an audio-thread-safe optimizer.

The calculation library has no npm dependencies or Site credentials. Clone the repository and use Node.js 22.13 or newer:

```sh
node scripts/model-lab.mjs score --shape triangle --out triangle-model.json
node scripts/model-lab.mjs score --shape triangle --native --out triangle-native.json
node scripts/model-lab.mjs score --patch my-patch.json --target my-target.json --native --out comparison.json
node scripts/model-lab.mjs corpus --table downloaded-table.json --out research-corpus.json
```

The first command evaluates the initial sine patch against a triangle. Supply a canonical patch JSON to evaluate another patch. `--native` runs the bundled Windows renderer or the executable selected by `DEXFRAGGLER_NATIVE_EXE`. See [native build instructions](../native/README.md). Files are created exclusively so repeated experiments cannot overwrite earlier output. Output directories must already exist.

## JavaScript interface

```js
import {model, targets, buildCorpus} from './models/index.mjs';
import {Reference} from './runner/reference.mjs';

const patch = model.blank();
const target = targets.idealTarget('triangle');
const proposal = model.fitLevels(patch, target);
const approximation = model.evaluate(proposal, target);
const derivative = model.renderWithLevelJacobian(proposal);
const reference = new Reference();
try {
  const measured = await reference.score(proposal, target);
  // Keep approximation and measured as separate observations.
} finally {
  await reference.close();
}
```

`model` exposes the six-operator renderer, analytic level Jacobian, damped level fitting, carrier fitting, quantized proposals, interpolation and SysEx codecs. `targets` exposes exact formulas, convex blending, analytical Fourier coefficients and energy. `model.analyzeMany(wave, targets)` shares the candidate FFT across targets while keeping every spectral bin and the original objective. `Reference.scoreMany(patch, targets, {preview:false})` shares actual native captures and pitch transforms; omit the option when display curves are needed.

The smooth proposal model runs at 48 kHz with a 187.5 Hz fundamental and 127 target harmonics. Its objective combines 85% squared waveform residual with 15% spectral residual. Its level derivatives describe a relaxed oscillator model; rounded legal DX7 proposals still require acceptance checks.

Native ranking independently minimizes the worst relative squared residual over A2/A3/A4, velocity 100, 48 kHz, and 4,096 samples starting 150 ms after note-on. It retains all target harmonics strictly below Nyquist and refines the phase to a correlation tolerance of 1e-10. It records the SHA-256 of the executable actually launched. A custom executable's hash identifies its bytes; the bundled source manifest describes the bundled sources, not an arbitrary replacement's provenance.

Scores are normalized correlations. For example, a 0.99 match corresponds to `sqrt(1 - 0.99**2)`, about 14.1% relative RMS residual. A cell's model champion and native champion can be different patches; subtracting their displayed scores does not measure prediction error. Score the same patch with both models when assessing that gap.

## Research corpus

`buildCorpus(table)` accepts the version 4 table format and returns:

- `sourceTable`: an independent copy of every supplied field, including native measurements, targets, scores and optimizer state if present.
- `candidates`: legal patches indexed by exact SysEx bytes, with complete bytes and every source cell/role. Distinct silent-operator codes remain distinct.
- Model, target and metric versions, so downstream experiments can reject incompatible observations.

Each origin separates the board's `currentTargetKey` from the observation's `targetKey`. Stale measurements keep their saved target when available; a stale compact export has `targetKey:null` because its old target is unknown. Never use those unknown-target scores as training labels for the current anchors.

The normal table download contains model and native champions, not the optimizer's alternate elites or raw captures. The corpus preserves everything provided; it cannot reconstruct data absent from its input. When working with a full checkpoint, every supplied elite is also indexed. A corpus contains observations, not trusted training labels or proof of optimality. Imported patches must be remeasured before changing native champions.

The current search checkpoints retain up to 16 model elites per cell and an independent native champion. Restarting now restores the complete valid saved pool. Historical named scans remain useful seed sources: a newer scan can improve on average while an older one still contains better patches in individual cells.

## Route to a wavetable-remix VST

Use this library to run reproducible offline experiments and compare native measurements with smooth-model predictions. Build a corpus keyed by target weights, algorithm and exact patch codes. Train or fit any predictor against measurements of the **same** patch, separating held-out patches and scans from training data.

For an initial instrument, precompute candidate patches and rendered tables off the audio thread. A real-time layer can select or crossfade these resources. DX7 parameter interpolation is quantized and does not guarantee a waveform blend; independently render intermediate patches. Multi-pitch testing, transients, release tails, velocity response, aliasing, phase alignment and transition smoothness remain implementation and validation work for the VST.

The native wrapper and combined engine are GPL-3.0-or-later as documented in [native/README.md](../native/README.md). Upstream notices and corresponding engine sources remain in the repository. No new license is asserted for unrelated repository files.
