#include "PluginEditor.h"

DexFragglerAudioProcessorEditor::DexFragglerAudioProcessorEditor(DexFragglerAudioProcessor& input)
    : AudioProcessorEditor(&input), processor(input) {
    title.setText("DexFraggler", juce::dontSendNotification);
    title.setFont(juce::Font(22.0f, juce::Font::bold));
    title.setColour(juce::Label::textColourId, juce::Colours::white);
    addAndMakeVisible(title);

    status.setText(processor.tableStatus(), juce::dontSendNotification);
    status.setColour(juce::Label::textColourId, juce::Colours::lightgrey);
    addAndMakeVisible(status);

    addAndMakeVisible(loadButton);
    loadButton.onClick = [this] {
        chooser = std::make_unique<juce::FileChooser>("Load DexFraggler waveform table", juce::File{}, "*.dfwt");
        juce::Component::SafePointer<DexFragglerAudioProcessorEditor> safeThis(this);
        chooser->launchAsync(juce::FileBrowserComponent::openMode |
                             juce::FileBrowserComponent::canSelectFiles,
                             [safeThis](const juce::FileChooser& selected) {
                                 if (safeThis == nullptr) return;
                                 juce::String error;
                                 if (!safeThis->processor.loadTableFile(selected.getResult(), error))
                                     safeThis->status.setText("Table load failed: " + error, juce::dontSendNotification);
                             });
    };

    addControl(bank, bankLabel, "Bank", "tableBank");
    addControl(row, rowLabel, "Row", "tableRow");
    addControl(column, columnLabel, "Column", "tableColumn");
    addControl(modBank, modBankLabel, "MW → Bank", "mwBank");
    addControl(modRow, modRowLabel, "MW → Row", "mwRow");
    addControl(modColumn, modColumnLabel, "MW → Column", "mwColumn");

    bankAttachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(processor.parameters, "tableBank", bank);
    rowAttachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(processor.parameters, "tableRow", row);
    columnAttachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(processor.parameters, "tableColumn", column);
    modBankAttachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(processor.parameters, "mwBank", modBank);
    modRowAttachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(processor.parameters, "mwRow", modRow);
    modColumnAttachment = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(processor.parameters, "mwColumn", modColumn);

    setSize(620, 290);
    startTimerHz(8);
}

void DexFragglerAudioProcessorEditor::addControl(juce::Slider& slider, juce::Label& label,
                                                 const juce::String& labelText,
                                                 const juce::String&) {
    slider.setSliderStyle(juce::Slider::LinearVertical);
    slider.setTextBoxStyle(juce::Slider::TextBoxBelow, false, 72, 20);
    label.setText(labelText, juce::dontSendNotification);
    label.setJustificationType(juce::Justification::centred);
    addAndMakeVisible(slider);
    addAndMakeVisible(label);
}

void DexFragglerAudioProcessorEditor::paint(juce::Graphics& graphics) {
    graphics.fillAll(juce::Colour(0xff15171d));
    graphics.setColour(juce::Colour(0xff2f3542));
    graphics.drawRoundedRectangle(getLocalBounds().toFloat().reduced(8.0f), 8.0f, 1.0f);
    graphics.setColour(juce::Colours::lightgrey);
    graphics.setFont(12.0f);
    graphics.drawText("Three-dimensional table interpolation; modulations may cross banks, rows, columns, and phase.",
                      20, 252, getWidth() - 40, 20, juce::Justification::centred);
}

void DexFragglerAudioProcessorEditor::resized() {
    auto area = getLocalBounds().reduced(18);
    title.setBounds(area.removeFromTop(32));
    auto top = area.removeFromTop(32);
    status.setBounds(top.removeFromLeft(area.getWidth() - 150));
    loadButton.setBounds(top.removeFromRight(145));
    area.removeFromTop(12);

    const auto controlWidth = area.getWidth() / 6;
    juce::Slider* sliders[] = {&bank, &row, &column, &modBank, &modRow, &modColumn};
    juce::Label* labels[] = {&bankLabel, &rowLabel, &columnLabel, &modBankLabel, &modRowLabel, &modColumnLabel};
    for (int i = 0; i < 6; ++i) {
        auto columnArea = area.removeFromLeft(controlWidth);
        labels[i]->setBounds(columnArea.removeFromTop(22));
        sliders[i]->setBounds(columnArea.reduced(10, 0));
    }
}

void DexFragglerAudioProcessorEditor::timerCallback() {
    const auto progress = processor.buildProgress();
    status.setText(processor.tableStatus() + " — native build " + juce::String(static_cast<int>(progress * 100.0f)) + "%",
                   juce::dontSendNotification);
}
