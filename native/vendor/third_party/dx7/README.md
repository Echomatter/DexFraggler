# Dexed / MSFA engine used by WaveFinder

Sources copied from [Dexed](https://github.com/asb2m10/dexed), commit
`2e182b3db85c09083ab13c8b9b00565ce7d9ff85` on 2026-09-08.
Original copyright and license notices remain in each file. Most MSFA sources
are Apache-2.0; `EngineMkI.cpp` is GPL-3.0-or-later. The combined application is
therefore distributed under GPL-3.0-or-later. The GPL text is included here.

The wrapper uses Dexed's **Mark I** engine, including its original DX7-style
logarithmic oscillator quantization and the two-/three-operator feedback paths
needed by algorithms 6 and 4. This is the actual Dexed synthesis engine, not an
independently approximated six-sine FM implementation. Per-voice output scaling
and 16-bit quantization follow Dexed's `PluginProcessor.cpp`.

Portability and correctness changes relative to the copied sources:

- `controllers.h` and `env.cc`: remove application-level `Dexed.h` dependency;
  initialize every controller before rendering; use modern standard `snprintf`.
- `tuning.h/.cc`, `dx7note.h/.cc`: use Dexed's standard 12TET A4=440 calculation;
  omit optional MTS-ESP, Scala/KBM tuning, and JUCE tuning dialogs. These features
  are not claimed as supported in WaveFinder.
- `EngineMkI.cpp`: initialize the shared logarithmic sine tables with
  `std::call_once`; each engine instance still owns its scratch buses.
- The wrapper initializes the sample-rate-sensitive MSFA tables exactly once at
  **48000 Hz**. Host conversion must happen outside this engine. No optimizer or
  host callback may reinitialize these global tables.
- `dx7note.cc`: initialize feedback memory, clear it on oscillator key sync, and
  apply live pitch envelope edits. `pitchenv.h/.cc` adds a stage-preserving update.
  `env.cc` keeps attack, decay, and release stage progression on held-note edits.
- `fm_core.cc`: correct carrier classification to require the main output bus;
  summed modulation buses must not keep an otherwise finished voice alive.
- `freqlut.cc`: handle extreme legal EG/bend/coarse combinations without negative
  or oversized bit shifts. Oscillator phase remains periodic modulo 2^24.

Each `wf::Dx7Voice` owns its note, patch, operator core, buffers, and LFO. A voice
accepts arbitrary output block sizes through a 64-sample internal cache. Note-on
and controls are reflected at this engine block granularity. LFOs are per voice;
this does not reproduce the original hardware's single shared free-running LFO
phase during polyphonic playing. Isolated candidate renders are deterministic.

DX7 voice and bank encoding uses the Yamaha VCED/VMEM format documented in the
included `sysex-format.txt`. That document came from Dexed's documentation.
The 145 acoustic voice bytes and 10 name bytes round-trip exactly. The extra
operator on/off mask is a transient performance parameter and is not part of
the DX7 voice/bank bulk dump. Voice decode rejects malformed framing, payload
sizes, 8-bit data, invalid checksums, and out-of-range voice parameter values.

The wrapper does not add sample playback, post effects, automatic gain
normalization, or a different oscillator model to its offline candidate renders.
