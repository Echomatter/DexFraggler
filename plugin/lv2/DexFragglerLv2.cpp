#include "dexfraggler/RealtimeEngine.h"

#include <lv2/atom/atom.h>
#include <lv2/atom/util.h>
#include <lv2/core/lv2.h>
#include <lv2/midi/midi.h>
#include <lv2/urid/urid.h>

#include <algorithm>
#include <cstdint>
#include <memory>
#include <string>

namespace {

constexpr char pluginUri[] = "https://echomatter.audio/plugins/dexfraggler";
enum PortIndex { audioOutput = 0, midiInput = 1, tableBank = 2, tableRow = 3, tableColumn = 4 };

struct Instance {
    dexfraggler::RealtimeEngine engine;
    std::shared_ptr<dexfraggler::WaveformTable> table;
    const LV2_Atom_Sequence* midi = nullptr;
    float* output = nullptr;
    const float* bank = nullptr;
    const float* row = nullptr;
    const float* column = nullptr;
    LV2_URID midiEvent = 0;
};

void handleMidi(Instance& instance, const std::uint8_t* message, std::uint32_t size) noexcept {
    if (message == nullptr || size == 0) return;
    const auto status = static_cast<std::uint8_t>(message[0] & 0xf0u);
    if (status == 0x90u && size >= 3 && message[2] != 0) {
        instance.engine.noteOn(message[1], message[2]);
    } else if ((status == 0x80u && size >= 3) || (status == 0x90u && size >= 3)) {
        instance.engine.noteOff(message[1]);
    } else if (status == 0xe0u && size >= 3) {
        const auto value = static_cast<int>(message[1]) | (static_cast<int>(message[2]) << 7);
        instance.engine.setPitchBend((static_cast<float>(value) - 8192.0f) / 8192.0f * 2.0f);
    } else if (status == 0xd0u && size >= 2) {
        instance.engine.setAftertouch(static_cast<float>(message[1]) / 127.0f);
    } else if (status == 0xb0u && size >= 3) {
        const auto value = static_cast<float>(message[2]) / 127.0f;
        if (message[1] == 1) instance.engine.setModWheel(value);
        else if (message[1] == 11) instance.engine.setExpression(value);
        else if (message[1] == 120 || message[1] == 123) instance.engine.allNotesOff();
    }
}

LV2_Handle instantiate(const LV2_Descriptor*, double rate, const char*, const LV2_Feature* const* features) {
    auto* instance = new Instance;
    instance->engine.prepare(rate);
    instance->table = dexfraggler::WaveformTable::makeFallback(4);
    instance->engine.setTable(instance->table.get());
    if (features != nullptr) {
        for (const auto* const* feature = features; *feature != nullptr; ++feature) {
            const auto* current = *feature;
            if (current->URI != nullptr && std::string(current->URI) == LV2_URID__map) {
                const auto* map = static_cast<const LV2_URID_Map*>(current->data);
                if (map != nullptr && map->map != nullptr)
                    instance->midiEvent = map->map(map->handle, LV2_MIDI__MidiEvent);
            }
        }
    }
    return instance;
}

void connectPort(LV2_Handle handle, std::uint32_t port, void* data) {
    auto& instance = *static_cast<Instance*>(handle);
    switch (port) {
    case audioOutput: instance.output = static_cast<float*>(data); break;
    case midiInput: instance.midi = static_cast<const LV2_Atom_Sequence*>(data); break;
    case tableBank: instance.bank = static_cast<const float*>(data); break;
    case tableRow: instance.row = static_cast<const float*>(data); break;
    case tableColumn: instance.column = static_cast<const float*>(data); break;
    default: break;
    }
}

void activate(LV2_Handle handle) {
    static_cast<Instance*>(handle)->engine.reset();
}

void run(LV2_Handle handle, std::uint32_t frames) {
    auto& instance = *static_cast<Instance*>(handle);
    if (instance.output == nullptr) return;
    instance.engine.setAddress({
        instance.bank != nullptr ? *instance.bank : 0.0f,
        instance.row != nullptr ? *instance.row : 0.0f,
        instance.column != nullptr ? *instance.column : 0.0f,
        0.0f});
    instance.engine.setTable(instance.table.get());

    std::uint32_t cursor = 0;
    if (instance.midi != nullptr && instance.midiEvent != 0) {
        LV2_ATOM_SEQUENCE_FOREACH(instance.midi, event) {
            if (event->body.type != instance.midiEvent) continue;
            const auto eventFrame = static_cast<std::uint32_t>(std::clamp<std::int64_t>(
                event->time.frames, 0, static_cast<std::int64_t>(frames)));
            if (eventFrame > cursor) {
                instance.engine.render(instance.output + cursor, nullptr,
                                       static_cast<int>(eventFrame - cursor));
                cursor = eventFrame;
            }
            handleMidi(instance,
                       static_cast<const std::uint8_t*>(LV2_ATOM_BODY_CONST(event)),
                       event->body.size);
        }
    }
    if (cursor < frames)
        instance.engine.render(instance.output + cursor, nullptr, static_cast<int>(frames - cursor));
}

void deactivate(LV2_Handle) {}

void cleanup(LV2_Handle handle) {
    delete static_cast<Instance*>(handle);
}

const void* extensionData(const char*) { return nullptr; }

const LV2_Descriptor descriptor{
    pluginUri, instantiate, connectPort, activate, run, deactivate, cleanup, extensionData};

} // namespace

extern "C" LV2_SYMBOL_EXPORT const LV2_Descriptor* lv2_descriptor(std::uint32_t index) {
    return index == 0 ? &descriptor : nullptr;
}
