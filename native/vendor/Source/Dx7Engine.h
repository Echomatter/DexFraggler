#pragma once

#include "Patch.h"
#include <memory>

namespace wf {

// All lookup tables are initialized once at this rate. Host-rate conversion
// belongs outside the engine; never reinitialize tables from a worker thread.
inline constexpr int engineSampleRate = 48000;
inline constexpr int engineBlockSize = 64;

struct Dx7LfoFrame {
    int32_t value = 1 << 23;
    int32_t delay = 1 << 24;
};

// One shared LFO clock for a polyphonic instrument. Call nextBlock exactly once
// per 64 engine samples, even while no voices sound. keydown is for the first
// held key, following Dexed's global LFO key-sync/delay behavior.
class Dx7Lfo {
public:
    Dx7Lfo();
    ~Dx7Lfo();
    Dx7Lfo(const Dx7Lfo&) = delete;
    Dx7Lfo& operator=(const Dx7Lfo&) = delete;
    void reset(const Patch&); // clear phase/random/delay state (prepare/panic)
    void setPatch(const Patch&); // preserve running phase while changing controls
    void keydown();
    Dx7LfoFrame nextBlock();
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};

class Dx7Voice {
public:
    Dx7Voice();
    ~Dx7Voice();
    Dx7Voice(Dx7Voice&&) noexcept;
    Dx7Voice& operator=(Dx7Voice&&) noexcept;
    Dx7Voice(const Dx7Voice&) = delete;
    Dx7Voice& operator=(const Dx7Voice&) = delete;

    // Allocation-free after construction. Each voice owns its patch and DSP
    // buffers and must be accessed by only one thread at a time.
    void start(const Patch&, int note, int velocity);
    void updatePatch(const Patch&);
    void release();
    void stop();
    bool active() const;
    // Writes (does not add) count mono samples, supporting any block size.
    void render(float* output, int count);
    void setPitchBend(float semitones);
    void setModWheel(int value);
    void setAftertouch(int value);
    // Optional stable frame owned by a shared polyphonic clock. All bound
    // voices must begin rendering on that clock's common 64-sample boundary.
    // nullptr restores the isolated per-voice LFO used by renderPatch.
    void setExternalLfo(const Dx7LfoFrame*) noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};

// Zero-based algorithm 0..31, operator index 0..5 (OP6..OP1).
bool isCarrier(int algorithm, int operatorIndex);

// Deterministic isolated offline rendering, safe alongside realtime playback.
// Length is seconds * engineSampleRate; gateSeconds is clamped to that length.
std::vector<float> renderPatch(const Patch&, int note, int velocity,
                               double seconds, double gateSeconds);

struct PatchRenderWithTail {
    std::vector<float> audio; // Original requested prefix; no crop, gain or fade.
    double tailRms = 0, tailPeak = 0, tailEndRms = 0;
    bool activeAtTailEnd = false; // Logical envelope state, not an audibility claim.
    bool noteOffOccurred = false;
};
// Continue the SAME voice into a post-prefix guard without storing that guard.
// The absolute gate may lie inside/after the guard. tailEndRms covers its final
// min(50 ms, tailSeconds); tailSeconds is bounded to 60 seconds. No audio/MIDI I/O.
PatchRenderWithTail renderPatchWithTail(const Patch&, int note, int velocity,
                                       double seconds, double gateSeconds, double tailSeconds);

} // namespace wf
