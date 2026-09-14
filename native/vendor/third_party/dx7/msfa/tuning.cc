// WaveFinder portability adapter for Dexed's standard equal-tempered tuning.
// The formula is the original Dexed/msfa StandardTuning implementation.
// Optional Scala/KBM, MTS-ESP and JUCE dialog dependencies are deliberately omitted.
#include "tuning.h"

namespace {
struct StandardTuning final : TuningState {
    int32_t midinote_to_logfreq(int midinote) override {
        constexpr int base = 50857777;
        constexpr int step = (1 << 24) / 12;
        return base + step * midinote;
    }
};
}

std::shared_ptr<TuningState> createStandardTuning() {
    return std::make_shared<StandardTuning>();
}
