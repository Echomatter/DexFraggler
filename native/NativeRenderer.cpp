// Research wrapper for the vendored Dexed Mark I engine. GPL-3.0-or-later.
#include "Dx7Engine.h"
#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

namespace {
constexpr std::array<int, 3> notes{45, 57, 69};
constexpr int offsetSamples = 7200;
constexpr int captureSamples = 4096;
constexpr double durationSeconds = 0.30;

wf::Patch parsePatch(std::string line) {
    std::replace(line.begin(), line.end(), ',', ' ');
    std::istringstream input(line);
    wf::Patch patch;
    std::string token;
    size_t count = 0;
    while (input >> token) {
        if (count >= 155) throw std::invalid_argument("Expected exactly 155 VCED bytes; extra value found.");
        int value = -1;
        const auto result = std::from_chars(token.data(), token.data() + token.size(), value);
        if (result.ec != std::errc{} || result.ptr != token.data() + token.size() || value < 0 || value > 127)
            throw std::invalid_argument("VCED values must be decimal integers from 0 to 127.");
        if (count < 145 && value > wf::Patch::parameters()[count].maxValue)
            throw std::invalid_argument("VCED parameter value is out of range at byte " + std::to_string(count) + ".");
        patch.data[count++] = static_cast<uint8_t>(value);
    }
    if (count != 155) throw std::invalid_argument("Expected exactly 155 VCED bytes; received " + std::to_string(count) + ".");
    patch.data[155] = 63;
    return patch;
}

std::string jsonEscape(const std::string& value) {
    std::ostringstream escaped;
    for (const unsigned char ch : value) {
        if (ch == '"' || ch == '\\') escaped << '\\' << ch;
        else if (ch < 32) escaped << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(ch) << std::dec;
        else escaped << ch;
    }
    return escaped.str();
}

void emitPatch(const wf::Patch& patch) {
    std::array<std::vector<float>, 3> audio;
    for (size_t n = 0; n < notes.size(); ++n) {
        audio[n] = wf::renderPatch(patch, notes[n], 100, durationSeconds, durationSeconds);
        if (audio[n].size() < offsetSamples + captureSamples)
            throw std::runtime_error("Reference engine returned too few samples.");
        for (const float value : audio[n]) {
            if (!std::isfinite(value)) throw std::runtime_error("Reference engine returned non-finite audio.");
        }
    }
    std::ostringstream output;
    output << std::setprecision(17)
           << "{\"ok\":true,\"engine\":\"Dexed Mark I / WaveFinder source\",\"sampleRate\":48000,"
              "\"velocity\":100,\"offsetSamples\":7200,\"captureSamples\":4096,"
              "\"notes\":[45,57,69],\"waveforms\":[";
    for (size_t n = 0; n < notes.size(); ++n) {
        if (n) output << ',';
        output << '[';
        for (int i = 0; i < captureSamples; ++i) {
            if (i) output << ',';
            output << static_cast<double>(audio[n][offsetSamples + i]);
        }
        output << ']';
    }
    output << "]}\n";
    std::cout << output.str() << std::flush;
}
}

int main(int argc, char** argv) {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    if (argc > 1) {
        const std::string argument = argv[1];
        if (argument == "--version") {
            std::cout << "{\"name\":\"DexfragglerReference\",\"version\":\"1.0.0\",\"sampleRate\":48000}\n";
            return 0;
        }
        std::cerr << "Usage: DexfragglerReference.exe < newline-separated-vced.txt\n";
        return 2;
    }
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.find_first_not_of(" \t\r\n") == std::string::npos) continue;
        try { emitPatch(parsePatch(line)); }
        catch (const std::exception& error) {
            std::cout << "{\"ok\":false,\"error\":\"" << jsonEscape(error.what()) << "\"}\n" << std::flush;
        }
    }
    return std::cin.bad() ? 1 : 0;
}
