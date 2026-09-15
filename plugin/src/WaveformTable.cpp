#include "dexfraggler/WaveformTable.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <sstream>

namespace dexfraggler {
namespace {

constexpr char fileMagic[] = {'D', 'F', 'W', 'T'};
constexpr float pi = 3.14159265358979323846f;

float safeFloat(float value) noexcept {
    return std::isfinite(value) ? std::clamp(value, -1.0f, 1.0f) : 0.0f;
}

void writeU32(std::ostream& output, std::uint32_t value) {
    const std::array<std::uint8_t, 4> bytes{
        static_cast<std::uint8_t>(value & 0xffu),
        static_cast<std::uint8_t>((value >> 8) & 0xffu),
        static_cast<std::uint8_t>((value >> 16) & 0xffu),
        static_cast<std::uint8_t>((value >> 24) & 0xffu)};
    output.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
}

bool readU32(std::istream& input, std::uint32_t& value) {
    std::array<std::uint8_t, 4> bytes{};
    input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!input) return false;
    value = static_cast<std::uint32_t>(bytes[0]) |
        (static_cast<std::uint32_t>(bytes[1]) << 8) |
        (static_cast<std::uint32_t>(bytes[2]) << 16) |
        (static_cast<std::uint32_t>(bytes[3]) << 24);
    return true;
}

wf::Patch defaultPatch(std::size_t bank, std::size_t row, std::size_t column) {
    auto patch = wf::Patch::init();
    patch.data[134] = static_cast<std::uint8_t>(row & 31u);
    patch.data[135] = static_cast<std::uint8_t>((column + bank) & 7u);
    patch.data[137] = static_cast<std::uint8_t>(30 + ((bank * 11 + column) % 30));
    patch.data[139] = static_cast<std::uint8_t>((row * 3 + bank * 5) % 35);
    patch.data[140] = static_cast<std::uint8_t>((column + bank) % 25);
    for (int op = 0; op < 6; ++op) {
        const auto offset = op * 21;
        patch.data[offset + 16] = static_cast<std::uint8_t>(op == 5
            ? 92 : 18 + ((row + column + bank * 7 + op * 9) % 50));
        patch.data[offset + 18] = static_cast<std::uint8_t>(1 + ((row + op + bank) % 4));
    }
    patch.setName("BANK" + std::to_string(bank + 1) + " " + std::to_string(row + 1) + "." + std::to_string(column + 1));
    patch.sanitize();
    return patch;
}

float fallbackSample(std::size_t bank, std::size_t row, std::size_t column, float phase) noexcept {
    const auto theta = 2.0f * pi * phase;
    const auto sine = std::sin(theta);
    const auto triangle = 2.0f * std::abs(2.0f * (phase - std::floor(phase + 0.5f))) - 1.0f;
    const auto saw = 2.0f * (phase - std::floor(phase + 0.5f));
    const auto square = sine >= 0.0f ? 1.0f : -1.0f;
    const auto rowMix = static_cast<float>(row) / static_cast<float>(tableRows - 1);
    const auto columnMix = static_cast<float>(column) / static_cast<float>(tableColumns - 1);
    const auto bankMix = static_cast<float>(bank % 4) / 3.0f;
    const auto low = sine * (1.0f - rowMix) + triangle * rowMix;
    const auto high = saw * (1.0f - columnMix) + square * columnMix;
    const auto harmonic = std::sin(theta * static_cast<float>(1 + (bank + column) % 7)) * 0.25f;
    return safeFloat(low * (1.0f - bankMix) + high * bankMix + harmonic * rowMix);
}

} // namespace

WaveformTable::WaveformTable(std::size_t bankCount) {
    banks.resize(std::clamp<std::size_t>(bankCount, 1, 16));
    for (std::size_t bank = 0; bank < banks.size(); ++bank) {
        banks[bank].name = "Waveform Bank " + std::to_string(bank + 1);
        banks[bank].cells.resize(tableCellCount);
    }
}

std::shared_ptr<WaveformTable> WaveformTable::makeFallback(std::size_t bankCount) {
    auto table = std::shared_ptr<WaveformTable>(new WaveformTable(bankCount));
    for (std::size_t bank = 0; bank < table->banks.size(); ++bank) {
        for (std::size_t row = 0; row < tableRows; ++row) {
            for (std::size_t column = 0; column < tableColumns; ++column) {
                auto& cell = table->banks[bank].cells[cellIndex(row, column)];
                cell.patch = defaultPatch(bank, row, column);
                cell.samples.resize(tableFrameSize);
                for (std::size_t sample = 0; sample < tableFrameSize; ++sample)
                    cell.samples[sample] = fallbackSample(bank, row, column,
                        static_cast<float>(sample) / static_cast<float>(tableFrameSize));
                cell.computed = false;
                cell.peak = 1.0f;
            }
        }
    }
    return table;
}

std::size_t WaveformTable::computedCellCount() const noexcept {
    std::size_t count = 0;
    for (const auto& bank : banks)
        for (const auto& cell : bank.cells)
            count += cell.computed ? 1u : 0u;
    return count;
}

std::size_t WaveformTable::cellIndex(std::size_t row, std::size_t column) noexcept {
    return row * tableColumns + column;
}

const WaveformCell* WaveformTable::cell(std::size_t bank, std::size_t row,
                                         std::size_t column) const noexcept {
    if (bank >= banks.size() || row >= tableRows || column >= tableColumns) return nullptr;
    return &banks[bank].cells[cellIndex(row, column)];
}

WaveformCell* WaveformTable::cell(std::size_t bank, std::size_t row,
                                  std::size_t column) noexcept {
    if (bank >= banks.size() || row >= tableRows || column >= tableColumns) return nullptr;
    return &banks[bank].cells[cellIndex(row, column)];
}

bool WaveformTable::rebuildNativeCell(CellAddress address, int note, int velocity,
                                      double settleSeconds, double renderSeconds) {
    auto* target = cell(address.bank, address.row, address.column);
    if (target == nullptr || !std::isfinite(settleSeconds) || !std::isfinite(renderSeconds) ||
        settleSeconds < 0.0 || renderSeconds <= settleSeconds || renderSeconds > 600.0)
        return false;

    const auto audio = wf::renderPatch(target->patch, note, velocity, renderSeconds, renderSeconds);
    const auto frequency = 440.0 * std::pow(2.0, (static_cast<double>(note) - 69.0) / 12.0);
    if (audio.empty() || !std::isfinite(frequency) || frequency <= 0.0) return false;
    const auto period = static_cast<double>(wf::engineSampleRate) / frequency;
    const auto start = settleSeconds * static_cast<double>(wf::engineSampleRate);
    if (start + period + 2.0 >= static_cast<double>(audio.size())) return false;

    target->samples.resize(tableFrameSize);
    double sum = 0.0;
    for (std::size_t i = 0; i < tableFrameSize; ++i) {
        const auto source = start + period * static_cast<double>(i) / static_cast<double>(tableFrameSize);
        const auto left = static_cast<std::size_t>(std::floor(source));
        const auto fraction = source - static_cast<double>(left);
        const auto a = static_cast<double>(audio[left]);
        const auto b = static_cast<double>(audio[std::min(left + 1, audio.size() - 1)]);
        const auto value = static_cast<float>(a + (b - a) * fraction);
        target->samples[i] = safeFloat(value);
        sum += target->samples[i];
    }
    const auto mean = static_cast<float>(sum / static_cast<double>(tableFrameSize));
    target->peak = 0.0f;
    for (auto& value : target->samples) {
        value = safeFloat(value - mean);
        target->peak = std::max(target->peak, std::abs(value));
    }
    target->computed = true;
    return true;
}

float WaveformTable::sampleCell(const WaveformCell& cell, float phase) noexcept {
    if (cell.samples.empty()) return 0.0f;
    phase -= std::floor(phase);
    if (phase < 0.0f) phase += 1.0f;
    const auto position = phase * static_cast<float>(cell.samples.size());
    const auto left = static_cast<std::size_t>(position) % cell.samples.size();
    const auto right = (left + 1) % cell.samples.size();
    const auto fraction = position - std::floor(position);
    return cell.samples[left] + (cell.samples[right] - cell.samples[left]) * fraction;
}

float WaveformTable::sample(TableAddress address) const noexcept {
    if (banks.empty()) return 0.0f;
    address.bank = std::clamp(std::isfinite(address.bank) ? address.bank : 0.0f,
                              0.0f, static_cast<float>(banks.size() - 1));
    address.row = std::clamp(std::isfinite(address.row) ? address.row : 0.0f,
                             0.0f, static_cast<float>(tableRows - 1));
    address.column = std::clamp(std::isfinite(address.column) ? address.column : 0.0f,
                                0.0f, static_cast<float>(tableColumns - 1));
    address.phase -= std::floor(address.phase);
    if (address.phase < 0.0f) address.phase += 1.0f;

    const auto bank0 = static_cast<std::size_t>(std::floor(address.bank));
    const auto row0 = static_cast<std::size_t>(std::floor(address.row));
    const auto column0 = static_cast<std::size_t>(std::floor(address.column));
    const auto bank1 = std::min(bank0 + 1, banks.size() - 1);
    const auto row1 = std::min(row0 + 1, tableRows - 1);
    const auto column1 = std::min(column0 + 1, tableColumns - 1);
    const auto bankFraction = address.bank - static_cast<float>(bank0);
    const auto rowFraction = address.row - static_cast<float>(row0);
    const auto columnFraction = address.column - static_cast<float>(column0);

    float result = 0.0f;
    for (int b = 0; b < 2; ++b) {
        const auto bankIndex = b == 0 ? bank0 : bank1;
        const auto bankWeight = b == 0 ? 1.0f - bankFraction : bankFraction;
        for (int r = 0; r < 2; ++r) {
            const auto rowIndex = r == 0 ? row0 : row1;
            const auto rowWeight = r == 0 ? 1.0f - rowFraction : rowFraction;
            for (int c = 0; c < 2; ++c) {
                const auto columnIndex = c == 0 ? column0 : column1;
                const auto columnWeight = c == 0 ? 1.0f - columnFraction : columnFraction;
                const auto* current = cell(bankIndex, rowIndex, columnIndex);
                if (current != nullptr)
                    result += bankWeight * rowWeight * columnWeight * sampleCell(*current, address.phase);
            }
        }
    }
    return safeFloat(result);
}

bool WaveformTable::saveBinary(const std::string& path, std::string& error) const {
    error.clear();
    if (banks.empty() || banks.size() > 16) {
        error = "A table must contain between one and sixteen waveform banks.";
        return false;
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        error = "Could not open table output: " + path;
        return false;
    }
    output.write(fileMagic, sizeof(fileMagic));
    writeU32(output, tableFileVersion);
    writeU32(output, static_cast<std::uint32_t>(banks.size()));
    writeU32(output, static_cast<std::uint32_t>(tableRows));
    writeU32(output, static_cast<std::uint32_t>(tableColumns));
    writeU32(output, static_cast<std::uint32_t>(tableFrameSize));
    for (const auto& bank : banks) {
        const auto nameLength = static_cast<std::uint32_t>(std::min<std::size_t>(bank.name.size(), 255));
        writeU32(output, nameLength);
        output.write(bank.name.data(), static_cast<std::streamsize>(nameLength));
        for (const auto& cell : bank.cells) {
            const auto computed = static_cast<std::uint8_t>(cell.computed ? 1 : 0);
            output.write(reinterpret_cast<const char*>(&computed), 1);
            output.write(reinterpret_cast<const char*>(cell.patch.data.data()),
                         static_cast<std::streamsize>(cell.patch.data.size()));
            for (const auto value : cell.samples) output.write(reinterpret_cast<const char*>(&value), sizeof(value));
        }
    }
    if (!output) {
        error = "Could not finish table output: " + path;
        return false;
    }
    return true;
}

std::shared_ptr<WaveformTable> WaveformTable::loadBinary(const std::string& path, std::string& error) {
    error.clear();
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        error = "Could not open table input: " + path;
        return {};
    }
    char magic[sizeof(fileMagic)]{};
    input.read(magic, sizeof(magic));
    std::uint32_t version = 0, bankCount = 0, rows = 0, columns = 0, frameSize = 0;
    if (!input || std::memcmp(magic, fileMagic, sizeof(fileMagic)) != 0 ||
        !readU32(input, version) || !readU32(input, bankCount) || !readU32(input, rows) ||
        !readU32(input, columns) || !readU32(input, frameSize) || version != tableFileVersion ||
        bankCount == 0 || bankCount > 16 || rows != tableRows || columns != tableColumns ||
        frameSize != tableFrameSize) {
        error = "Invalid or unsupported DexFraggler waveform-table header.";
        return {};
    }
    auto table = std::shared_ptr<WaveformTable>(new WaveformTable(bankCount));
    for (auto& bank : table->banks) {
        std::uint32_t nameLength = 0;
        if (!readU32(input, nameLength) || nameLength > 255) {
            error = "Invalid waveform-bank name.";
            return {};
        }
        bank.name.resize(nameLength);
        input.read(bank.name.data(), static_cast<std::streamsize>(nameLength));
        if (!input) {
            error = "Truncated waveform-bank name.";
            return {};
        }
        for (auto& cell : bank.cells) {
            std::uint8_t computed = 0;
            input.read(reinterpret_cast<char*>(&computed), 1);
            input.read(reinterpret_cast<char*>(cell.patch.data.data()),
                       static_cast<std::streamsize>(cell.patch.data.size()));
            cell.samples.resize(tableFrameSize);
            input.read(reinterpret_cast<char*>(cell.samples.data()),
                       static_cast<std::streamsize>(cell.samples.size() * sizeof(float)));
            if (!input || computed > 1) {
                error = "Truncated or invalid waveform-table cell.";
                return {};
            }
            cell.patch.sanitize();
            cell.computed = computed != 0;
            cell.peak = 0.0f;
            for (auto& sample : cell.samples) {
                if (!std::isfinite(sample)) {
                    error = "Waveform-table cell contains non-finite audio.";
                    return {};
                }
                sample = safeFloat(sample);
                cell.peak = std::max(cell.peak, std::abs(sample));
            }
        }
    }
    return table;
}

std::shared_ptr<WaveformTable> WaveformTableBuilder::buildDefault(
    std::size_t bankCount, std::size_t maxCells, const std::atomic_bool* cancel,
    ProgressCallback progress) {
    auto table = WaveformTable::makeFallback(bankCount);
    const auto total = maxCells == 0
        ? table->totalCellCount() : std::min(maxCells, table->totalCellCount());
    if (progress) progress({0, total});
    std::size_t completed = 0;
    for (std::size_t bank = 0; bank < table->bankCount() && completed < total; ++bank) {
        for (std::size_t row = 0; row < tableRows && completed < total; ++row) {
            for (std::size_t column = 0; column < tableColumns && completed < total; ++column) {
                if (cancel != nullptr && cancel->load(std::memory_order_relaxed)) return table;
                table->rebuildNativeCell({bank, row, column});
                ++completed;
                if (progress) progress({completed, total});
            }
        }
    }
    return table;
}

} // namespace dexfraggler
