import random

from dexfrag.mutate import MUTATION_FAMILIES, algorithm_hop, feedback_sweep, mutate, operator_block_swap, \
    single_parameter_nudge
from dexfrag.patch import patch_key, validate_patch


def _sample_patch():
    return validate_patch({
        "algorithm": 5,
        "feedback": 3,
        "operators": [
            {"op": i + 1, "coarse": 1, "fine": (i * 7) % 100, "detune": 7, "mode": 0, "level": 80 if i == 0 else 20}
            for i in range(6)
        ],
    })


def test_single_parameter_nudge_changes_exactly_one_field():
    patch = _sample_patch()
    rng = random.Random(42)
    mutated = single_parameter_nudge(patch, rng)
    diffs = []
    for before, after in zip(patch.operators, mutated.operators):
        for field_name in ("coarse", "fine", "detune", "mode", "level"):
            if getattr(before, field_name) != getattr(after, field_name):
                diffs.append((before.op, field_name))
    assert mutated.algorithm == patch.algorithm
    assert mutated.feedback == patch.feedback
    assert len(diffs) == 1


def test_operator_block_swap_swaps_two_operators_only():
    patch = _sample_patch()
    rng = random.Random(1)
    mutated = operator_block_swap(patch, rng)
    changed_ops = [
        before.op for before, after in zip(patch.operators, mutated.operators)
        if before.to_dict() != after.to_dict()
    ]
    assert len(changed_ops) == 2


def test_algorithm_hop_only_changes_algorithm():
    patch = _sample_patch()
    rng = random.Random(2)
    mutated = algorithm_hop(patch, rng)
    assert mutated.algorithm != patch.algorithm
    assert mutated.feedback == patch.feedback
    assert mutated.operators == patch.operators


def test_feedback_sweep_only_changes_feedback():
    patch = _sample_patch()
    rng = random.Random(3)
    mutated = feedback_sweep(patch, rng)
    assert mutated.feedback != patch.feedback
    assert mutated.algorithm == patch.algorithm
    assert mutated.operators == patch.operators


def test_mutate_dispatches_named_family_and_produces_distinct_legal_patch():
    patch = _sample_patch()
    rng = random.Random(7)
    for family in MUTATION_FAMILIES:
        mutated, returned_family = mutate(patch, rng, family=family)
        assert returned_family == family
        assert patch_key(mutated) != patch_key(patch) or family in ("single_parameter_nudge",)
