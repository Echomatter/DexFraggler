cmake_minimum_required(VERSION 3.22)

project(DexFraggler VERSION 0.2.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

option(DEXFRAGGLER_BUILD_JUCE "Build the JUCE VST3/standalone target and AUv3 on Apple" OFF)
option(DEXFRAGGLER_BUILD_LV2 "Build the optional LV2 adapter" OFF)
option(DEXFRAGGLER_BUILD_PLUGIN_TESTS "Build native waveform-table and realtime tests" ON)
option(DEXFRAGGLER_BUILD_TABLE_TOOL "Build the offline native table builder" ON)
set(JUCE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/plugin/third_party/JUCE" CACHE PATH "JUCE checkout (7.0.12 or newer)")

add_subdirectory(native)
add_subdirectory(plugin)
