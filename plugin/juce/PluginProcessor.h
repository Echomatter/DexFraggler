#pragma once

#include <juce_audio_utils/juce_audio_utils.h>

#include "dexfraggler/RealtimeEngine.h"

#include <atomic>
#include <memory>
#include <mutex>
#include <thread>

class DexFragglerAudioProcessor final : public juce::AudioProcessor {
public:
    DexFragglerAudioProcessor();
    ~DexFragglerAudioProcessor() override;

    void prepareToPlay(double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported(const BusesLayout& layouts) const override;
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "DexFraggler"; }
    bool acceptsMidi() const override { return true; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.25; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram(int) override {}
    const juce::String getProgramName(int) override { return "Computed Table"; }
    void changeProgramName(int, const juce::String&) override {}

    void getStateInformation(juce::MemoryBlock&) override;
    void setStateInformation(const void*, int) override;

    juce::AudioProcessorValueTreeState parameters;
    bool loadTableFile(const juce::File&, juce::String& error);
    juce::String tableStatus() const;
    float buildProgress() const noexcept { return nativeBuildProgress.load(std::memory_order_acquire); }

private:
    static juce::AudioProcessorValueTreeState::ParameterLayout createParameterLayout();
    void handleMidi(const juce::MidiMessage&) noexcept;
    void renderSegment(juce::AudioBuffer<float>&, int start, int count) noexcept;
    void startDefaultBuild();

    dexfraggler::RealtimeEngine engine;
    std::shared_ptr<dexfraggler::WaveformTable> table;
    std::atomic_bool cancelBuild{false};
    std::atomic<float> nativeBuildProgress{0.0f};
    std::thread buildThread;
    mutable std::mutex statusMutex;
    juce::String loadedTableName = "Fallback waveforms; native rebuild pending";
    double hostSampleRate = 48000.0;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(DexFragglerAudioProcessor)
};
