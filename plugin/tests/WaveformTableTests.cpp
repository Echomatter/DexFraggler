#include "dexfraggler/RealtimeEngine.h"

#include <cassert>
#include <cmath>
#include <filesystem>
#include <iostream>

namespace {

void expectFinite(float value) {
    assert(std::isfinite(value));
    assert(value >= -1.0f && value <= 1.0f);
}

} // namespace

int main() {
    using namespace dexfraggler;

    const auto fallback = WaveformTable::makeFallback(2);
    assert(fallback->bankCount() == 2);
    assert(fallback->totalCellCount() == 2 * tableCellCount);
    assert(fallback->computedCellCount() == 0);
    expectFinite(fallback->sample({0.0f, 0.0f, 0.0f, 0.25f}));
    expectFinite(fallback->sample({1.0f, 31.0f, 31.0f, 0.75f}));

    ModulationMatrix matrix;
    assert(matrix.addRoute({ModulationSource::modWheel, TableAxis::bank, 1.0f}));
    assert(matrix.addRoute({ModulationSource::aftertouch, TableAxis::row, 10.0f}));
    assert(matrix.addRoute({ModulationSource::pitchBend, TableAxis::column, 8.0f}));
    assert(matrix.addRoute({ModulationSource::expression, TableAxis::phase, 0.25f}));
    const auto moved = matrix.apply({0.5f, 4.0f, 8.0f, 0.0f}, {1.0f, 0.5f, 0.4f, 0.8f, 1.0f}, 3.0f, 31.0f, 31.0f);
    assert(moved.bank >= 1.0f);
    assert(moved.row > 7.0f);
    assert(moved.column > 7.0f);
    assert(moved.phase > 0.0f);

    // One native rebuild proves the builder is attached to the copied DX7
    // engine, while keeping this test bounded for CI and local smoke runs.
    const auto built = WaveformTableBuilder::buildDefault(1, 1);
    assert(built->computedCellCount() == 1);
    const auto* nativeCell = built->cell(0, 0, 0);
    assert(nativeCell != nullptr && nativeCell->computed);
    expectFinite(built->sample({0.0f, 0.0f, 0.0f, 0.1f}));

    const auto file = std::filesystem::temp_directory_path() / "dexfraggler-waveform-test.dfwt";
    std::string error;
    assert(built->saveBinary(file.string(), error));
    const auto loaded = WaveformTable::loadBinary(file.string(), error);
    assert(loaded != nullptr);
    assert(loaded->bankCount() == 1);
    assert(loaded->computedCellCount() == 1);
    std::error_code ignored;
    std::filesystem::remove(file, ignored);

    RealtimeEngine engine;
    engine.prepare(48000.0);
    engine.setTable(loaded.get());
    engine.setAddress({0.0f, 0.0f, 0.0f, 0.0f});
    engine.noteOn(69, 127);
    float left[256]{};
    float right[256]{};
    engine.render(left, right, 256);
    bool audible = false;
    for (int i = 0; i < 256; ++i) {
        expectFinite(left[i]);
        assert(left[i] == right[i]);
        audible = audible || std::abs(left[i]) > 1.0e-6f;
    }
    assert(audible);

    std::cout << "DexFraggler waveform-table core tests passed\n";
    return 0;
}
