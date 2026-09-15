# Sample-to-DX7 execution plan

## Scope

Build a local-first `Import → Preview frames → Solve → Audition → Export` path for single-cycle WAVs, WAV wavetables, and pitched samples. Extend the existing ideal-target table without invalidating named scans, native Dexed verification, legal SysEx export, or resumable runner behavior.

## Baseline audit

- Existing foundation: 32 algorithms × 32 columns, ideal waveform-blend targets, persistent named scans, native three-pitch Dexed measurements, row leases, atomic checkpoints, table import/export, and the standalone calculation library.
- Current gap: there is no imported waveform target contract, audio import/parser, frame extraction/distribution, sample-specific persistence, retrieval index, training dataset builder, or interactive sample workflow.
- Current validation baseline: 62 JavaScript tests, TypeScript check, production build, lint with zero errors, and live local APIs healthy. These validate the existing ideal-target flow only.

## Milestones

### 1. Imported target contract and audio preparation — complete

- [x] Versioned periodic-wave target representation with harmonic phase and band-limit metadata.
- [x] Single-cycle WAV parser with explicit frame-size selection when needed.
- [x] WAV-wavetable frame extraction and pitched-sample pitch-aware extraction.
- [x] Normalization, alignment, previews, warnings, and 32-column distribution.
- [x] Compatibility tests proving existing ideal targets and scans remain unchanged.

### 2. Persistent imported workflows — complete

- [x] Persist source metadata, normalized frames, target identities, and affected caches in the existing named-scan config, exact target-key map, and bounded native score memo.
- [x] Reuse the existing row leases, atomic checkpoints, local pause, cancellation signal, and restart reconstruction for imported targets.

### 3. Retrieval baseline and native verification — complete baseline

- [x] Build an exact-native-observation JSONL dataset/index with bounded storage and atomic checkpoints.
- [x] Retrieve several legal candidates per algorithm, feed them to the existing refinement loop, and verify them through the native renderer.
- [x] Complete the imported-cycle path before broadening input support.

### 4. Interactive product flow — complete baseline

- [x] Import → preview frames → solve → audition → export UI.
- [x] Distinguish model proposals from native-verified results and seed neighboring frames without treating interpolation as a verified answer.

### 5. Optional predictor and benchmark — in progress

- [x] Reproducible dependency-free local training/checkpoint/inference path with retrieval fallback.
- [ ] Optional PyTorch dataset/training/checkpoint/inference path.
- [ ] Compare scratch, retrieval, and predictor-assisted search on held-out material under equal budgets.
- [ ] Document latency, native match, residual error, memory, disk use, transition quality, and limitations.

## Decisions and boundaries

- Use the current target/scoring/native renderer contracts as the foundation; do not replace the ideal-target scan.
- Keep all processing local by default. No paid services, automatic uploads, or unbounded compute.
- Imported targets retain harmonic phase and use the same three-pitch native objective; envelopes, LFO, effects, and performance behavior remain out of scope.
- Native-rendered observations remain the acceptance boundary. Model scores and parameter prediction are proposals only.
- Store exact legal patches with their native output, renderer identity, preprocessing version, and provenance when building retrieval/training data.
- Interpolated source frames carry explicit provenance and receive a small fairness penalty in source-column ranking. They remain eligible and useful, but cannot win solely because interpolation makes a target easier to score.
- Imported target scoring uses both harmonic quadratures. A cosine-only or phase-shifted frame is not silently reduced to a sine-only target.

## Blockers

- None at the start of milestone 1. Physical listening and hardware comparison will remain explicit later validation gates.

## Next executable task

Implement and test a pure local audio-preparation module for PCM WAV parsing, single-cycle validation, frame extraction, normalization/alignment, and 32-column distribution before wiring persistence or UI.
