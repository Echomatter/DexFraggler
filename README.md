# DexFraggler

A private Sites workbench and a persistent Windows compute runner for constrained DX7 inverse synthesis. The original FM1_WaveLab directory is preserved. Eleven unique saved champions were imported with provenance and re-scored.

## The important distinction

The browser shows two independent champions: a smooth mathematical proposal, and a patch measured through the compiled Dexed Mark I reference engine. Model scores cannot establish FM1 hardware accuracy. Read `/method` for equations, scoring, bandwidth, tuning, feedback, and precision limits.

The solver uses harmonic seeds, bounded damped least squares for levels, nonnegative carrier fitting, discrete tuning/topology/feedback refinement, and compatible-patch interpolation. No neural network training is required. There is no global-optimality or exhaustive-coverage claim.

## Run and maintain

- `npm run dev`: local workbench, with simulated ChatGPT sign-in on loopback.
- `npm run build`: Sites-compatible Cloudflare Worker build.
- `node --test tests/core.test.mjs`: mathematical/codec/native regression tests.
- `node tests/api-integration.mjs`: real local D1 API integration tests while the development server is running.
- `node runner/background.mjs`: persistent search, configured by ignored `.runtime/runner-config.json`.
- `powershell -File runner/install-startup.ps1`: resume after Windows sign-in.
- `powershell -File runner/install-startup.ps1 -Remove`: disable automatic startup.

Pause each experiment in the Site to stop its computation. This PC must be running and connected for search progress to reach the Site. Closing the browser is safe. The runner keeps local recovery checkpoints, native champions, and logs under `.runtime/`, retries transient failures, and uses unique claim tokens plus optimistic revisions to reject stale writes.

The runner configuration contains the private Site URL, a Sites bypass credential, and its dedicated server secret. It is intentionally excluded from Git and publication. Do not share it. Hosted runtime secrets are configured in Sites, never in `.openai/hosting.json`.

## Native reference engine

`native/bin/DexfragglerReference.exe` was compiled from the exact copied local WaveFinder/Dexed Mark I sources. The source manifest and upstream licenses are retained under `native/`. Rebuild with CMake and MSVC using `native/CMakeLists.txt`. Its persistent stdin protocol accepts 155 validated VCED bytes and returns three 4,096-sample held-note measurements at 48 kHz, after 150 ms settling. Native ranking minimizes worst relative squared RMS error across notes 45, 57 and 69. The phase fit is refined continuously; performance controls are neutral.

## State and portability

D1 migrations under `drizzle/` own the schema. Site data are authoritative. Browser storage is not used for experiment persistence. JSON exports preserve the complete current state and native measurement. Import re-scores candidates (including the native champion); it does not restore trusted historical evaluation counts. Legacy individual best files, arrays, and table files up to 5 MB are accepted; imports select at most 64 distinct candidates, taking highest legacy-scored entries from large tables. Native measurements are repeated after import.

WebMCP exposes `get_experiment`, `select_target`, and `set_search_running` to supported ChatGPT browsers. All three were exercised in the local browser, including invalid inputs and state read-back. Sites hosting is private; this implementation does not change its audience.

## Scope limits

Search defaults to ratio oscillators. Fixed-frequency imported patches are rendered, with their oscillator mode retained in SysEx. Detuning is optional. Mathematical model analysis remains an approximation and native evaluation is limited to the stated pitches, duration, velocity, and bandwidth. The FM1 device has not been measured. An always-on cloud compute host is not provisioned.
