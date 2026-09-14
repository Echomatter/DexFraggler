# Local prototype

The production app runs in Node on `127.0.0.1:5173`. It uses SQLite, with no Sites login or remote worker credentials. The existing smooth model, native scoring objectives, accuracy bounds, legal DX7 codes and result-retention rules are unchanged.

Run `npm ci`, `npm run build`, then `npm run local`. Start the Windows tray or `npm run compute` to run the solver. The tray preserves its saved pause setting. The background runner starts the web server when missing and checks its health every 30 seconds. Existing hosted runner configurations are rejected rather than silently continuing to upload results.

## Data and recovery

The default database is `.runtime/local/dexfraggler.sqlite`. SQL migrations apply once and have checksums to detect modifications to already-applied migrations. Row checkpoints use a single SQLite transaction; failures roll back the complete batch. Existing lease, generation, score monotonicity and seed acknowledgment guards remain in the API.

`node scripts/backup-local.mjs new-backup.sqlite` creates a consistent, complete SQLite snapshot while the app is running. A compact table JSON export is intended for portable seeds; a full SQLite backup also retains alternate elites, optimizer state, histories and native preview arrays. Keep all `.runtime` data out of Git.

To restore, stop the app and runner, create a new directory, place the snapshot there as `dexfraggler.sqlite`, and set `DEXFRAGGLER_DATA_DIR` to that directory before starting the app. Retain the original database until the restored scans have been checked. A process inherits environment settings at launch; set this variable consistently for both the app and runner.

The full hosted-data migration was resumed after interruption and verified across two scans and 2,048 cells. Archive file hashes and all persisted cell fields were checked, including alternate candidates and native waves. The original archive and a verified SQLite snapshot remain private on the migration machine. No research results are bundled in the repository.

## Validation

- Production build and TypeScript check passed.
- All 60 model, scorer, retention, storage and boundary tests passed.
- Isolated table API tests passed concurrent leases, atomic row saves, monotonic scores, stale generations, pause and cross-origin rejection.
- Scan integration passed creation, switching, native seed remeasurement, atomic acknowledgment and desktop commands.
- Windows tray integration passed its 16 checks, including live icon state, pause persistence, owned-process priority, exports and absence of cloud credentials.
- The local production table was opened and visually inspected with saved results and the connected, paused runner.

Use a separate database and port for API tests. For example, in one PowerShell terminal set `DEXFRAGGLER_DATA_DIR` to an empty test directory and `DEXFRAGGLER_PORT` to `5174`, then run `npm start`. In another, set `DEXFRAGGLER_TEST_URL` to `http://127.0.0.1:5174` and run `node tests/table-api.mjs` or `node tests/scans-api.mjs`. The latter also requires the native renderer and a built tray executable supplied through `DEXFRAGGLER_TEST_TRAY`.

The first build attempt on the migration machine exited under system memory pressure. A retry with `NODE_OPTIONS=--max-old-space-size=384` and `RAYON_NUM_THREADS=2` passed. These are optional build settings, not reduced solver precision.

Removing the local hosting manifest does not unpublish a previously deployed Site. Hosting removal must be completed in the hosting management interface; the old hosted scan was left paused.
