# DexFraggler Windows tray

A real .NET Framework WinForms tray executable with a geometry-drawn icon. Requires Windows with .NET Framework 4.5 or newer and Node.js on PATH. Build with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1`.

Start `DexFraggler.Tray.exe --root "C:\path\to\Dexfraggler"`. No user path or credential is compiled into it. One tray runs per project and Windows session. Add `--open` to open the local app in the default browser, including when the tray is already running. Opening the table preserves the existing pause setting. Startup should omit `--open`.

The menu opens the waveform table, pauses/resumes computing, selects Idle/BelowNormal/Normal/AboveNormal/High process priority, downloads table results, creates or switches named scans, imports table patches as seeds, or exits after saving a local pause. Double-click opens the table. Exit never terminates a worker or native process.

New scan creates an empty dataset with the active anchors, preserving every established scan. Switch scan resumes a saved dataset. Import table as seeds accepts a current version 4 table; choose New scan to use its anchors, or an existing scan to keep that destination's anchors and champions. Every imported patch is remeasured. Successful scan actions start the selected scan and resume this computer. The web page shows the active scan name and pending seed count.

## Installation

Copy `DexFraggler.Tray.exe` into the project's `desktop` directory. The ICO is embedded; keeping the standalone ICO and source alongside it is optional. Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-shortcuts.ps1 -ProjectRoot "C:\path\to\Dexfraggler"
```

The installer creates `DexFraggler.lnk` on Desktop with `--open` and in Startup without it. Both point directly to the Windows executable, with no console launcher. Existing same-name shortcuts for another project are rejected. The installer supports `-WhatIf` and does not launch any process. This artifact preparation does not install shortcuts or change the running tray.

## Runner/API contract

- Reads `.runtime/runner-config.json` with a loopback HTTP URL. No cloud credentials are sent. HTTP redirects are rejected. The runner starts the built local server automatically; run `npm ci` and `npm run build` before first launch.
- Atomically writes `.runtime/runner-control.json`: `{paused:boolean,priority:string,updatedAt:unixMilliseconds}`. Unknown control fields are retained. The runner must poll control changes at bounded operation boundaries. Exit writes `paused:true` before hiding the tray.
- Reads `.runtime/runner-status.json`: `{pid,nativePid,root,processStartTime,nativeProcessStartTime,running,localPaused,priority,phase,updatedAt,evaluations}`. Times can be Unix milliseconds or ISO strings. Node start time may be computed as `Date.now()-process.uptime()*1000`.
- Pause/resume makes a best-effort asynchronous POST `/api/table` with `{action:"running",running:boolean}`. A network failure preserves local control and reports pending synchronization.
- Download uses local GET `/api/table?export=1`. It requires `format: "dexfraggler-table"`, `version: 4`, `targetVersion: "ideal-waveform-v1"`, 0-1,024 cells and a 32 MB limit; a new table with no results can be exported. Formula configs contain exactly `allowDetune` and 1-32 sorted anchors `{slot,shape}` with unique slots 0-31 and shapes sine, triangle, square or saw. Imported configs may instead contain an empty anchor list, 32 normalized `periodic-wave-v1` targets with finite samples, harmonic sine/cosine arrays and provenance, plus optional source metadata. The validated response atomically replaces the chosen file and preserves all returned results and measurement metadata. Other export versions, custom/Fourier targets and harmonic-count configuration are rejected before saving.

Before changing priority, the tray verifies that node.exe is running this project's absolute runner script, or that a relative script command has a matching recorded process start time. A native process must be `<root>/native/bin/DexfragglerReference.exe` and a child of the verified Node; any recorded start time must match. Bare PID/process-name matches are insufficient.

If no owned runner exists, the tray launches Node hidden with an absolute script path and the project as working directory. Direct inherited file handles append stdout to `.runtime/runner.log` and stderr to `.runtime/runner-error.log`; logging survives tray exit. The tray records `.runtime/tray-runner-launch.json` with pid/start/root and writes `runner.pid`. It retries missing/crashed workers at most every 30 seconds. Relative-script runners without a matching start-time status cannot be safely adopted.

Scan controls use GET `/api/table?scans=1` and generation-guarded POST actions `new_scan`, `switch_scan`, and `import_seeds`. Named scans share the database but keep separate cells and pending seed queues. Scan changes supersede unfinished work. The current runner advertises `named-scans-v1`; seed acknowledgments commit atomically with row results.

## Diagnostics and verification

The following commands are Windows executables and do not open consoles. Use an absolute `--report` path to receive JSON.

```text
DexFraggler.Tray.exe --root "C:\project" --status --report "C:\output\status.json"
DexFraggler.Tray.exe --root "C:\project" --command pause --report "C:\output\pause.json"
DexFraggler.Tray.exe --root "C:\project" --command resume --report "C:\output\resume.json"
DexFraggler.Tray.exe --root "C:\project" --command priority --value BelowNormal --report "C:\output\priority.json"
DexFraggler.Tray.exe --root "C:\project" --command download-to-path --output "C:\output\table.json" --report "C:\output\download.json"
DexFraggler.Tray.exe --root "C:\project" --command list-scans --report "C:\output\scans.json"
DexFraggler.Tray.exe --root "C:\project" --command new-scan --value "New experiment" --report "C:\output\new.json"
DexFraggler.Tray.exe --root "C:\project" --command switch-scan --value SCAN_ID --report "C:\output\switch.json"
DexFraggler.Tray.exe --root "C:\project" --command import-seeds --value "new:Seeded experiment" --input "C:\output\table.json" --report "C:\output\import.json"
```

For an established import destination, pass its scan ID as `--value`.

`--status` is read-only. It checks `.runtime/tray-status.json`, live executable identity, process start time, a fresh UI heartbeat, and the initialized/visible NotifyIcon. Exit code 0 means an active verified tray; 3 means absent or stale. The heartbeat establishes actual NotifyIcon initialization but does not assert whether Windows places the icon in the visible taskbar area or overflow area.

Commands execute the same internal actions used by the menus. They do not create a visible tray, spawn workers, or use a remote listener/IPC endpoint. Pause/resume/priority update the local control file, which an existing tray and runner observe. Download calls the same validated atomic save logic as SaveFileDialog. Exit code 0 means the local command succeeded; a pause/resume report separately records `siteSynchronized`.

`--self-test --report "C:\output\self-test.json"` constructs a hidden NotifyIcon and all menus, tests atomic control changes in an isolated temporary project, and rejects an unrelated process. No network requests or live process changes occur. `build.ps1` runs this automatically. `--write-icon path.ico` exports the generated icon.

`node integration-test.mjs` tests a real temporary NotifyIcon and a separate local stub API. It verifies read-only live/dead status, pause/resume through shared menu logic, existing-tray observation, owned Node priority, local version 4 download, rejection of incompatible downloads without overwriting an existing file, exact endpoints and offline pause retention. It never touches the live project.

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\export-validation-test.ps1` checks the export validator against valid formulas and malformed configuration, target descriptors and unsupported versions. It makes no network request and does not create a tray or runner.

`OwnershipProbe.cs` tests strict process ownership and direct file logging after its separate launcher process exits. Compile it as a console executable referencing `System.Web.Extensions.dll`; pass the tray executable path, node.exe path and report path. It kills only its own isolated stub Node. The included JSON reports record passing runs. Source review confirms Desktop-only `--open` occurs before singleton exit; browser launch and the SaveFileDialog picker are not automated by these tests.

The executable is not code-signed. The installer is intentionally separate from validation so installation remains with the project owner.

