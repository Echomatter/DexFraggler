# DexFraggler Windows tray

A real .NET Framework WinForms tray executable with a geometry-drawn icon. Requires Windows with .NET Framework 4.5 or newer and Node.js on PATH. Build with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1`.

Start `DexFraggler.Tray.exe --root "C:\path\to\Dexfraggler"`. No user path or credential is compiled into it. One tray runs per project and Windows session. Add `--open` to open the configured Site in the default browser, including when the tray is already running. Opening the table preserves the existing pause setting. Startup should omit `--open`.

The menu opens the waveform table, pauses/resumes computing, selects Idle/BelowNormal/Normal/AboveNormal/High process priority, downloads table results, or exits after saving a local pause. Double-click opens the table. Exit never terminates a worker or native process.

## Installation

Copy `DexFraggler.Tray.exe` into the project's `desktop` directory. The ICO is embedded; keeping the standalone ICO and source alongside it is optional. Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-shortcuts.ps1 -ProjectRoot "C:\path\to\Dexfraggler"
```

The installer creates `DexFraggler.lnk` on Desktop with `--open` and in Startup without it. Both point directly to the Windows executable, with no console launcher. It removes only the exact obsolete Startup shortcut `DexFraggler background runner.lnk`, and only if its target/arguments identify this project. Existing same-name shortcuts for another project are rejected. The installer supports `-WhatIf` and does not launch any process. It has been syntax-checked but has not been run in the user's profile as part of artifact preparation.

## Runner/API contract

- Reads `.runtime/runner-config.json`: `url`, `bypass`, `secret`, optional `cookie`. Requests send `OAI-Sites-Authorization: Bearer ...`, `x-dexfraggler-worker`, and an optional Cookie matching the existing runner. Credentials and remote response bodies are never displayed or logged. HTTP redirects are rejected.
- Atomically writes `.runtime/runner-control.json`: `{paused:boolean,priority:string,updatedAt:unixMilliseconds}`. Unknown control fields are retained. The runner must poll control changes at bounded operation boundaries. Exit writes `paused:true` before hiding the tray.
- Reads `.runtime/runner-status.json`: `{pid,nativePid,root,processStartTime,nativeProcessStartTime,running,localPaused,priority,phase,updatedAt,evaluations}`. Times can be Unix milliseconds or ISO strings. `startedAt`/`nativeStartedAt` are accepted aliases. Node start time may be computed as `Date.now()-process.uptime()*1000`.
- Pause/resume makes a best-effort asynchronous POST `/api/table` with `{action:"running",running:boolean}`. A network failure preserves local control and reports pending synchronization.
- Download uses authenticated GET `/api/table?export=1`. It checks HTTP success, the `dexfraggler-table` version 2 or 3 format, 1-1,024 cells and a 32 MB limit, then atomically replaces the chosen output file. The download preserves the full returned JSON, including config, targets and reference results.

Before changing priority, the tray verifies that node.exe is running this project's absolute runner script, or that a relative script command has a matching recorded process start time. A native process must be `<root>/native/bin/DexfragglerReference.exe` and a child of the verified Node; any recorded start time must match. Bare PID/process-name matches are insufficient.

If no owned runner exists, the tray launches Node hidden with an absolute script path and the project as working directory. Direct inherited file handles append stdout to `.runtime/runner.log` and stderr to `.runtime/runner-error.log`; logging survives tray exit. The tray records `.runtime/tray-runner-launch.json` with pid/start/root and writes `runner.pid`. It retries missing/crashed workers at most every 30 seconds. Relative-script runners without a matching start-time status cannot be safely adopted.

## Diagnostics and verification

The following commands are Windows executables and do not open consoles. Use an absolute `--report` path to receive JSON.

```text
DexFraggler.Tray.exe --root "C:\project" --status --report "C:\output\status.json"
DexFraggler.Tray.exe --root "C:\project" --command pause --report "C:\output\pause.json"
DexFraggler.Tray.exe --root "C:\project" --command resume --report "C:\output\resume.json"
DexFraggler.Tray.exe --root "C:\project" --command priority --value BelowNormal --report "C:\output\priority.json"
DexFraggler.Tray.exe --root "C:\project" --command download-to-path --output "C:\output\table.json" --report "C:\output\download.json"
```

`--status` is read-only. It checks `.runtime/tray-status.json`, live executable identity, process start time, a fresh UI heartbeat, and the initialized/visible NotifyIcon. Exit code 0 means an active verified tray; 3 means absent or stale. The heartbeat establishes actual NotifyIcon initialization but does not assert whether Windows places the icon in the visible taskbar area or overflow area.

Commands execute the same internal actions used by the menus. They do not create a visible tray, spawn workers, or use a remote listener/IPC endpoint. Pause/resume/priority update the local control file, which an existing tray and runner observe. Download calls the same validated atomic save logic as SaveFileDialog. Exit code 0 means the local command succeeded; a pause/resume report separately records `siteSynchronized`.

`--self-test --report "C:\output\self-test.json"` constructs a hidden NotifyIcon and all menus, tests atomic control changes in an isolated temporary project, and rejects an unrelated process. No network requests or live process changes occur. `build.ps1` runs this automatically. `--write-icon path.ico` exports the generated icon.

`node integration-test.mjs` tests a real temporary NotifyIcon and a separate local stub API. It verifies read-only live/dead status, pause/resume through shared menu logic, existing-tray observation, owned Node priority, authenticated v2/v3 download, invalid-download preservation, exact endpoints and offline pause retention. It never touches the live project.

`OwnershipProbe.cs` tests strict process ownership and direct file logging after its separate launcher process exits. Compile it as a console executable referencing `System.Web.Extensions.dll`; pass the tray executable path, node.exe path and report path. It kills only its own isolated stub Node. The included JSON reports record passing runs. Source review confirms Desktop-only `--open` occurs before singleton exit; browser launch and the SaveFileDialog picker are not automated by these tests.

The executable is not code-signed. The installer is intentionally separate from validation so installation remains with the project owner.

