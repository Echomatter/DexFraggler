#pragma once

#include "WaveformTable.h"

#include <array>
#include <cstddef>

namespace dexfraggler {

// Format-neutral voice engine shared by the JUCE and LV2 adapters. It plays
// immutable computed cells; it never asks the native DX7 renderer to allocate
// or rebuild audio during a host callback.
class RealtimeEngine {
public:
    static constexpr std::size_t maxVoices = 16;

    void prepare(double sampleRate) noexcept;
    void reset() noexcept;
    void setTable(const WaveformTable* table) noexcept { this->table = table; }
    void setAddress(TableAddress value) noexcept { address = value; }
    void setRouteAmount(ModulationSource source, TableAxis axis, float amount) noexcept;

    void noteOn(int note, int velocity) noexcept;
    void noteOff(int note) noexcept;
    void allNotesOff() noexcept;
    void setPitchBend(float semitones) noexcept;
    void setModWheel(float value) noexcept;
    void setAftertouch(float value) noexcept;
    void setExpression(float value) noexcept;

    void render(float* left, float* right, int frames) noexcept;

private:
    struct Voice {
        int note = -1;
        float velocity = 0.0f;
        float phase = 0.0f;
        float level = 0.0f;
        std::size_t age = 0;
        bool active = false;
        bool held = false;
    };

    const WaveformTable* table = nullptr;
    std::array<Voice, maxVoices> voices{};
    ModulationMatrix matrix;
    TableAddress address{};
    ModulationState modulation{};
    double sampleRate = wf::engineSampleRate;
    float pitchBendSemitones = 0.0f;
    std::size_t ageCounter = 0;
};

} // namespace dexfraggler
