#include "PluginProcessor.h"
#include "PluginEditor.h"

#include <algorithm>
#include <array>
#include <cmath>

namespace {

using namespace dexfraggler;

std::unique_ptr<juce::AudioParameterFloat> floatParameter(const char* id,
                                                          const char* name,
                                                          float minimum,
                                                          float maximum,
                                                          float defaultValue) {
    return std::make_unique<juce::AudioParameterFloat>(
        juce::ParameterID(id, 1), name,
        juce::NormalisableRange<float>(minimum, maximum, 0.01f), defaultValue);
}

} // namespace

juce::AudioProcessorValueTreeState::ParameterLayout DexFragglerAudioProcessor::createParameterLayout() {
    juce::AudioProcessorValueTreeState::ParameterLayout layout;
    layout.add(floatParameter("tableBank", "Table bank", 0.0f, 3.0f, 0.0f));
    layout.add(floatParameter("tableRow", "Table row", 0.0f, 31.0f, 0.0f));
    layout.add(floatParameter("tableColumn", "Table column", 0.0f, 31.0f, 0.0f));
    layout.add(floatParameter("output", "Output", -24.0f, 6.0f, -9.0f));

    // The default UI shows the mod-wheel routes. The remaining routes keep
    // the same matrix available to automation and future custom editors.
    const std::array<const char*, 9> ids{
        "mwBank", "mwRow", "mwColumn", "atBank", "atRow", "atColumn",
        "pbBank", "pbRow", "pbColumn"};
    const std::array<const char*, 9> names{
        "Mod wheel → bank", "Mod wheel → row", "Mod wheel → column",
        "Aftertouch → bank", "Aftertouch → row", "Aftertouch → column",
        "Pitch bend → bank", "Pitch bend → row", "Pitch bend → column"};
    const std::array<float, 9> maxima{3.0f, 31.0f, 31.0f, 3.0f, 31.0f, 31.0f, 3.0f, 31.0f, 31.0f};
    for (std::size_t i = 0; i < ids.size(); ++i)
        layout.add(floatParameter(ids[i], names[i], -maxima[i], maxima[i], 0.0f));
    return layout;
}

DexFragglerAudioProcessor::DexFragglerAudioProcessor()
    : AudioProcessor(BusesProperties().withOutput("Output", juce::AudioChannelSet::stereo(), true)),
      parameters(*this, nullptr, "DexFragglerState", createParameterLayout()),
      table(dexfraggler::WaveformTable::makeFallback(4)) {
    startDefaultBuild();
}

DexFragglerAudioProcessor::~DexFragglerAudioProcessor() {
    cancelBuild.store(true, std::memory_order_release);
    if (buildThread.joinable()) buildThread.join();
}

void DexFragglerAudioProcessor::startDefaultBuild() {
    buildThread = std::thread([this] {
        auto built = dexfraggler::WaveformTableBuilder::buildDefault(
            2, dexfraggler::tableCellCount, &cancelBuild,
            [this](const dexfraggler::TableBuildProgress& progress) {
                const auto ratio = progress.total == 0 ? 1.0f
                    : static_cast<float>(progress.completed) / static_cast<float>(progress.total);
                nativeBuildProgress.store(std::clamp(ratio, 0.0f, 1.0f), std::memory_order_release);
            });
        if (!cancelBuild.load(std::memory_order_acquire)) {
            std::atomic_store_explicit(&table, std::move(built), std::memory_order_release);
            std::lock_guard<std::mutex> lock(statusMutex);
            loadedTableName = "Native DX7 table (bank 1 computed)";
        }
    });
}

void DexFragglerAudioProcessor::prepareToPlay(double sampleRate, int) {
    hostSampleRate = std::isfinite(sampleRate) && sampleRate >= 8000.0 ? sampleRate : 48000.0;
    engine.prepare(hostSampleRate);
}

void DexFragglerAudioProcessor::releaseResources() {
    engine.allNotesOff();
}

bool DexFragglerAudioProcessor::isBusesLayoutSupported(const BusesLayout& layouts) const {
    const auto output = layouts.getMainOutputChannelSet();
    return output == juce::AudioChannelSet::mono() || output == juce::AudioChannelSet::stereo();
}

void DexFragglerAudioProcessor::handleMidi(const juce::MidiMessage& message) noexcept {
    if (message.isNoteOn()) {
        engine.noteOn(message.getNoteNumber(), message.getVelocity());
    } else if (message.isNoteOff()) {
        engine.noteOff(message.getNoteNumber());
    } else if (message.isPitchWheel()) {
        engine.setPitchBend((static_cast<float>(message.getPitchWheelValue()) - 8192.0f) / 8192.0f * 2.0f);
    } else if (message.isChannelPressure()) {
        engine.setAftertouch(static_cast<float>(message.getChannelPressureValue()) / 127.0f);
    } else if (message.isController()) {
        const auto value = static_cast<float>(message.getControllerValue()) / 127.0f;
        switch (message.getControllerNumber()) {
        case 1: engine.setModWheel(value); break;
        case 11: engine.setExpression(value); break;
        case 120:
        case 123: engine.allNotesOff(); break;
        default: break;
        }
    }
}

void DexFragglerAudioProcessor::renderSegment(juce::AudioBuffer<float>& buffer,
                                              int start, int count) noexcept {
    if (count <= 0) return;
    auto* left = buffer.getWritePointer(0, start);
    auto* right = buffer.getNumChannels() > 1 ? buffer.getWritePointer(1, start) : nullptr;
    engine.render(left, right, count);
    const auto gain = juce::Decibels::decibelsToGain(
        parameters.getRawParameterValue("output")->load());
    for (int i = 0; i < count; ++i) {
        left[i] = std::clamp(left[i] * gain, -1.0f, 1.0f);
        if (right != nullptr) right[i] = std::clamp(right[i] * gain, -1.0f, 1.0f);
    }
}

void DexFragglerAudioProcessor::processBlock(juce::AudioBuffer<float>& buffer,
                                             juce::MidiBuffer& midi) {
    juce::ScopedNoDenormals noDenormals;
    buffer.clear();

    const auto snapshot = std::atomic_load_explicit(&table, std::memory_order_acquire);
    engine.setTable(snapshot.get());
    engine.setAddress({
        parameters.getRawParameterValue("tableBank")->load(),
        parameters.getRawParameterValue("tableRow")->load(),
        parameters.getRawParameterValue("tableColumn")->load(), 0.0f});
    engine.setRouteAmount(ModulationSource::modWheel, TableAxis::bank,
                          parameters.getRawParameterValue("mwBank")->load());
    engine.setRouteAmount(ModulationSource::modWheel, TableAxis::row,
                          parameters.getRawParameterValue("mwRow")->load());
    engine.setRouteAmount(ModulationSource::modWheel, TableAxis::column,
                          parameters.getRawParameterValue("mwColumn")->load());
    engine.setRouteAmount(ModulationSource::aftertouch, TableAxis::bank,
                          parameters.getRawParameterValue("atBank")->load());
    engine.setRouteAmount(ModulationSource::aftertouch, TableAxis::row,
                          parameters.getRawParameterValue("atRow")->load());
    engine.setRouteAmount(ModulationSource::aftertouch, TableAxis::column,
                          parameters.getRawParameterValue("atColumn")->load());
    engine.setRouteAmount(ModulationSource::pitchBend, TableAxis::bank,
                          parameters.getRawParameterValue("pbBank")->load());
    engine.setRouteAmount(ModulationSource::pitchBend, TableAxis::row,
                          parameters.getRawParameterValue("pbRow")->load());
    engine.setRouteAmount(ModulationSource::pitchBend, TableAxis::column,
                          parameters.getRawParameterValue("pbColumn")->load());

    int cursor = 0;
    for (const auto metadata : midi) {
        const auto position = juce::jlimit(cursor, buffer.getNumSamples(), metadata.samplePosition);
        renderSegment(buffer, cursor, position - cursor);
        handleMidi(metadata.getMessage());
        cursor = position;
    }
    renderSegment(buffer, cursor, buffer.getNumSamples() - cursor);
    midi.clear();
}

bool DexFragglerAudioProcessor::loadTableFile(const juce::File& file, juce::String& error) {
    cancelBuild.store(true, std::memory_order_release);
    if (buildThread.joinable()) buildThread.join();
    std::string nativeError;
    auto loaded = dexfraggler::WaveformTable::loadBinary(file.getFullPathName().toStdString(), nativeError);
    if (!loaded) {
        error = nativeError;
        return false;
    }
    const auto computedCells = loaded->computedCellCount();
    std::atomic_store_explicit(&table, std::move(loaded), std::memory_order_release);
    nativeBuildProgress.store(1.0f, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(statusMutex);
        loadedTableName = file.getFileName() + " (" + juce::String(static_cast<int>(computedCells)) + " native cells)";
    }
    error.clear();
    return true;
}

juce::String DexFragglerAudioProcessor::tableStatus() const {
    std::lock_guard<std::mutex> lock(statusMutex);
    const auto snapshot = std::atomic_load_explicit(&table, std::memory_order_acquire);
    if (!snapshot) return "No waveform table";
    return loadedTableName + " — " + juce::String(static_cast<int>(snapshot->bankCount())) + " banks";
}

void DexFragglerAudioProcessor::getStateInformation(juce::MemoryBlock& destination) {
    if (const auto state = parameters.copyState().createXml())
        copyXmlToBinary(*state, destination);
}

void DexFragglerAudioProcessor::setStateInformation(const void* data, int sizeInBytes) {
    if (const auto state = getXmlFromBinary(data, sizeInBytes))
        if (state->hasTagName(parameters.state.getType())) parameters.replaceState(juce::ValueTree::fromXml(*state));
}

juce::AudioProcessorEditor* DexFragglerAudioProcessor::createEditor() {
    return new DexFragglerAudioProcessorEditor(*this);
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() {
    return new DexFragglerAudioProcessor();
}
