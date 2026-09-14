#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace wf {

struct ParameterInfo {
    std::string id;
    std::string name;
    int maxValue;
};

// Yamaha VCED layout: operators 6..1, then globals, then a ten-character name.
// Byte 155 is the transient operator enable mask and is NOT stored in DX7 dumps.
struct Patch {
    std::array<uint8_t, 156> data{};
    static Patch init();
    static const std::array<ParameterInfo, 145>& parameters();
    void sanitize();
    std::string name() const;
    void setName(const std::string&);
};

// Channel is zero-based. Dumps include F0/F7 and Yamaha checksum.
std::vector<uint8_t> encodeVoice(const Patch&, int channel = 0);
std::vector<uint8_t> encodeBank(const std::array<Patch, 32>&, int channel = 0);
// Accepts single dumps, 32-voice banks, or a concatenated sequence of them.
// Validation is atomic: any malformed message rejects the entire input.
std::vector<Patch> decodeSysex(const void*, size_t, std::string& error);

} // namespace wf
