#include "dexfraggler/WaveformTable.h"

#include <algorithm>
#include <cmath>

namespace dexfraggler {
namespace {

float sourceValue(ModulationSource source, const ModulationState& state) noexcept {
    switch (source) {
    case ModulationSource::pitchBend: return std::clamp(state.pitchBend, -1.0f, 1.0f);
    case ModulationSource::modWheel: return std::clamp(state.modWheel, 0.0f, 1.0f);
    case ModulationSource::aftertouch: return std::clamp(state.aftertouch, 0.0f, 1.0f);
    case ModulationSource::expression: return std::clamp(state.expression, 0.0f, 1.0f);
    case ModulationSource::velocity: return std::clamp(state.velocity, 0.0f, 1.0f);
    }
    return 0.0f;
}

float curveValue(float value, ModulationCurve curve) noexcept {
    if (curve == ModulationCurve::linear) return value;
    const auto sign = value < 0.0f ? -1.0f : 1.0f;
    const auto magnitude = std::abs(value);
    return sign * magnitude * magnitude * (3.0f - 2.0f * magnitude);
}

float wrapPhase(float value) noexcept {
    value -= std::floor(value);
    return value < 0.0f ? value + 1.0f : value;
}

} // namespace

void ModulationMatrix::clear() noexcept {
    routeCount = 0;
}

bool ModulationMatrix::addRoute(ModulationRoute route) noexcept {
    if (routeCount >= maxRoutes || !std::isfinite(route.amount)) return false;
    route.amount = std::clamp(route.amount, -1000.0f, 1000.0f);
    routes[routeCount++] = route;
    return true;
}

bool ModulationMatrix::setAmount(ModulationSource source, TableAxis axis, float amount) noexcept {
    for (std::size_t i = 0; i < routeCount; ++i) {
        if (routes[i].source == source && routes[i].axis == axis) {
            routes[i].amount = std::isfinite(amount) ? std::clamp(amount, -1000.0f, 1000.0f) : 0.0f;
            return true;
        }
    }
    return addRoute({source, axis, amount, ModulationCurve::linear});
}

TableAddress ModulationMatrix::apply(TableAddress base, const ModulationState& state,
                                     float maxBank, float maxRow, float maxColumn) const noexcept {
    base.bank = std::clamp(std::isfinite(base.bank) ? base.bank : 0.0f, 0.0f, std::max(0.0f, maxBank));
    base.row = std::clamp(std::isfinite(base.row) ? base.row : 0.0f, 0.0f, std::max(0.0f, maxRow));
    base.column = std::clamp(std::isfinite(base.column) ? base.column : 0.0f, 0.0f, std::max(0.0f, maxColumn));
    base.phase = wrapPhase(std::isfinite(base.phase) ? base.phase : 0.0f);

    for (std::size_t i = 0; i < routeCount; ++i) {
        const auto& route = routes[i];
        const auto delta = curveValue(sourceValue(route.source, state), route.curve) * route.amount;
        switch (route.axis) {
        case TableAxis::bank: base.bank += delta; break;
        case TableAxis::row: base.row += delta; break;
        case TableAxis::column: base.column += delta; break;
        case TableAxis::phase: base.phase += delta; break;
        }
    }

    base.bank = std::clamp(base.bank, 0.0f, std::max(0.0f, maxBank));
    base.row = std::clamp(base.row, 0.0f, std::max(0.0f, maxRow));
    base.column = std::clamp(base.column, 0.0f, std::max(0.0f, maxColumn));
    base.phase = wrapPhase(base.phase);
    return base;
}

} // namespace dexfraggler
