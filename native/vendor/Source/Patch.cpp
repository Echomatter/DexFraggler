#include "Patch.h"

#include <algorithm>
#include <cstring>

namespace wf {

const std::array<ParameterInfo, 145>& Patch::parameters() {
    static const auto info = [] {
        std::array<ParameterInfo, 145> result{};
        constexpr const char* ids[] = {
            "r1", "r2", "r3", "r4", "l1", "l2", "l3", "l4", "breakpoint",
            "left_depth", "right_depth", "left_curve", "right_curve", "rate_scaling",
            "amp_mod_sensitivity", "velocity_sensitivity", "output_level", "osc_mode",
            "coarse", "fine", "detune"
        };
        constexpr const char* names[] = {
            "EG rate 1", "EG rate 2", "EG rate 3", "EG rate 4",
            "EG level 1", "EG level 2", "EG level 3", "EG level 4",
            "Key scale breakpoint", "Key scale left depth", "Key scale right depth",
            "Key scale left curve", "Key scale right curve", "Key rate scaling",
            "Amplitude modulation sensitivity", "Velocity sensitivity", "Output level",
            "Oscillator mode", "Frequency coarse", "Frequency fine", "Detune"
        };
        constexpr int maxima[] = {99,99,99,99,99,99,99,99,99,99,99,3,3,7,3,7,99,1,31,99,14};
        for (int op = 0; op < 6; ++op) {
            const auto prefix = "op" + std::to_string(6 - op) + "_";
            const auto label = "OP " + std::to_string(6 - op) + " ";
            for (int field = 0; field < 21; ++field)
                result[op * 21 + field] = {prefix + ids[field], label + names[field], maxima[field]};
        }
        for (int i = 0; i < 4; ++i) {
            result[126 + i] = {"pitch_r" + std::to_string(i + 1), "Pitch EG rate " + std::to_string(i + 1), 99};
            result[130 + i] = {"pitch_l" + std::to_string(i + 1), "Pitch EG level " + std::to_string(i + 1), 99};
        }
        result[134] = {"algorithm", "Algorithm", 31};
        result[135] = {"feedback", "Feedback", 7};
        result[136] = {"osc_sync", "Oscillator key sync", 1};
        result[137] = {"lfo_speed", "LFO speed", 99};
        result[138] = {"lfo_delay", "LFO delay", 99};
        result[139] = {"lfo_pitch_depth", "LFO pitch depth", 99};
        result[140] = {"lfo_amp_depth", "LFO amplitude depth", 99};
        result[141] = {"lfo_sync", "LFO key sync", 1};
        result[142] = {"lfo_wave", "LFO waveform", 5};
        result[143] = {"pitch_mod_sensitivity", "Pitch modulation sensitivity", 7};
        result[144] = {"transpose", "Transpose", 48};
        return result;
    }();
    return info;
}

Patch Patch::init() {
    Patch p;
    for (int op = 0; op < 6; ++op) {
        auto* d = p.data.data() + op * 21;
        d[0] = 99; d[1] = 99; d[2] = 99; d[3] = 60;
        d[4] = 99; d[5] = 99; d[6] = 99; d[7] = 0;
        d[8] = 39;
        d[16] = op == 5 ? 99 : 0;
        d[18] = 1;
        d[20] = 7;
    }
    for (int i = 0; i < 4; ++i) {
        p.data[126 + i] = 99;
        p.data[130 + i] = 50;
    }
    p.data[136] = 1;
    p.data[137] = 35;
    p.data[141] = 1;
    p.data[142] = 4;
    p.data[144] = 24;
    p.data[155] = 63;
    p.setName("INIT SINE");
    return p;
}

void Patch::sanitize() {
    const auto& info = parameters();
    for (size_t i = 0; i < info.size(); ++i)
        data[i] = static_cast<uint8_t>(std::min<int>(data[i], info[i].maxValue));
    for (size_t i = 145; i < 155; ++i) data[i] &= 127;
    data[155] &= 63;
}

std::string Patch::name() const {
    std::string result;
    for (int i = 145; i < 155; ++i) {
        const auto ch = data[i];
        result += ch >= 32 && ch <= 126 ? static_cast<char>(ch) : ' ';
    }
    const auto last = result.find_last_not_of(' ');
    if (last == std::string::npos) return {};
    result.resize(last + 1);
    return result;
}

void Patch::setName(const std::string& text) {
    for (int i = 0; i < 10; ++i) {
        const auto ch = i < static_cast<int>(text.size()) ? static_cast<unsigned char>(text[i]) : ' ';
        data[145 + i] = static_cast<uint8_t>(ch >= 32 && ch <= 126 ? ch : ' ');
    }
}

namespace {
uint8_t checksum(const uint8_t* data, size_t length) {
    unsigned sum = 0;
    for (size_t i = 0; i < length; ++i) sum += data[i];
    return static_cast<uint8_t>((0u - sum) & 127u);
}

void pack(const Patch& patch, uint8_t* packed) {
    Patch p = patch;
    p.sanitize();
    for (int op = 0; op < 6; ++op) {
        const auto* in = p.data.data() + op * 21;
        auto* out = packed + op * 17;
        std::copy_n(in, 11, out);
        out[11] = in[11] | (in[12] << 2);
        out[12] = in[13] | (in[20] << 3);
        out[13] = in[14] | (in[15] << 2);
        out[14] = in[16];
        out[15] = in[17] | (in[18] << 1);
        out[16] = in[19];
    }
    std::copy_n(p.data.data() + 126, 8, packed + 102);
    packed[110] = p.data[134];
    packed[111] = p.data[135] | (p.data[136] << 3);
    std::copy_n(p.data.data() + 137, 4, packed + 112);
    packed[116] = p.data[141] | (p.data[142] << 1) | (p.data[143] << 4);
    std::copy_n(p.data.data() + 144, 11, packed + 117);
}

Patch unpack(const uint8_t* packed) {
    Patch p;
    for (int op = 0; op < 6; ++op) {
        const auto* in = packed + op * 17;
        auto* out = p.data.data() + op * 21;
        std::copy_n(in, 11, out);
        out[11] = in[11] & 3;
        out[12] = (in[11] >> 2) & 3;
        out[13] = in[12] & 7;
        out[14] = in[13] & 3;
        out[15] = (in[13] >> 2) & 7;
        out[16] = in[14];
        out[17] = in[15] & 1;
        out[18] = (in[15] >> 1) & 31;
        out[19] = in[16];
        out[20] = (in[12] >> 3) & 15;
    }
    std::copy_n(packed + 102, 8, p.data.data() + 126);
    p.data[134] = packed[110] & 31;
    p.data[135] = packed[111] & 7;
    p.data[136] = (packed[111] >> 3) & 1;
    std::copy_n(packed + 112, 4, p.data.data() + 137);
    p.data[141] = packed[116] & 1;
    p.data[142] = (packed[116] >> 1) & 7;
    p.data[143] = (packed[116] >> 4) & 7;
    std::copy_n(packed + 117, 11, p.data.data() + 144);
    p.data[155] = 63;
    return p;
}

bool validParameters(const Patch& p) {
    const auto& info = Patch::parameters();
    for (size_t i = 0; i < info.size(); ++i)
        if (p.data[i] > info[i].maxValue) return false;
    return true;
}
} // namespace

std::vector<uint8_t> encodeVoice(const Patch& patch, int channel) {
    Patch p = patch;
    p.sanitize();
    std::vector<uint8_t> out{0xf0, 0x43, static_cast<uint8_t>(std::clamp(channel, 0, 15)), 0, 1, 0x1b};
    out.insert(out.end(), p.data.begin(), p.data.begin() + 155);
    out.push_back(checksum(out.data() + 6, 155));
    out.push_back(0xf7);
    return out;
}

std::vector<uint8_t> encodeBank(const std::array<Patch, 32>& bank, int channel) {
    std::vector<uint8_t> out(4104);
    const uint8_t header[] = {0xf0, 0x43, static_cast<uint8_t>(std::clamp(channel, 0, 15)), 9, 0x20, 0};
    std::copy_n(header, 6, out.begin());
    for (size_t i = 0; i < bank.size(); ++i) pack(bank[i], out.data() + 6 + i * 128);
    out[4102] = checksum(out.data() + 6, 4096);
    out[4103] = 0xf7;
    return out;
}

std::vector<Patch> decodeSysex(const void* memory, size_t size, std::string& error) {
    error.clear();
    const auto* bytes = static_cast<const uint8_t*>(memory);
    std::vector<Patch> result;
    const auto fail = [&error](const char* message) { error = message; return std::vector<Patch>{}; };
    if (bytes == nullptr || size == 0) return fail("Empty SysEx input.");
    size_t offset = 0;
    while (offset < size) {
        if (size - offset < 8) return fail("Truncated DX7 SysEx message.");
        const auto* p = bytes + offset;
        if (p[0] != 0xf0 || p[1] != 0x43 || p[2] > 15)
            return fail("Expected a Yamaha DX7 voice or bank bulk dump.");
        const size_t length = p[3] == 0 ? 155 : p[3] == 9 ? 4096 : 0;
        if (length == 0) return fail("Unsupported Yamaha dump format; expected VCED or 32-voice VMEM.");
        if (p[4] > 127 || p[5] > 127 || (static_cast<size_t>(p[4]) * 128 + p[5]) != length)
            return fail("DX7 SysEx byte count does not match its format.");
        if (length + 8 > size - offset || p[length + 7] != 0xf7)
            return fail("Truncated DX7 SysEx payload or missing end marker.");
        for (size_t i = 6; i < length + 7; ++i)
            if (p[i] > 127) return fail("DX7 SysEx data must contain only 7-bit bytes.");
        if (checksum(p + 6, length) != p[length + 6]) return fail("DX7 SysEx checksum mismatch.");
        const size_t count = length == 155 ? 1 : 32;
        for (size_t i = 0; i < count; ++i) {
            Patch patch;
            if (length == 155) {
                std::copy_n(p + 6, 155, patch.data.begin());
                patch.data[155] = 63;
            } else patch = unpack(p + 6 + 128 * i);
            if (!validParameters(patch)) return fail("DX7 patch contains an out-of-range voice parameter.");
            result.push_back(patch);
        }
        offset += length + 8;
    }
    return result;
}

} // namespace wf
