#include "Dx7Engine.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <future>
#include <iostream>
#include <numeric>
#include <random>
#include <set>
#include <stdexcept>
#include <string>

namespace {
void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

double rms(const std::vector<float>& audio, size_t from = 0) {
    double energy = 0;
    for (size_t i = from; i < audio.size(); ++i) {
        require(std::isfinite(audio[i]) && std::abs(audio[i]) <= 1.0f, "Non-finite or out-of-range engine output");
        energy += audio[i] * audio[i];
    }
    return std::sqrt(energy / std::max<size_t>(1, audio.size() - from));
}

double sineFrequency(const std::vector<float>& audio, size_t start = 9600) {
    size_t first = 0, last = 0, crossings = 0;
    for (size_t i = start + 1; i < audio.size(); ++i) {
        if (audio[i - 1] <= 0 && audio[i] > 0) {
            if (crossings == 0) first = i;
            last = i;
            ++crossings;
        }
    }
    require(crossings > 2 && last > first, "Insufficient sine crossings");
    return static_cast<double>(crossings - 1) * wf::engineSampleRate / (last - first);
}

void testSysex() {
    std::mt19937 random(0x445837);
    std::set<std::string> ids;
    const auto& parameters = wf::Patch::parameters();
    for (const auto& parameter : parameters) {
        require(!parameter.id.empty() && !parameter.name.empty(), "Missing parameter metadata");
        require(ids.insert(parameter.id).second, "Duplicate parameter identifier");
    }
    require(ids.size() == 145, "Voice metadata must contain 145 acoustic parameters");
    for (int iteration = 0; iteration < 64; ++iteration) {
        std::array<wf::Patch, 32> bank;
        for (auto& patch : bank) {
            for (int field = 0; field < 145; ++field)
                patch.data[field] = static_cast<uint8_t>(random() % (parameters[field].maxValue + 1));
            for (int field = 145; field < 155; ++field) patch.data[field] = random() & 127;
            patch.data[155] = 63;
            const auto encoded = wf::encodeVoice(patch, iteration % 16);
            require(encoded.size() == 163 && encoded[2] == iteration % 16, "Wrong single dump framing");
            std::string error;
            const auto decoded = wf::decodeSysex(encoded.data(), encoded.size(), error);
            require(error.empty() && decoded.size() == 1 && decoded.front().data == patch.data,
                    "Single voice byte-exact round trip failed: " + error);
        }
        auto encoded = wf::encodeBank(bank, iteration % 16);
        require(encoded.size() == 4104 && encoded[4] == 0x20 && encoded[5] == 0, "Wrong bank framing");
        std::string error;
        const auto decoded = wf::decodeSysex(encoded.data(), encoded.size(), error);
        require(error.empty() && decoded.size() == bank.size(), "Bank decode failed: " + error);
        for (size_t i = 0; i < bank.size(); ++i)
            require(decoded[i].data == bank[i].data, "Bank byte-exact round trip failed");
        encoded[64] ^= 1;
        require(wf::decodeSysex(encoded.data(), encoded.size(), error).empty() && !error.empty(),
                "Corrupt bank checksum was accepted");
    }

    auto voice = wf::encodeVoice(wf::Patch::init());
    std::string error;
    for (size_t size = 0; size < voice.size(); ++size)
        require(wf::decodeSysex(voice.data(), size, error).empty() && !error.empty(), "Truncated dump accepted");
    auto invalid = voice;
    invalid[3] = 1;
    require(wf::decodeSysex(invalid.data(), invalid.size(), error).empty(), "Unknown format accepted");
    invalid = voice; invalid[5]++;
    require(wf::decodeSysex(invalid.data(), invalid.size(), error).empty(), "Wrong byte count accepted");
    invalid = voice; invalid[10] |= 128;
    require(wf::decodeSysex(invalid.data(), invalid.size(), error).empty(), "8-bit payload accepted");
    invalid = voice; invalid[6] = 127;
    unsigned sum = 0;
    for (size_t i = 6; i < 161; ++i) sum += invalid[i];
    invalid[161] = (0u - sum) & 127;
    require(wf::decodeSysex(invalid.data(), invalid.size(), error).empty(), "Out-of-range EG parameter accepted");
    const auto secondVoice = voice;
    voice.insert(voice.end(), secondVoice.begin(), secondVoice.end());
    require(wf::decodeSysex(voice.data(), voice.size(), error).size() == 2, "Concatenated dumps failed");

    // Independent bit-field oracle from Yamaha's VMEM data sheet.
    std::array<wf::Patch, 32> bank;
    bank.fill(wf::Patch::init());
    auto& p = bank[0].data;
    p[11] = 2; p[12] = 3; p[13] = 5; p[20] = 13;
    p[14] = 2; p[15] = 7; p[17] = 1; p[18] = 27;
    p[135] = 6; p[136] = 1; p[141] = 1; p[142] = 5; p[143] = 6;
    const auto packed = wf::encodeBank(bank);
    require(packed[6 + 11] == 14 && packed[6 + 12] == 109 && packed[6 + 13] == 30
            && packed[6 + 15] == 55 && packed[6 + 111] == 14 && packed[6 + 116] == 107,
            "VMEM bit layout differs from Yamaha specification");
    std::cout << "PASS SysEx: 2048 randomized single voices, 64 banks, malformed framing/checksum/ranges, VMEM bit oracle\n";
}

void testAllAlgorithmsAndBounds() {
    for (int algorithm = 0; algorithm < 32; ++algorithm) {
        auto patch = wf::Patch::init();
        patch.data[134] = static_cast<uint8_t>(algorithm);
        patch.data[135] = 6;
        for (int op = 0; op < 6; ++op) patch.data[op * 21 + 16] = wf::isCarrier(algorithm, op) ? 85 : 65;
        const auto audio = wf::renderPatch(patch, 60, 100, 0.12, 0.1);
        require(rms(audio) > 0.0001, "Silent algorithm " + std::to_string(algorithm + 1));
        require(wf::renderPatch(patch, 60, 100, 0.12, 0.1) == audio, "Nondeterministic feedback rendering");
    }
    // Multi-operator feedback paths must differ from the equivalent serial paths.
    for (const int algorithm : {3, 5}) {
        auto patch = wf::Patch::init();
        patch.data[134] = static_cast<uint8_t>(algorithm);
        for (int op = 0; op < 6; ++op) patch.data[op * 21 + 16] = 90;
        const auto dry = wf::renderPatch(patch, 60, 100, 0.1, 0.1);
        patch.data[135] = 7;
        require(dry != wf::renderPatch(patch, 60, 100, 0.1, 0.1), "Algorithm 4/6 feedback did not affect audio");
    }
    std::mt19937 random(2037);
    const auto& parameters = wf::Patch::parameters();
    for (int trial = 0; trial < 192; ++trial) {
        auto patch = wf::Patch::init();
        for (int field = 0; field < 145; ++field)
            patch.data[field] = static_cast<uint8_t>(trial == 0 ? parameters[field].maxValue
                : trial == 1 ? 0 : random() % (parameters[field].maxValue + 1));
        const auto audio = wf::renderPatch(patch, trial % 128, (trial * 31) % 127 + 1, 0.04, 0.025);
        (void) rms(audio);
    }
    std::cout << "PASS engine: all 32 algorithms, multi-operator feedback, deterministic renders, 192 complete-parameter/extreme patches\n";
}

void testMusicalBehavior() {
    auto patch = wf::Patch::init();
    auto audio = wf::renderPatch(patch, 69, 100, 0.8, 0.8);
    require(std::abs(sineFrequency(audio) - 440) < 1.0, "A4 tuning is wrong");
    patch.data[123] = 2; // OP1 coarse
    audio = wf::renderPatch(patch, 69, 100, 0.8, 0.8);
    require(std::abs(sineFrequency(audio) - 880) < 1.0, "Ratio-mode coarse frequency is wrong");
    patch.data[123] = 1; patch.data[124] = 50;
    audio = wf::renderPatch(patch, 69, 100, 0.8, 0.8);
    require(std::abs(sineFrequency(audio) - 660) < 1.0, "Ratio-mode fine frequency is wrong");
    patch.data[122] = 1; patch.data[123] = 2; patch.data[124] = 0;
    const auto low = wf::renderPatch(patch, 36, 100, 0.8, 0.8);
    const auto high = wf::renderPatch(patch, 96, 100, 0.8, 0.8);
    require(low == high && std::abs(sineFrequency(low) - 100) < 1.0, "Fixed frequency tracked MIDI note");

    patch = wf::Patch::init();
    patch.data[144] = 36;
    require(std::abs(sineFrequency(wf::renderPatch(patch, 69, 100, 0.8, 0.8)) - 880) < 1.0, "Transpose failed");
    patch = wf::Patch::init(); patch.data[120] = 7;
    require(rms(wf::renderPatch(patch, 69, 127, 0.4, 0.4)) > 2 * rms(wf::renderPatch(patch, 69, 20, 0.4, 0.4)),
            "Velocity sensitivity failed");
    patch = wf::Patch::init(); patch.data[115] = 99; patch.data[117] = 0; // negative linear right key scaling
    require(rms(wf::renderPatch(patch, 48, 100, 0.4, 0.4)) > 2 * rms(wf::renderPatch(patch, 108, 100, 0.4, 0.4)),
            "Keyboard level scaling failed");

    patch = wf::Patch::init(); patch.data[139] = 75; patch.data[143] = 7; patch.data[137] = 65;
    auto previous = wf::renderPatch(patch, 69, 100, 0.2, 0.2);
    for (int wave = 0; wave < 6; ++wave) {
        patch.data[142] = static_cast<uint8_t>(wave);
        const auto modulated = wf::renderPatch(patch, 69, 100, 0.2, 0.2);
        require(modulated != previous, "LFO waveform failed to affect pitch");
        previous = modulated;
    }
    patch = wf::Patch::init(); patch.data[130] = 80; patch.data[131] = 80; patch.data[132] = 80;
    require(sineFrequency(wf::renderPatch(patch, 69, 100, 0.8, 0.8)) > 600, "Pitch envelope failed");
    patch = wf::Patch::init(); patch.data[155] = 0;
    require(rms(wf::renderPatch(patch, 69, 100, 0.1, 0.1)) == 0, "Operator enable mask failed");
    std::cout << "PASS musical behavior: A440, ratio/fine/fixed tuning, transpose, velocity/key scaling, six LFOs, pitch EG, operator mask\n";
}

void testRealtimeAndConcurrency() {
    auto patch = wf::Patch::init();
    patch.data[134] = 5; patch.data[135] = 6;
    for (int op = 0; op < 6; ++op) patch.data[op * 21 + 16] = 80;
    const auto expected = wf::renderPatch(patch, 60, 100, 0.25, 0.137);
    wf::Dx7Voice voice;
    voice.start(patch, 60, 100);
    std::vector<float> actual(expected.size());
    const int gate = static_cast<int>(std::llround(0.137 * wf::engineSampleRate));
    for (int i = 0; i < static_cast<int>(actual.size()); ++i) {
        if (i == gate) voice.release();
        voice.render(actual.data() + i, 1);
    }
    require(actual == expected, "One-sample realtime blocks differ from offline renderer");
    auto job = [patch, expected] {
        for (int i = 0; i < 12; ++i)
            require(wf::renderPatch(patch, 60, 100, 0.25, 0.137) == expected, "Concurrent renderer changed shared tables/state");
    };
    auto a = std::async(std::launch::async, job);
    auto b = std::async(std::launch::async, job);
    job(); a.get(); b.get();

    patch = wf::Patch::init();
    patch.data[108] = 99; // fast OP1 release
    voice.start(patch, 69, 100);
    std::vector<float> segment(24000);
    voice.render(segment.data(), static_cast<int>(segment.size()));
    require(voice.active() && rms(segment) > 0.001, "Held voice stopped unexpectedly");
    patch.data[123] = 2;
    voice.updatePatch(patch);
    voice.render(segment.data(), static_cast<int>(segment.size()));
    require(std::abs(sineFrequency(segment) - 880) < 1.0, "Held-note frequency edit failed");
    voice.setPitchBend(-12);
    voice.render(segment.data(), static_cast<int>(segment.size()));
    require(std::abs(sineFrequency(segment) - 440) < 1.0, "Pitch bend failed");
    voice.release();
    voice.render(segment.data(), static_cast<int>(segment.size()));
    require(!voice.active() && rms(segment, 12000) == 0, "Release did not retire a silent voice");
    voice.start(patch, 69, 100);
    voice.stop();
    voice.render(segment.data(), static_cast<int>(segment.size()));
    require(!voice.active() && rms(segment) == 0, "Panic stop left audio active");
    std::cout << "PASS realtime: sample/block equivalence, concurrent deterministic renderers, held edits, bend, envelope retirement, panic\n";
}

void testSharedLfoClock() {
    auto patch=wf::Patch::init();
    patch.data[141]=0; // free-running phase
    patch.data[137]=48; patch.data[139]=75; patch.data[143]=7;
    patch.data[138]=0; patch.data[142]=4;
    const auto isolated=wf::renderPatch(patch,69,100,0.8,0.8);
    wf::Dx7Lfo global;
    global.reset(patch); global.keydown();
    wf::Dx7LfoFrame frame;
    wf::Dx7Voice first,late;
    first.setExternalLfo(&frame); late.setExternalLfo(&frame);
    first.start(patch,69,100);
    std::vector<float> firstAudio(isolated.size()),lateAudio(isolated.size());
    constexpr int onset=8192;
    for(int offset=0;offset<static_cast<int>(isolated.size());offset+=wf::engineBlockSize) {
        frame=global.nextBlock();
        if(offset==onset) late.start(patch,69,100);
        const int count=std::min(wf::engineBlockSize,static_cast<int>(isolated.size())-offset);
        first.render(firstAudio.data()+offset,count);
        if(offset>=onset) late.render(lateAudio.data()+offset,count);
    }
    require(firstAudio==isolated,"Shared LFO at epoch zero differs from isolated offline LFO");
    const auto privateLate=wf::renderPatch(patch,69,100,static_cast<double>(isolated.size()-onset)/wf::engineSampleRate,1.0);
    double different=0;
    for(size_t i=0;i<privateLate.size();++i) different+=std::abs(lateAudio[onset+i]-privateLate[i]);
    require(different>10,"Staggered note incorrectly restarted a private LFO");

    wf::Dx7Lfo reference,legato;
    reference.reset(patch); legato.reset(patch);
    reference.keydown(); legato.keydown();
    for(int block=0;block<300;++block) {
        if(block==70) legato.keydown(); // sync-off preserves free-running phase
        const auto a=reference.nextBlock(),b=legato.nextBlock();
        require(a.value==b.value,"LFO sync-off keydown reset oscillator phase");
    }
    std::cout<<"PASS shared LFO: exact isolated reference at epoch zero, staggered note consumes running phase, sync-off phase continuity\n";
}
} // namespace

int main() {
    try {
        testSysex();
        testAllAlgorithmsAndBounds();
        testMusicalBehavior();
        testRealtimeAndConcurrency();
        testSharedLfoClock();
        std::cout << "All engine tests passed.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "ENGINE TEST FAILURE: " << error.what() << '\n';
        return 1;
    }
}
