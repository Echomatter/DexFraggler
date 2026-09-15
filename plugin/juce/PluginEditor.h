#pragma once

#include "PluginProcessor.h"

#include <juce_audio_utils/juce_audio_utils.h>

class DexFragglerAudioProcessorEditor final : public juce::AudioProcessorEditor,
                                              private juce::Timer {
public:
    explicit DexFragglerAudioProcessorEditor(DexFragglerAudioProcessor&);
    ~DexFragglerAudioProcessorEditor() override = default;

    void paint(juce::Graphics&) override;
    void resized() override;

private:
    void timerCallback() override;
    void addControl(juce::Slider&, juce::Label&, const juce::String&, const juce::String&);

    DexFragglerAudioProcessor& processor;
    juce::Label title;
    juce::Label status;
    juce::TextButton loadButton{"Load computed table"};
    juce::Slider bank, row, column, modBank, modRow, modColumn;
    juce::Label bankLabel, rowLabel, columnLabel, modBankLabel, modRowLabel, modColumnLabel;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> bankAttachment;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> rowAttachment;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> columnAttachment;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> modBankAttachment;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> modRowAttachment;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> modColumnAttachment;
    std::unique_ptr<juce::FileChooser> chooser;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(DexFragglerAudioProcessorEditor)
};
