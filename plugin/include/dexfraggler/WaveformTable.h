#pragma once

#include "Dx7Engine.h"
#include "Patch.h"

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace dexfraggler {

inline constexpr std::size_t tableRows = 32;
inline constexpr std::size_t tableColumns = 32;
inline constexpr std::size_t tableCellCount = tableRows * tableColumns;
inline constexpr std::size_t tableFrameSize = 2048;
inline constexpr std::uint32_t tableFileVersion = 1;

struct CellAddress {
    std::size_t bank = 0;
    std::size_t row = 0;
    std::size_t column = 0;
};

// These are continuous coordinates. A bank is a first-class interpolation
// axis, rather than a MIDI-program selector. A modulation route may move any
// of the three table axes and phase may be modulated independently.
struct TableAddress {
    float bank = 0.0f;
    float row = 0.0f;
    float column = 0.0f;
    float phase = 0.0f;
};

struct ModulationState {
    float pitchBend = 0.0f; // -1..1, after the host's pitch-range mapping
    float modWheel = 0.0f;  // 0..1
    float aftertouch = 0.0f; // 0..1
    float expression = 1.0f; // 0..1
    float velocity = 1.0f; // 0..1
};

enum class ModulationSource : std::uint8_t {
    pitchBend,
    modWheel,
    aftertouch,
    expression,
    velocity
};

enum class TableAxis : std::uint8_t {
    bank,
    row,
    column,
    phase
};

enum class ModulationCurve : std::uint8_t {
    linear,
    smooth
};

struct ModulationRoute {
    ModulationSource source = ModulationSource::modWheel;
    TableAxis axis = TableAxis::column;
    float amount = 0.0f;
    ModulationCurve curve = ModulationCurve::linear;
};

// Fixed-capacity so route changes are safe to make at a block boundary and
// apply() remains allocation-free on the audio thread.
class ModulationMatrix {
public:
    static constexpr std::size_t maxRoutes = 32;

    void clear() noexcept;
    bool addRoute(ModulationRoute route) noexcept;
    bool setAmount(ModulationSource source, TableAxis axis, float amount) noexcept;
    TableAddress apply(TableAddress base, const ModulationState& state,
                       float maxBank, float maxRow, float maxColumn) const noexcept;

    std::size_t size() const noexcept { return routeCount; }
    const ModulationRoute& route(std::size_t index) const noexcept { return routes[index]; }

private:
    std::array<ModulationRoute, maxRoutes> routes{};
    std::size_t routeCount = 0;
};

struct WaveformCell {
    wf::Patch patch = wf::Patch::init();
    std::vector<float> samples;
    bool computed = false;
    float peak = 0.0f;
};

class WaveformTable {
public:
    static std::shared_ptr<WaveformTable> makeFallback(std::size_t bankCount = 4);

    std::size_t bankCount() const noexcept { return banks.size(); }
    std::size_t frameSize() const noexcept { return tableFrameSize; }
    std::size_t computedCellCount() const noexcept;
    std::size_t totalCellCount() const noexcept { return banks.size() * tableCellCount; }

    const WaveformCell* cell(std::size_t bank, std::size_t row,
                             std::size_t column) const noexcept;
    WaveformCell* cell(std::size_t bank, std::size_t row,
                       std::size_t column) noexcept;

    // Rebuilds one cell from the vendored native DX7 engine. This function is
    // intentionally a worker/tool operation; it allocates and must never run
    // from processBlock or an LV2 run callback.
    bool rebuildNativeCell(CellAddress address, int note = 45, int velocity = 100,
                           double settleSeconds = 0.25,
                           double renderSeconds = 0.75);

    // Trilinear interpolation across bank, row and column, then linear
    // interpolation around the cyclic frame. No allocation or locks occur.
    float sample(TableAddress address) const noexcept;

    bool saveBinary(const std::string& path, std::string& error) const;
    static std::shared_ptr<WaveformTable> loadBinary(const std::string& path,
                                                     std::string& error);

private:
    struct Bank {
        std::string name;
        std::vector<WaveformCell> cells;
    };

    explicit WaveformTable(std::size_t bankCount);
    std::vector<Bank> banks;

    static std::size_t cellIndex(std::size_t row, std::size_t column) noexcept;
    static float sampleCell(const WaveformCell& cell, float phase) noexcept;
};

struct TableBuildProgress {
    std::size_t completed = 0;
    std::size_t total = 0;
};

class WaveformTableBuilder {
public:
    using ProgressCallback = std::function<void(const TableBuildProgress&)>;

    // Builds the requested number of native cells from deterministic DX7
    // patches. maxCells == 0 means every cell. Unfinished cells retain their
    // explicit fallback waveform and computed=false marker.
    static std::shared_ptr<WaveformTable> buildDefault(
        std::size_t bankCount = 2,
        std::size_t maxCells = tableCellCount,
        const std::atomic_bool* cancel = nullptr,
        ProgressCallback progress = {});
};

} // namespace dexfraggler
