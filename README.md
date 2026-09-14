# DexFraggler

A private Sites app for a 32-algorithm × 32-slice DX7 patch table, with a persistent Windows tray runner.

Set waveform anchors on any column. Columns linearly blend exact unit-peak sine, triangle, square and saw formulas. Ideal targets never come from measured results. Rows keep their algorithm fixed while tuning, levels and feedback are optimized. Click a cell to inspect it; open Cell details for measurements, operators, routing and patch download.

## Search and precision

The smooth proposal model uses an analytic six-level Jacobian, including nested modulation and sample-delayed feedback. Damped least squares and carrier fitting propose legal quantized changes. A native Dexed Mark I process measures candidates independently at A2/A3/A4, 48 kHz, 4,096 samples per note after 150 ms settling. Ranking minimizes worst relative squared RMS error over those notes.

Native captures and Fourier projections are reused across all 32 targets in a row. The scorer evaluates finite trigonometric polynomials at arbitrary phase, using every target harmonic below Nyquist. A curvature bound guides adaptive phase refinement to a 1e-10 score tolerance. Preview arrays are generated only for improved cells. Exact SysEx keys cache captures without merging distinct patches. Row leases, target generations and atomic database batches prevent stale or regressing checkpoints.

The model remains approximate; measurements cover the stated pitches and duration. No global-optimality certificate or FM1 hardware comparison is claimed. See `/method`, `docs/native-scoring.md` and `docs/analytic-fitting.md`.

Table progress averages all 1,024 native match scores with unmeasured cells contributing zero. Every cell remains in the search indefinitely. Rank mode orders current cells against one another; equal scores share a rank.

## Windows app

- `desktop/DexFraggler.Tray.exe --root "C:\path\to\Dexfraggler"`: start the tray app.
- `powershell -File desktop/install-shortcuts.ps1 -ProjectRoot "C:\path\to\Dexfraggler"`: install Desktop and sign-in shortcuts.
- Tray menu: open DexFraggler, pause/resume, processor priority, download table, exit.
- `node runner/background.mjs`: run the same scheduler without the tray.

The runner reads ignored `.runtime/runner-config.json` containing the Site URL, Sites bypass credential and dedicated worker secret. These credentials are excluded from Git and publication. The tray and runner exchange atomic control/status files under `.runtime/`. The PC must be on for computation; closing the browser is safe.

The Site stores anchors and results automatically. Restarting reconstructs optimization from saved patches and measured champions; it does not need a trial-history archive. Table JSON downloads include anchors, targets and cell results. Single-voice and complete row/column SysEx exports preserve legal DX7 codes.

## Development and verification

- `npm run dev` and `npm run build`: Sites development server and Worker build.
- `node --test tests/*.test.mjs`: model, derivatives, scoring, cache, targets, scheduling and codecs.
- `node tests/table-api.mjs`: authenticated local D1 integration, row transactions and stale-result rejection (development server required).
- `powershell -File desktop/build.ps1`: rebuild the Windows tray executable.

D1 migrations under `drizzle/` define persisted tables. `native/` retains the engine sources, source manifest and upstream licenses; rebuild the native executable with its CMake/MSVC configuration.

WebMCP exposes `get_wavetable`, `select_wavetable_cell`, `set_wavetable_anchor` and `set_table_running` on the map and cell-details pages. Hosting remains private.
