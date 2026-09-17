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
