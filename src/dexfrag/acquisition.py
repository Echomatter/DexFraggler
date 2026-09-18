"""Acquisition sources for Phase 2 dataset collection.

Each source is a generator of :class:`AcquisitionCandidate` -- a legal patch
plus lineage metadata -- that the collector (``collector.py``) consumes,
renders, classifies and stores. Sources never touch storage or the native
renderer themselves; they are pure patch-space samplers so they can be
tested in isolation and reused independently of collection.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .algorithms import all_topologies
from .mutate import mutate
from .patch import LIMITS, Operator, Patch, validate_patch

# Coarse "ratio families" used by structure-aware exploration: integer
# harmonic ratios are common/musical; non-integer coarse values plus large
# fine/detune produce inharmonic/complex spectra. Both are worth covering
# deliberately rather than leaving to chance under uniform random sampling.
_INTEGER_COARSE_VALUES = tuple(range(0, 16))  # 0 and 1..15 are common harmonic ratios
_HIGH_COARSE_VALUES = tuple(range(16, LIMITS["coarse"] + 1))

# --- coherent-ratio families used by coherent_ratio_exploration -------------
# Each family is a small set of DX7 "coarse" values (operator frequency
# ratio multipliers relative to the played note, in ratio mode). With
# fine=0 (no fractional ratio component) and detune=7 (the centered/neutral
# detune value used throughout this project, see patch.py's
# RESEARCH_PROFILE_NOTES / blank_patch), every operator built from these
# values has an *exact* integer-or-half-integer frequency ratio to the
# note's own nominal fundamental. When every operator in a patch (carriers
# and modulators alike) is drawn from one such family, the whole signal
# graph -- including any FM modulation -- stays commensurate with the
# note's fundamental period, which is what "periodic at the played note"
# (a high ``periodicity_ratio``) requires. DX7 coarse 0 denotes the ratio
# 0.5 (an octave below), which is why it appears alongside small integers
# in a couple of these families rather than only as an edge case.
_COHERENT_RATIO_FAMILIES: dict[str, tuple[int, ...]] = {
    "unison": (1,),
    "octave_stack": (1, 2, 4, 8),
    "wide_octave_stack": (1, 2, 4, 8, 16),
    "harmonic_series_low": (1, 2, 3, 4),
    "harmonic_series_full": (1, 2, 3, 4, 5, 6),
    "fifth_stack": (1, 3),
    "sub_harmonic_unison": (0, 1),  # coarse 0 == x0.5 ratio, still commensurate
}
COHERENT_RATIO_FAMILY_NAMES = tuple(_COHERENT_RATIO_FAMILIES.keys())


@dataclass(frozen=True)
class AcquisitionCandidate:
    patch: Patch
    acquisition_source: str
    parent_key: str | None = None
    parent_lineage_root_key: str | None = None


def _random_operator(rng: random.Random, op_number: int, *, level_bias: str = "uniform") -> Operator:
    coarse = rng.randint(0, LIMITS["coarse"])
    fine = rng.randint(0, LIMITS["fine"])
    detune = rng.randint(0, LIMITS["detune"])
    mode = rng.randint(0, LIMITS["mode"])
    if level_bias == "uniform":
        level = rng.randint(0, LIMITS["level"])
    elif level_bias == "favor_audible":
        # Skew away from near-zero levels, which mostly produce silent
        # patches under naive uniform sampling (a known plan pitfall).
        level = rng.randint(40, LIMITS["level"])
    else:
        level = rng.randint(0, LIMITS["level"])
    return Operator(op=op_number, coarse=coarse, fine=fine, detune=detune, mode=mode, level=level)


def random_legal_exploration(rng: random.Random, count: int):
    """Required baseline/diversity source: uniform-ish sampling over the
    entire legal parameter space, with light level-bias to avoid the
    "mostly silent" degenerate mode of naive uniform sampling landing on
    every carrier near level 0."""
    for _ in range(count):
        algorithm = rng.randint(1, 32)
        feedback = rng.randint(0, 7)
        operators = tuple(_random_operator(rng, i + 1, level_bias="favor_audible") for i in range(6))
        patch = validate_patch(Patch(algorithm=algorithm, feedback=feedback, operators=operators))
        yield AcquisitionCandidate(patch=patch, acquisition_source="random_legal")


def broad_structured_exploration(rng: random.Random, count: int):
    """Cover legal parameter space intentionally using the Phase-1
    structural report: cycle through every algorithm's carriers and give
    each carrier an audible level, rather than letting uniform chance decide
    whether a topology is ever exercised meaningfully."""
    topologies = all_topologies()
    for i in range(count):
        topology = topologies[i % len(topologies)]
        operators = []
        for op_index in range(6):
            op_number = op_index + 1
            is_carrier = op_index in topology.carriers
            level_bias = "favor_audible" if is_carrier else "uniform"
            operators.append(_random_operator(rng, op_number, level_bias=level_bias))
        feedback = rng.randint(0, 7)
        patch = validate_patch(Patch(algorithm=topology.number, feedback=feedback, operators=tuple(operators)))
        yield AcquisitionCandidate(patch=patch, acquisition_source="broad_structured")


def structure_aware_exploration(rng: random.Random, count: int):
    """Deliberately sample across algorithms, carrier/modulator patterns,
    coarse ratio families, feedback regimes and output-level patterns, so
    coverage instrumentation has real diagonal structure to report on."""
    topologies = all_topologies()
    feedback_regimes = [(0, 1), (2, 4), (5, 7)]  # none/low, mid, high
    for i in range(count):
        topology = topologies[i % len(topologies)]
        ratio_family = "integer" if (i // len(topologies)) % 2 == 0 else "high"
        coarse_values = _INTEGER_COARSE_VALUES if ratio_family == "integer" else _HIGH_COARSE_VALUES
        regime = feedback_regimes[i % len(feedback_regimes)]
        feedback = rng.randint(*regime)
        operators = []
        for op_index in range(6):
            op_number = op_index + 1
            is_carrier = op_index in topology.carriers
            coarse = rng.choice(coarse_values)
            fine = rng.randint(0, LIMITS["fine"])
            detune = rng.randint(0, LIMITS["detune"])
            mode = rng.randint(0, LIMITS["mode"])
            level = rng.randint(50, LIMITS["level"]) if is_carrier else rng.randint(0, LIMITS["level"])
            operators.append(Operator(op=op_number, coarse=coarse, fine=fine, detune=detune, mode=mode, level=level))
        patch = validate_patch(Patch(algorithm=topology.number, feedback=feedback, operators=tuple(operators)))
        yield AcquisitionCandidate(patch=patch, acquisition_source="structure_aware")


def coherent_ratio_exploration(rng: random.Random, count: int):
    """Deliberately construct harmonically coherent / stationary patches.

    Purpose (Phase 2 operator-gate revision): the other four sources sample
    each operator's coarse ratio independently, which is realistic DX7
    coverage but predominantly produces patches that are *not* periodic at
    the played note's own fundamental within one 4096-sample capture (see
    docs/plan/PHASE_2_REPORT.md's "unstable" finding). This source instead
    picks one small ``_COHERENT_RATIO_FAMILIES`` family per candidate and
    draws every operator's coarse ratio from it, with fine=0 and the
    neutral detune=7, so the whole signal graph -- carriers and modulators,
    including any FM -- stays commensurate with the note's fundamental
    period. This deliberately populates the ``valid`` (periodic) region of
    the observation corpus and gives ``local_mutation`` real parents to
    mutate around; it does not replace or shrink the other sources, which
    remain the corpus's legitimate coverage of inharmonic/unstable DX7
    behavior.

    Still varies: algorithm/topology (cycled so all 32 remain reachable),
    operator role (carriers are drawn from the low end of the family to
    anchor the audible register near the note's own pitch; modulators may
    use any family member for brighter harmonic content), feedback regime
    (mostly low/controlled, occasionally mid or high for diversity), output
    levels, and the ratio family itself (cycled across all seven families).
    """
    topologies = all_topologies()
    feedback_low = tuple(range(0, 3))
    feedback_mid = tuple(range(3, 5))
    feedback_high = tuple(range(5, 8))
    for i in range(count):
        topology = topologies[i % len(topologies)]
        family_name = COHERENT_RATIO_FAMILY_NAMES[i % len(COHERENT_RATIO_FAMILY_NAMES)]
        ratios = _COHERENT_RATIO_FAMILIES[family_name]

        # Controlled feedback regime: mostly low (favors periodicity), some
        # mid, rarely high -- feedback is the single parameter most likely
        # to destabilize an otherwise-coherent ratio family.
        roll = rng.random()
        if roll < 0.6:
            feedback = rng.choice(feedback_low)
        elif roll < 0.9:
            feedback = rng.choice(feedback_mid)
        else:
            feedback = rng.choice(feedback_high)

        operators = []
        low_ratio_count = min(2, len(ratios))
        for op_index in range(6):
            op_number = op_index + 1
            is_carrier = op_index in topology.carriers
            if is_carrier:
                coarse = ratios[rng.randrange(low_ratio_count)]
                level = rng.randint(40, LIMITS["level"])
            else:
                coarse = rng.choice(ratios)
                level = rng.randint(20, LIMITS["level"])
            operators.append(Operator(op=op_number, coarse=coarse, fine=0, detune=7, mode=0, level=level))
        patch = validate_patch(Patch(algorithm=topology.number, feedback=feedback, operators=tuple(operators)))
        yield AcquisitionCandidate(patch=patch, acquisition_source="coherent_ratio")


def local_mutation(rng: random.Random, parents: list[tuple[Patch, str, str]], count: int):
    """Mutate around existing valid observations.

    ``parents`` is a list of ``(patch, patch_key, lineage_root_key)`` tuples
    to mutate around (typically recently-collected valid observations).
    Recording the parent's key and lineage root is the caller's/collector's
    responsibility for storage; here we only pass them through as metadata.
    """
    if not parents:
        return
    for _ in range(count):
        parent_patch, parent_key, lineage_root_key = rng.choice(parents)
        child_patch, _family = mutate(parent_patch, rng)
        yield AcquisitionCandidate(
            patch=child_patch,
            acquisition_source="local_mutation",
            parent_key=parent_key,
            parent_lineage_root_key=lineage_root_key,
        )
