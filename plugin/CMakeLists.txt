set(DEXFRAGGLER_PLUGIN_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/include")

add_library(dexfraggler_waveform_core STATIC
    src/ModulationMatrix.cpp
    src/RealtimeEngine.cpp
    src/WaveformTable.cpp
)
set_target_properties(dexfraggler_waveform_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(dexfraggler_waveform_core
    PUBLIC "${DEXFRAGGLER_PLUGIN_INCLUDE_DIR}"
    PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/../native/vendor/Source")
target_link_libraries(dexfraggler_waveform_core PUBLIC dexfraggler_dx7_engine)
target_compile_definitions(dexfraggler_waveform_core PUBLIC _USE_MATH_DEFINES NOMINMAX)

if(MSVC)
    target_compile_options(dexfraggler_waveform_core PRIVATE /W4 /wd4244 /wd4267 /wd4996)
else()
    target_compile_options(dexfraggler_waveform_core PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(DEXFRAGGLER_BUILD_TABLE_TOOL)
    add_executable(DexFragglerTableTool tools/TableBuilderMain.cpp)
    target_link_libraries(DexFragglerTableTool PRIVATE dexfraggler_waveform_core)
endif()

if(DEXFRAGGLER_BUILD_PLUGIN_TESTS)
    enable_testing()
    add_executable(DexFragglerWaveformTests tests/WaveformTableTests.cpp)
    target_link_libraries(DexFragglerWaveformTests PRIVATE dexfraggler_waveform_core)
    add_test(NAME dexfraggler_waveform_core COMMAND DexFragglerWaveformTests)
endif()

if(DEXFRAGGLER_BUILD_JUCE)
    if(NOT EXISTS "${JUCE_ROOT}/CMakeLists.txt")
        message(FATAL_ERROR "JUCE was not found at ${JUCE_ROOT}. Run scripts/build-plugin.ps1 or set -DJUCE_ROOT=...")
    endif()

    add_subdirectory("${JUCE_ROOT}" JUCE EXCLUDE_FROM_ALL)
    set(DEXFRAGGLER_JUCE_FORMATS VST3 Standalone)
    if(APPLE AND CMAKE_GENERATOR STREQUAL "Xcode")
        list(APPEND DEXFRAGGLER_JUCE_FORMATS AUv3)
    elseif(APPLE)
        message(STATUS "AUv3 is enabled only with the Xcode generator; building JUCE VST3/standalone here.")
    endif()

    juce_add_plugin(DexFraggler
        COMPANY_NAME "Echomatter"
        BUNDLE_ID "audio.echomatter.dexfraggler"
        PLUGIN_MANUFACTURER_CODE Echm
        PLUGIN_CODE DfTb
        FORMATS ${DEXFRAGGLER_JUCE_FORMATS}
        PRODUCT_NAME "DexFraggler"
        DESCRIPTION "Computed DX7 waveform-bank instrument"
        IS_SYNTH TRUE
        NEEDS_MIDI_INPUT TRUE
        NEEDS_MIDI_OUTPUT FALSE
        IS_MIDI_EFFECT FALSE
        EDITOR_WANTS_KEYBOARD_FOCUS TRUE
        VST3_CATEGORIES Instrument Synth
        COPY_PLUGIN_AFTER_BUILD FALSE
    )
    target_sources(DexFraggler PRIVATE
        juce/PluginEditor.cpp
        juce/PluginProcessor.cpp
    )
    target_link_libraries(DexFraggler PRIVATE
        dexfraggler_waveform_core
        juce::juce_audio_utils
        juce::juce_audio_processors
        PUBLIC juce::juce_recommended_config_flags
    )
    target_compile_definitions(DexFraggler PUBLIC
        JUCE_VST3_CAN_REPLACE_VST2=0
        JUCE_DISPLAY_SPLASH_SCREEN=0
        JUCE_REPORT_APP_USAGE=0
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
    )
endif()

if(DEXFRAGGLER_BUILD_LV2)
    find_path(DEXFRAGGLER_LV2_INCLUDE_DIR lv2/core/lv2.h)
    if(NOT DEXFRAGGLER_LV2_INCLUDE_DIR)
        message(FATAL_ERROR "LV2 headers were not found. Install liblv2-dev or set DEXFRAGGLER_LV2_INCLUDE_DIR.")
    endif()

    add_library(DexFragglerLV2 MODULE lv2/DexFragglerLv2.cpp)
    target_include_directories(DexFragglerLV2 PRIVATE "${DEXFRAGGLER_LV2_INCLUDE_DIR}")
    target_link_libraries(DexFragglerLV2 PRIVATE dexfraggler_waveform_core)
    set_target_properties(DexFragglerLV2 PROPERTIES PREFIX "" OUTPUT_NAME "DexFraggler")
    install(TARGETS DexFragglerLV2 LIBRARY DESTINATION "lib/lv2/DexFraggler.lv2")
    install(FILES
        "${CMAKE_CURRENT_SOURCE_DIR}/lv2/manifest.ttl"
        "${CMAKE_CURRENT_SOURCE_DIR}/lv2/dexfraggler.ttl"
        DESTINATION "lib/lv2/DexFraggler.lv2"
    )
endif()
