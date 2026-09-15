#include "dexfraggler/RealtimeEngine.h"

#include <algorithm>
#include <cmath>

namespace dexfraggler {
namespace {

float noteFrequency(int note, float bendSemitones) noexcept {
    const auto semitone = static_cast<float>(std::clamp(note, 0, 127) - 69) + bendSemitones;
    return 440.0f * std::pow(2.0f, semitone / 12.0f);
}

} // namespace

void RealtimeEngine::prepare(double requestedRate) noexcept {
    sampleRate = std::isfinite(requestedRate) && requestedRate >= 8000.0
        ? requestedRate : static_cast<double>(wf::engineSampleRate);
    reset();
}

void RealtimeEngine::reset() noexcept {
    for (auto& voice : voices) voice = {};
    ageCounter = 0;
    pitchBendSemitones = 0.0f;
    modulation = {};
    modulation.expression = 1.0f;
}

void RealtimeEngine::setRouteAmount(ModulationSource source, TableAxis axis, float amount) noexcept {
    matrix.setAmount(source, axis, amount);
}

void RealtimeEngine::noteOn(int note, int velocity) noexcept {
    Voice* chosen = nullptr;
    for (auto& voice : voices) {
        if (!voice.active) {
            chosen = &voice;
            break;
        }
    }
    if (chosen == nullptr) {
        chosen = &voices[0];
        for (auto& voice : voices) {
            if ((!chosen->held && voice.held) ||
                (chosen->held == voice.held && voice.age < chosen->age))
                chosen = &voice;
        }
    }
    chosen->note = std::clamp(note, 0, 127);
    chosen->velocity = static_cast<float>(std::clamp(velocity, 1, 127)) / 127.0f;
    chosen->phase = 0.0f;
    chosen->level = 0.0f;
    chosen->age = ++ageCounter;
    chosen->active = true;
    chosen->held = true;
}

void RealtimeEngine::noteOff(int note) noexcept {
    for (auto& voice : voices) {
        if (voice.active && voice.note == note) voice.held = false;
    }
}

void RealtimeEngine::allNotesOff() noexcept {
    for (auto& voice : voices) voice.held = false;
}

void RealtimeEngine::setPitchBend(float semitones) noexcept {
    pitchBendSemitones = std::isfinite(semitones) ? std::clamp(semitones, -48.0f, 48.0f) : 0.0f;
    modulation.pitchBend = std::clamp(pitchBendSemitones / 2.0f, -1.0f, 1.0f);
}

void RealtimeEngine::setModWheel(float value) noexcept {
    modulation.modWheel = std::isfinite(value) ? std::clamp(value, 0.0f, 1.0f) : 0.0f;
}

void RealtimeEngine::setAftertouch(float value) noexcept {
    modulation.aftertouch = std::isfinite(value) ? std::clamp(value, 0.0f, 1.0f) : 0.0f;
}

void RealtimeEngine::setExpression(float value) noexcept {
    modulation.expression = std::isfinite(value) ? std::clamp(value, 0.0f, 1.0f) : 1.0f;
}

void RealtimeEngine::render(float* left, float* right, int frames) noexcept {
    if (left == nullptr || frames <= 0) return;
    const auto maxBank = table != nullptr && table->bankCount() > 0
        ? static_cast<float>(table->bankCount() - 1) : 0.0f;
    const auto phaseRate = static_cast<float>(1.0 / sampleRate);

    for (int frame = 0; frame < frames; ++frame) {
        float output = 0.0f;
        for (auto& voice : voices) {
            if (!voice.active) continue;
            const auto attack = std::max(0.0001f, static_cast<float>(1.0 / (sampleRate * 0.004)));
            const auto release = std::exp(static_cast<float>(-1.0 / (sampleRate * 0.18)));
            if (voice.held) voice.level = std::min(1.0f, voice.level + attack);
            else voice.level *= release;
            if (!voice.held && voice.level < 1.0e-5f) {
                voice = {};
                continue;
            }

            auto state = modulation;
            state.velocity = voice.velocity;
            auto voiceAddress = address;
            voiceAddress.phase = voice.phase;
            const auto point = matrix.apply(voiceAddress, state, maxBank,
                                      static_cast<float>(tableRows - 1),
                                      static_cast<float>(tableColumns - 1));
            const auto wave = table != nullptr ? table->sample(point) : 0.0f;
            output += wave * voice.level * (0.2f + 0.8f * voice.velocity);
            voice.phase += noteFrequency(voice.note, pitchBendSemitones) * phaseRate;
            voice.phase -= std::floor(voice.phase);
        }
        output = std::clamp(output, -1.0f, 1.0f);
        left[frame] = output;
        if (right != nullptr) right[frame] = output;
    }
}

} // namespace dexfraggler
