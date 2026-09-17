import random

from dexfrag.acquisition import broad_structured_exploration, local_mutation, random_legal_exploration, \
    structure_aware_exploration
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
