# DexFraggler plugin architecture

DexFraggler is the new product layer around the repository's existing native DX7 research engine. The plugin is not a renamed Dexed bank. A DX7 patch is an input to native cell computation; the playable resource is a computed waveform table.

## Resource model

Each immutable `WaveformTable` contains one to sixteen waveform banks. Every bank has 32 rows and 32 columns, and every cell contains:

- the legal native `wf::Patch` that generated it;
- a 2,048-sample cyclic frame;
- a `computed` marker and observed peak level.

The row/column dimensions intentionally preserve the current search model, while the bank dimension makes a bank a crossfade axis instead of a list of 32 unrelated programs. `WaveformTable::sample()` performs trilinear interpolation over bank, row, and column, followed by cyclic phase interpolation. Missing or still-uncomputed cells retain a clearly marked deterministic fallback waveform so a host can open safely while a worker builds native cells.

## Native rebuild boundary

`WaveformTableBuilder` calls the vendored Mark I engine through `wf::renderPatch()`. It renders a held note, skips a settling interval, extracts one phase-bearing cycle, removes only the measured DC offset, and stores the frame. This is a worker/tool operation. No native renderer, file I/O, allocation, mutex, or table rebuild is allowed from a realtime callback.

`DexFragglerTableTool --output table.dfwt --banks 2 --max-cells 1024` creates a portable table. `--max-cells 0` computes every requested bank. The JUCE processor starts with a safe fallback, builds the first bank in a worker, and can load a completed `.dfwt` through its editor. A future table browser can replace the same immutable snapshot without changing the voice engine.

## Host translations

`plugin/include/dexfraggler/RealtimeEngine.h` is the shared audio/MIDI layer.

- `plugin/juce` adapts it to `AudioProcessor`, VST3, standalone, and AUv3. AUv3 is enabled only with an Apple Xcode CMake generator because JUCE emits it as an app extension.
- `plugin/lv2` adapts the same engine to an LV2 audio port, atom sequence MIDI input, and three continuous table coordinates. Its `.ttl` metadata lives beside the adapter.

Both adapters consume the same table snapshot and have the same modulation axes. The JUCE editor exposes the base coordinates and mod-wheel routes; the remaining aftertouch and pitch-bend routes are APVTS parameters and are available to host automation.

## Verification boundary

The native C++ test proves one bounded native cell rebuild, table serialization, trilinear interpolation, arbitrary-axis modulation, and realtime playback. CI builds that core on Linux and retains the existing Windows native-reference suite. JUCE format compilation is host/toolchain-specific; VST3/AUv3 package discovery, DAW loading, LV2 host discovery, MIDI timing, and listening remain separate host-validation gates.
