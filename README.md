# DexFraggler

A private Sites workbench for a 32-algorithm × 32-slice DX7 patch table. One persistent Windows runner searches the entire map. The original FM1_WaveLab directory is preserved. All 1,024 patches from its live board (revision 1625, captured 2026-09-14 02:26:28 UTC) were retained as seeds with historical provenance. The three earlier waveform studies remain under `/studies` as an archive.

## The map

Algorithms are fixed rows; slices are fixed columns. Click a column or cell to set an anchor. Defaults: Triangle at 1, Square at 16, Saw at 32. Add sine or custom single-cycle JSON anchors anywhere. Between anchors, blend normalized complex Fourier coefficients and normalize the result; outside them, hold the nearest anchor. Default fundamentals share sine phase; custom cycles preserve supplied phase. Short input cycles are limited to their source Nyquist. Invalid or silent target paths are rejected before saving.

Every row searches legal tuning, level and feedback values with its algorithm fixed. One scheduler visits each cell once per pass, anchors first, using same-row neighbors and compatible interpolation as seeds. Failed cells get a five-minute retry delay. Changing targets invalidates only affected scores, preserves patches, and cancels the active lease. Ranked and absolute map colors only use current scores. Historical scores never color the new map.

## The important distinction

The browser shows two independent champions: a smooth mathematical proposal, and a patch measured through the compiled Dexed Mark I reference engine. Model scores cannot establish FM1 hardware accuracy. Read `/method` for equations, scoring, bandwidth, tuning, feedback, and precision limits.

The solver uses harmonic seeds, bounded damped least squares for levels, nonnegative carrier fitting, discrete tuning/topology/feedback refinement, and compatible-patch interpolation. No neural network training is required. There is no global-optimality or exhaustive-coverage claim.

## Run and maintain

- `npm run dev`: local workbench, with simulated ChatGPT sign-in on loopback.
- `npm run build`: Sites-compatible Cloudflare Worker build.
- `node --test tests/core.test.mjs tests/table.test.mjs`: mathematical, map, codec and native regression tests.
- `node tests/table-api.mjs`: local table persistence, import, lease and stale-result tests while the development server is running.
- `node tests/api-integration.mjs`: real local D1 API integration tests while the development server is running.
- `node runner/background.mjs`: persistent search, configured by ignored `.runtime/runner-config.json`.
- `powershell -File runner/install-startup.ps1`: resume after Windows sign-in.
- `powershell -File runner/install-startup.ps1 -Remove`: disable automatic startup.

Pause the table in the Site to stop its computation. This PC must be running and connected for search progress to reach the Site. Closing the browser is safe. The runner keeps a local recovery checkpoint and logs under `.runtime/`, retries failures, and uses unique claim tokens plus target generations to reject stale writes. The startup shortcut still calls `runner/background.mjs`, which now starts the table scheduler.

The runner configuration contains the private Site URL, a Sites bypass credential, and its dedicated server secret. It is intentionally excluded from Git and publication. Do not share it. Hosted runtime secrets are configured in Sites, never in `.openai/hosting.json`.

## Native reference engine

`native/bin/DexfragglerReference.exe` was compiled from the exact copied local WaveFinder/Dexed Mark I sources. The source manifest and upstream licenses are retained under `native/`. Rebuild with CMake and MSVC using `native/CMakeLists.txt`. Its persistent stdin protocol accepts 155 validated VCED bytes and returns three 4,096-sample held-note measurements at 48 kHz, after 150 ms settling. Native ranking minimizes worst relative squared RMS error across notes 45, 57 and 69. The phase fit is refined continuously; performance controls are neutral.

## State and portability

D1 migrations under `drizzle/` own the schema. Site data are authoritative. JSON table backups retain the target configuration, model/native champion patches and historical provenance, without bloating the export with all captured audio and internal trial states. Import accepts all 1,024 cells in bounded batches; candidates are re-scored, and imported scores are untrusted. The original live-board snapshot is retained separately in the adjacent `Dexfraggler-audit` directory; its normalized seed file SHA256 is `21e9588b38ce93aaf7286c796f6ce139b951e82e9cec3554fb380779a6af88a7`.

Export a single VCED patch, a complete algorithm row or slice column as a standard 32-voice VMEM bank (4,104 bytes), or the complete table JSON. Incomplete banks are rejected. Imported 32-algorithm banks populate the selected slice; single-algorithm banks populate its row in voice order. Exporting retained patches awaiting remeasurement is allowed and identified. A DX7 patch table is not an additional hardware wavetable playback mode.

WebMCP exposes `get_wavetable`, `select_wavetable_cell`, `set_wavetable_anchor`, and `set_table_running` to supported ChatGPT browsers. All four were exercised in the local browser with valid and invalid inputs and state read-back. Sites hosting remains private. The earlier study page retains its inspection and export capabilities; its separate searches are archived.

## Scope limits

Search defaults to ratio oscillators. Fixed-frequency imported patches are rendered, with their oscillator mode retained in SysEx. Detuning is optional. Mathematical model analysis remains an approximation and native evaluation is limited to the stated pitches, duration, velocity, and bandwidth. The FM1 device has not been measured. An always-on cloud compute host is not provisioned.
