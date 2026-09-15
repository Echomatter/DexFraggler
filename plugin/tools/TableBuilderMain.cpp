#include "dexfraggler/WaveformTable.h"

#include <cstdlib>
#include <iostream>
#include <string>

namespace {

void usage() {
    std::cout << "DexFragglerTableTool\n"
                 "  --output FILE       write a .dfwt computed waveform table\n"
                 "  --banks N           number of crossfade banks (1..16, default 2)\n"
                 "  --max-cells N       native cells to rebuild (default 1024; 0 = all)\n"
                 "  --version           print the table format version\n";
}

bool readNumber(const char* text, std::size_t& value) {
    if (text == nullptr || *text == '\0') return false;
    char* end = nullptr;
    const auto parsed = std::strtoull(text, &end, 10);
    if (end == text || *end != '\0') return false;
    value = static_cast<std::size_t>(parsed);
    return true;
}

} // namespace

int main(int argc, char** argv) {
    std::string outputPath;
    std::size_t bankCount = 2;
    std::size_t maxCells = dexfraggler::tableCellCount;
    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        if (argument == "--version") {
            std::cout << "{\"product\":\"DexFraggler\",\"tableFormat\":1,\"banks\":16,\"rows\":32,\"columns\":32,\"frameSize\":2048}\n";
            return 0;
        }
        if (argument == "--help" || argument == "-h") {
            usage();
            return 0;
        }
        if (argument == "--output" && i + 1 < argc) {
            outputPath = argv[++i];
            continue;
        }
        if (argument == "--banks" && i + 1 < argc && readNumber(argv[++i], bankCount)) continue;
        if (argument == "--max-cells" && i + 1 < argc && readNumber(argv[++i], maxCells)) continue;
        std::cerr << "Unknown or incomplete argument: " << argument << "\n";
        usage();
        return 2;
    }
    if (outputPath.empty() || bankCount == 0 || bankCount > 16) {
        usage();
        return 2;
    }

    std::cerr << "Building native DX7 cells...\n";
    const auto table = dexfraggler::WaveformTableBuilder::buildDefault(
        bankCount, maxCells, nullptr,
        [](const dexfraggler::TableBuildProgress& progress) {
            if (progress.total == 0) return;
            std::cerr << "\r" << progress.completed << "/" << progress.total << " cells" << std::flush;
        });
    std::cerr << "\n";
    std::string error;
    if (!table->saveBinary(outputPath, error)) {
        std::cerr << error << "\n";
        return 1;
    }
    std::cout << "{\"output\":\"" << outputPath << "\",\"banks\":" << table->bankCount()
              << ",\"cells\":" << table->totalCellCount()
              << ",\"computedCells\":" << table->computedCellCount() << "}\n";
    return 0;
}
