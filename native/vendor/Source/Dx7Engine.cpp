#include "Dx7Engine.h"

#include "EngineMkI.h"
#include "msfa/dx7note.h"
#include "msfa/exp2.h"
#include "msfa/freqlut.h"
#include "msfa/lfo.h"
#include "msfa/sin.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <mutex>
#include <stdexcept>

namespace wf {
namespace {
void initializeEngine() {
    static std::once_flag once;
    std::call_once(once, [] {
        Sin::init();
        Exp2::init();
        Freqlut::init(engineSampleRate);
        Env::init_sr(engineSampleRate);
        PitchEnv::init(engineSampleRate);
        Lfo::init(engineSampleRate);
        Porta::init_sr(engineSampleRate);
        // Force parameter strings to allocate before any realtime start().
        (void) Patch::parameters();
    });
}

std::shared_ptr<TuningState> standardTuning() {
    static const auto tuning = createStandardTuning();
    return tuning;
}
} // namespace

struct Dx7Lfo::Impl { Lfo lfo{}; };
Dx7Lfo::Dx7Lfo() : impl(std::make_unique<Impl>()) { initializeEngine(); }
Dx7Lfo::~Dx7Lfo() = default;
void Dx7Lfo::reset(const Patch& patch) {
    impl->lfo=Lfo{};
    setPatch(patch);
}
void Dx7Lfo::setPatch(const Patch& patch) {
    auto sanitized=patch;
    sanitized.sanitize();
    impl->lfo.reset(sanitized.data.data()+137);
}
void Dx7Lfo::keydown() { impl->lfo.keydown(); }
Dx7LfoFrame Dx7Lfo::nextBlock() { return {impl->lfo.getsample(),impl->lfo.getdelay()}; }

struct Dx7Voice::Impl {
    EngineMkI core;
    Controllers controllers;
    Patch patch = Patch::init();
    Dx7Note note{standardTuning()};
    Lfo lfo{};
    const Dx7LfoFrame* externalLfo = nullptr;
    alignas(16) std::array<int32_t, N> integerBuffer{};
    std::array<float, N> buffer{};
    int position = N;
    int midiNote = 60;
    int velocity = 100;
    bool live = false;
    bool released = false;

    Impl() {
        initializeEngine();
        controllers.core = &core;
        controllers.mpeEnabled = false;
        controllers.wheel.range = 50;
        controllers.wheel.pitch = true;
        controllers.at.range = 50;
        controllers.at.pitch = true;
        controllers.refresh();
    }

    int transposedNote() const {
        return std::clamp(midiNote + static_cast<int>(patch.data[144]) - 24, 0, 127);
    }

    void applyOperatorSwitches() {
        for (int op = 0; op < 6; ++op)
            controllers.opSwitch[op] = (patch.data[155] & (1 << op)) ? '1' : '0';
    }

    void refill() {
        if (!live || !note.isPlaying()) {
            live = false;
            buffer.fill(0.0f);
            position = 0;
            return;
        }
        integerBuffer.fill(0);
        const auto value = externalLfo ? externalLfo->value : lfo.getsample();
        const auto delay = externalLfo ? externalLfo->delay : lfo.getdelay();
        note.compute(integerBuffer.data(), value, delay, &controllers);
        for (int i = 0; i < N; ++i) {
            // Same output quantization and scale used by Dexed. No FX or
            // normalizer are inserted, so candidate and live renders agree.
            const int32_t value16 = integerBuffer[i] >> 4;
            const int32_t quantized = value16 < -(1 << 24) ? -32768
                : value16 >= (1 << 24) ? 32767 : value16 >> 9;
            buffer[i] = static_cast<float>(quantized) / 32768.0f;
        }
        position = 0;
    }
};

Dx7Voice::Dx7Voice() : impl(std::make_unique<Impl>()) {}
Dx7Voice::~Dx7Voice() = default;
Dx7Voice::Dx7Voice(Dx7Voice&&) noexcept = default;
Dx7Voice& Dx7Voice::operator=(Dx7Voice&&) noexcept = default;

void Dx7Voice::start(const Patch& patch, int note, int velocity) {
    impl->patch = patch;
    impl->patch.sanitize();
    impl->midiNote = std::clamp(note, 0, 127);
    impl->velocity = std::clamp(velocity, 1, 127);
    impl->applyOperatorSwitches();
    impl->note.init(impl->patch.data.data(), impl->transposedNote(), impl->velocity, 1, &impl->controllers);
    if (impl->patch.data[136]) impl->note.oscSync();
    impl->lfo.reset(impl->patch.data.data() + 137);
    impl->lfo.keydown();
    impl->position = N;
    impl->released = false;
    impl->live = true;
}

void Dx7Voice::updatePatch(const Patch& patch) {
    if (impl->patch.data == patch.data) return;
    impl->patch = patch;
    impl->patch.sanitize();
    impl->applyOperatorSwitches();
    if (impl->live) {
        impl->note.update(impl->patch.data.data(), impl->transposedNote(), impl->velocity, 1);
        impl->lfo.reset(impl->patch.data.data() + 137);
    }
}

void Dx7Voice::release() {
    if (impl->live && !impl->released) {
        impl->note.keyup();
        impl->released = true;
    }
}

void Dx7Voice::stop() {
    impl->live = false;
    impl->released = true;
    impl->position = N;
    impl->buffer.fill(0.0f);
}

bool Dx7Voice::active() const { return impl->live; }

void Dx7Voice::render(float* output, int count) {
    if (!output || count <= 0) return;
    while (count > 0) {
        if (impl->position == N) impl->refill();
        const auto amount = std::min(count, N - impl->position);
        std::copy_n(impl->buffer.data() + impl->position, amount, output);
        impl->position += amount;
        output += amount;
        count -= amount;
    }
}

void Dx7Voice::setPitchBend(float semitones) {
    if (!std::isfinite(semitones)) semitones = 0;
    // Direct Q24 semitone conversion avoids rounding to a MIDI wheel value.
    impl->controllers.masterTune = static_cast<int32_t>(std::lround(std::clamp(semitones, -48.0f, 48.0f) * (16777216.0 / 12.0)));
}

void Dx7Voice::setModWheel(int value) {
    impl->controllers.modwheel_cc = std::clamp(value, 0, 127);
    impl->controllers.refresh();
}

void Dx7Voice::setAftertouch(int value) {
    impl->controllers.aftertouch_cc = std::clamp(value, 0, 127);
    impl->controllers.refresh();
}

void Dx7Voice::setExternalLfo(const Dx7LfoFrame* frame) noexcept { impl->externalLfo=frame; }

bool isCarrier(int algorithm, int operatorIndex) {
    return algorithm >= 0 && algorithm < 32 && operatorIndex >= 0 && operatorIndex < 6
        && FmCore::isCarrier(algorithm, operatorIndex);
}

std::vector<float> renderPatch(const Patch& patch, int note, int velocity,
                               double seconds, double gateSeconds) {
    if (!std::isfinite(seconds) || seconds < 0 || seconds > 600)
        throw std::invalid_argument("Render duration must be finite and between 0 and 600 seconds.");
    if (!std::isfinite(gateSeconds)) gateSeconds = seconds;
    const auto count = static_cast<int>(std::llround(seconds * engineSampleRate));
    const auto gate = std::clamp(static_cast<int>(std::llround(std::clamp(gateSeconds, 0.0, seconds) * engineSampleRate)), 0, count);
    std::vector<float> output(static_cast<size_t>(count));
    Dx7Voice voice;
    voice.start(patch, note, velocity);
    voice.render(output.data(), gate);
    voice.release();
    if (count > gate) voice.render(output.data() + gate, count - gate);
    return output;
}

PatchRenderWithTail renderPatchWithTail(const Patch& patch, int note, int velocity,
                                       double seconds, double gateSeconds, double tailSeconds) {
    if (!std::isfinite(seconds) || seconds < 0 || seconds > 600
        || !std::isfinite(tailSeconds) || tailSeconds < 0 || tailSeconds > 60)
        throw std::invalid_argument("Render prefix must be 0..600 seconds and tail guard 0..60 seconds.");
    if (!std::isfinite(gateSeconds)) gateSeconds = seconds;
    const int count = static_cast<int>(std::llround(seconds * engineSampleRate));
    const int tailCount = static_cast<int>(std::llround(tailSeconds * engineSampleRate));
    const int total = count + tailCount;
    // A gate beyond the observed timeline must remain pending, not be moved
    // earlier to the prefix endpoint or spuriously reported as a note-off.
    const double boundedGate = std::clamp(gateSeconds, 0.0, (total + 1.0) / engineSampleRate);
    const int gate = static_cast<int>(std::llround(boundedGate * engineSampleRate));
    PatchRenderWithTail result;
    result.audio.resize(static_cast<size_t>(count));
    Dx7Voice voice;
    voice.start(patch, note, velocity);
    int cursor = 0;
    auto emit = [&](float* output, int frames) {
        if (!result.noteOffOccurred && cursor == gate) { voice.release(); result.noteOffOccurred = true; }
        if (!result.noteOffOccurred && gate > cursor && gate <= cursor + frames) {
            const int beforeGate = gate - cursor;
            voice.render(output, beforeGate);
            voice.release(); result.noteOffOccurred = true;
            if (frames > beforeGate) voice.render(output + beforeGate, frames - beforeGate);
        } else voice.render(output, frames);
        cursor += frames;
    };
    emit(result.audio.data(), count);
    std::array<float, 512> scratch{};
    const int endCount = std::min(tailCount, engineSampleRate / 20);
    double power = 0, endPower = 0;
    for (int offset = 0; offset < tailCount;) {
        const int frames = std::min(static_cast<int>(scratch.size()), tailCount - offset);
        emit(scratch.data(), frames);
        for (int i = 0; i < frames; ++i) {
            const double value = scratch[static_cast<size_t>(i)];
            power += value * value;
            if (offset + i >= tailCount - endCount) endPower += value * value;
            result.tailPeak = std::max(result.tailPeak, std::abs(value));
        }
        offset += frames;
    }
    result.tailRms = std::sqrt(power / std::max(1, tailCount));
    result.tailEndRms = std::sqrt(endPower / std::max(1, endCount));
    result.activeAtTailEnd = voice.active();
    return result;
}

} // namespace wf
