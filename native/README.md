# Dexfraggler native reference renderer

Research artifact built from the current local WaveFinder source with its vendored
Dexed Mark I core. It has no JUCE, audio device, MIDI, network, or UI dependency.
`source-provenance.json` records every copied vendor file's SHA256. Original files
in `FM1_WaveFinder` are not modified. Upstream Dexed base is
`2e182b3db85c09083ab13c8b9b00565ce7d9ff85`; WaveFinder portability/correctness changes
are retained exactly. See `vendor/third_party/dx7/README.md` and bundled licenses.
The combined executable and this wrapper are GPL-3.0-or-later.

## Protocol

Run `build/Release/DexfragglerReference.exe` as one long-lived process. Send one
line per candidate containing exactly 155 decimal VCED bytes separated by commas
or whitespace. Operators are in DX7 byte order OP6 through OP1. Name bytes occupy
145 through 154. Parameter and seven-bit ranges are validated. The nonpersistent
operator mask is set to 63 internally; it is not a 156th input byte.

One flushed JSON response line is emitted per nonblank request:

```json
{"ok":true,"engine":"Dexed Mark I / WaveFinder source","sampleRate":48000,"velocity":100,"offsetSamples":7200,"captureSamples":4096,"notes":[45,57,69],"waveforms":[[],[],[]]}
```

Each waveform contains 4096 normalized floating-point PCM samples copied from a
fresh held-note render, beginning at sample 7200 (0.15 seconds). Each full render
lasts 0.30 seconds with no note-off before its end. PCM is the exact engine output,
including its 16-bit quantization and level, without added gain normalization.
JSON numbers preserve those PCM values. Invalid lines return
`{"ok":false,"error":"..."}` and processing continues. Blank lines are ignored;
EOF ends the process. Stdout contains only response JSON; `--version` emits a
single metadata JSON object. No generated PCM arrays need to be logged.

The input envelope, LFO, scaling, tuning, feedback, and sync fields are honored.
For steady-state core experiments, the caller must supply a consistent static
voice (for example R1/R2/R3=99, L1/L2/L3=99; zero modulation depths, zero velocity
and key scaling, pitch EG levels50, transpose24). A 0.15-second offset does not
guarantee a plateau for arbitrary input envelopes or stable high-feedback states.
The renderer proves agreement with these copied Dexed/WaveFinder sources, not
physical FM1 hardware equivalence.

## Build and verify

Use Visual Studio 2022 Build Tools and CMake. Configure this standalone directory,
not WaveFinder's top-level CMake project:

```powershell
cmake -S . -B build -G 'Visual Studio 17 2022' -A x64
cmake --build build --config Release --parallel 4
ctest --test-dir build -C Release --output-on-failure
py tests/smoke.py
```

The copied engine tests cover SysEx round trips/bit packing, all32 algorithms,
feedback paths4/6, tuning, quantization bounds, deterministic concurrent renders,
block handling, and shared LFO behavior. The Python protocol test sends multiple
requests through one process, verifies expected sine frequencies/amplitude, and
records compact measurements in `tests/smoke-result.json`.

The smoke test validates the vendored files against the manifest without needing
the original author's checkout. Add `--source-root C:\path\to\FM1_WaveFinder`
to compare against an independent source tree, or `--executable C:\path\to\renderer.exe`
to test another build. The report identifies the executable actually tested.

From the repository root, set `DEXFRAGGLER_NATIVE_EXE` to the absolute path of
`native/build/Release/DexfragglerReference.exe` before running the JavaScript
tests or calculation lab to use your fresh build. Otherwise Windows uses the
checked-in `native/bin/DexfragglerReference.exe`. The reference client records
the selected executable's SHA-256 in every measurement.
