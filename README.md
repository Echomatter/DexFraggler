# DexFraggler

A research prototype for finding DX7 patches that approximate ideal waveform blends: a 32-algorithm × 32-slice table, a persistent Windows tray runner, and a standalone calculation library. This is a foundation for a future wavetable-remix VST using Dexed.

## Run the calculation models

The math tools need only Node.js 22.13 or newer; no Site account or npm installation is required:

```sh
git clone https://github.com/Echomatter/DexFraggler.git
cd DexFraggler
node scripts/model-lab.mjs score --shape triangle --out triangle-model.json
node scripts/model-lab.mjs score --shape triangle --native --out triangle-native.json
node scripts/model-lab.mjs corpus --table downloaded-table.json --out research-corpus.json
```

The native command uses the included Windows executable. Set `DEXFRAGGLER_NATIVE_EXE` to use a separately built renderer. Import `models/index.mjs` to use waveform formulas, the smooth renderer, analytic derivatives, fitting and SysEx codecs in another program. See [calculation models and VST development path](docs/calculation-models.md), [native build instructions](native/README.md), and the [performance review](docs/performance-review-2026-09-14.md).

The project is a prototype, not a VST or trained predictor. The native wrapper and combined engine are GPL-3.0-or-later; bundled third-party notices and source provenance are under `native/`.

## Table and desktop app

Run the complete app locally with Node.js 22.13 or newer:

```sh
npm ci
npm run build
npm run local
```

Open http://127.0.0.1:5173. The app binds to this computer only and needs no account or cloud credentials. On Windows, launch the tray app below to start the background solver. `npm run compute` starts the same solver from a terminal and starts the local server if needed. Keep only one solver running per checkout.

Set waveform anchors on any column. Columns linearly blend exact unit-peak sine, triangle, square and saw formulas. Ideal targets never come from measured results. Rows keep their algorithm fixed while tuning, levels and feedback are optimized. Click a cell to inspect it; open Cell details for measurements, operators, routing and patch download.

## Search and precision

The smooth proposal model uses an analytic six-level Jacobian, including nested modulation and sample-delayed feedback. Damped least squares and carrier fitting propose legal quantized changes. A native Dexed Mark I process measures candidates independently at A2/A3/A4, 48 kHz, 4,096 samples per note after 150 ms settling. Ranking minimizes worst relative squared RMS error over those notes.

Native captures and Fourier projections are reused across all 32 targets in a row. The scorer evaluates finite trigonometric polynomials at arbitrary phase, using every target harmonic below Nyquist. A curvature bound guides adaptive phase refinement to a 1e-10 score tolerance. Preview arrays are generated only for improved cells. Exact SysEx keys cache captures without merging distinct patches. Row leases, target generations and atomic database batches prevent stale or regressing checkpoints.

The table scheduler uses a two-lane priority policy: stale or least-visited cells preserve coverage, while every fourth decision can give a materially weak native result one bounded recovery visit. Candidate source columns are ranked by native loss, coverage deficit, age and model/native disagreement, which prevents easy interpolated columns from monopolizing the search. Exact row scores are memoized by patch and target generation, and the proposal cursor resumes beyond persisted model evaluations after a restart.

The model remains approximate; measurements cover the stated pitches and duration. No global-optimality certificate or FM1 hardware comparison is claimed. See `/method`, `docs/native-scoring.md` and `docs/analytic-fitting.md`.

Table progress averages all 1,024 native match scores with unmeasured cells contributing zero. Every cell remains in the search indefinitely. Rank mode orders current cells against one another; equal scores share a rank.

## Windows app

- `desktop/DexFraggler.Tray.exe --root "C:\path\to\Dexfraggler"`: start the tray app.
- `powershell -File desktop/install-shortcuts.ps1 -ProjectRoot "C:\path\to\Dexfraggler"`: install Desktop and sign-in shortcuts.
- Tray menu: open DexFraggler, pause/resume, processor priority, download table, new scan, switch scan, import table as seeds, exit.
- `node runner/background.mjs`: run the same scheduler without the tray.

The local launcher creates ignored `.runtime/runner-config.json` with a loopback URL. The tray and runner exchange atomic control/status files under `.runtime/`. The runner starts and monitors the local web server automatically. The PC must be on for computation; closing the browser is safe. Pause state survives restarts.

The local database stores independent named scans automatically. New scan keeps the current anchors and starts with no results; Switch scan resumes any saved dataset. Import table as seeds accepts current version 4 JSON: a new destination uses the uploaded anchors, while an existing destination keeps its anchors and champions. Imported patches are independently remeasured across their algorithm rows, without restoring uploaded scores or optimizer history. Pending seeds survive restarts. Restarting reconstructs optimization from saved patches and measured champions; it does not need a trial-history archive. Table JSON downloads include anchors, targets and cell results. Single-voice and complete row/column SysEx exports preserve legal DX7 codes.

## Development and verification

- `npm ci`, then `npm run dev` or `npm run build`: local development server or production build.
- `node --test tests/*.test.mjs`: model, derivatives, scoring, cache, targets, scheduling and codecs.
- `node tests/table-api.mjs`: local SQLite integration, row transactions and stale-result rejection (isolated test server required).
- `node tests/scans-api.mjs`: local native-renderer and desktop command integration for scan creation, switching and seed imports.
- `powershell -File desktop/build.ps1`: rebuild the Windows tray executable.

SQLite migrations under `drizzle/` define persisted tables and apply once per database. `native/` retains the engine sources, source manifest and upstream licenses; rebuild the native executable with its CMake/MSVC configuration.

WebMCP exposes `get_wavetable`, `select_wavetable_cell`, `set_wavetable_anchor` and `set_table_running` on the map and cell-details pages. Sharing this repository does not share your local scans.

## Complete local backups

All named scans, model elites, native measurements, pending seeds and history live in `.runtime/local/dexfraggler.sqlite`. That directory is ignored by Git. Set `DEXFRAGGLER_DATA_DIR` to choose another data directory. Do not run integration tests against your working database.

Use `node scripts/backup-local.mjs backup.sqlite` to create a consistent complete snapshot, including while the app is open. To restore, stop the local app and runner and use the snapshot in a **new data directory**. A table JSON download remains a portable seed export; it does not contain the complete research archive. Keep the original database until the restored scans have been checked.
