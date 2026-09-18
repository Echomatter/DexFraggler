import random

import pytest

from dexfrag.acquisition import COHERENT_RATIO_FAMILY_NAMES, broad_structured_exploration, \
    coherent_ratio_exploration, local_mutation, random_legal_exploration, structure_aware_exploration
from dexfrag.native import DEFAULT_EXECUTABLE, NativeRenderer
from dexfrag.features import canonical_frame
from dexfrag.patch import patch_key, validate_patch


def test_random_legal_exploration_yields_legal_distinct_patches():
    rng = random.Random(0)
    candidates = list(random_legal_exploration(rng, 20))
    assert len(candidates) == 20
    keys = {patch_key(c.patch) for c in candidates}
    assert len(keys) > 1  # overwhelmingly likely to be distinct
    assert all(c.acquisition_source == "random_legal" for c in candidates)
    assert all(c.parent_key is None for c in candidates)


def test_broad_structured_exploration_covers_every_algorithm_at_least_once():
    rng = random.Random(1)
    candidates = list(broad_structured_exploration(rng, 32))
    algorithms = {c.patch.algorithm for c in candidates}
    assert algorithms == set(range(1, 33))


def test_broad_structured_exploration_biases_carrier_levels_audible():
    from dexfrag.algorithms import topology_for
    rng = random.Random(2)
    candidates = list(broad_structured_exploration(rng, 32))
    for candidate in candidates:
        topology = topology_for(candidate.patch.algorithm)
        for op_index in topology.carriers:
            level = candidate.patch.operators[op_index].level
            assert level >= 40  # favor_audible lower bound


def test_structure_aware_exploration_sweeps_feedback_regimes():
    rng = random.Random(3)
    candidates = list(structure_aware_exploration(rng, 9))
    feedbacks = [c.patch.feedback for c in candidates]
    assert any(f <= 1 for f in feedbacks)
    assert any(2 <= f <= 4 for f in feedbacks)
    assert any(f >= 5 for f in feedbacks)


def test_local_mutation_records_parent_lineage():
    parent_patch = validate_patch({
        "algorithm": 10, "feedback": 2,
        "operators": [{"op": i + 1, "coarse": 1, "fine": 0, "detune": 7, "mode": 0, "level": 80 if i == 0 else 10}
                       for i in range(6)],
    })
    parent_key = patch_key(parent_patch)
    rng = random.Random(4)
    candidates = list(local_mutation(rng, [(parent_patch, parent_key, parent_key)], 10))
    assert len(candidates) == 10
    for candidate in candidates:
        assert candidate.acquisition_source == "local_mutation"
        assert candidate.parent_key == parent_key
        assert candidate.parent_lineage_root_key == parent_key


def test_local_mutation_with_no_parents_yields_nothing():
    rng = random.Random(5)
    assert list(local_mutation(rng, [], 10)) == []


def test_coherent_ratio_exploration_covers_every_algorithm_at_least_once():
    rng = random.Random(6)
    candidates = list(coherent_ratio_exploration(rng, 32))
    algorithms = {c.patch.algorithm for c in candidates}
    assert algorithms == set(range(1, 33))
    assert all(c.acquisition_source == "coherent_ratio" for c in candidates)


def test_coherent_ratio_exploration_uses_only_exact_integer_ratio_operators():
    """Every operator must have fine=0, detune=7 (neutral) and mode=0 (ratio
    mode) so its frequency is an exact integer/half-integer multiple of the
    played note -- the whole point of this acquisition source."""
    rng = random.Random(7)
    candidates = list(coherent_ratio_exploration(rng, 50))
    for candidate in candidates:
        for operator in candidate.patch.operators:
            assert operator.fine == 0
            assert operator.detune == 7
            assert operator.mode == 0
            assert operator.coarse <= 16  # every family tops out at 16


def test_coherent_ratio_exploration_cycles_through_every_ratio_family():
    rng = random.Random(8)
    candidates = list(coherent_ratio_exploration(rng, len(COHERENT_RATIO_FAMILY_NAMES) * 3))
    # Distinguish families by the set of distinct coarse values actually used
    # per candidate (a reasonable proxy since family membership isn't stored
    # directly on the patch).
    coarse_sets = {tuple(sorted({op.coarse for op in c.patch.operators})) for c in candidates}
    assert len(coarse_sets) >= 4  # meaningfully diverse across the 7 families


def test_coherent_ratio_exploration_varies_feedback_and_levels():
    rng = random.Random(9)
    candidates = list(coherent_ratio_exploration(rng, 60))
    feedbacks = {c.patch.feedback for c in candidates}
    assert len(feedbacks) > 1
    levels = {op.level for c in candidates for op in c.patch.operators}
    assert len(levels) > 5


@pytest.mark.skipif(not DEFAULT_EXECUTABLE.is_file(), reason="native renderer required to verify real periodicity")
def test_coherent_ratio_exploration_renders_with_high_periodicity():
    """The actual proof: rendered coherent_ratio patches should measure a
    high periodicity_ratio far more often than a naive independently-random
    patch does (see docs/plan/PHASE_2_REPORT.md's original finding)."""
    rng = random.Random(10)
    candidates = list(coherent_ratio_exploration(rng, 12))
    renderer = NativeRenderer()
    try:
        ratios = []
        for candidate in candidates:
            capture = renderer.render(candidate.patch)
            frames = [canonical_frame(w, n) for w, n in zip(capture.waveforms, capture.notes)]
            ratios.append(min(f.periodicity_ratio for f in frames))
    finally:
        renderer.close()
    high_periodicity_count = sum(1 for r in ratios if r >= 0.5)
    assert high_periodicity_count >= len(candidates) // 2
