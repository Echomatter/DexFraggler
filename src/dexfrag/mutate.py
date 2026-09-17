"""Local-mutation families for acquisition (Phase 2).

Several distinct mutation families rather than one undifferentiated random
nudge, per the Phase 2 doc. Each mutation function takes a legal ``Patch``
and a ``random.Random`` instance and returns a new legal ``Patch`` (raising
nothing -- callers are responsible for re-validating/re-rendering and for
recording the parent's ``patch_key`` as lineage).
"""
from __future__ import annotations

import random
from dataclasses import replace

from .patch import LIMITS, ALGORITHM_RANGE, FEEDBACK_RANGE, Operator, Patch, validate_patch

MUTATION_FAMILIES = (
    "single_parameter_nudge",
    "operator_block_swap",
    "algorithm_hop",
    "feedback_sweep",
)


def _clamp(value: int, maximum: int) -> int:
    return max(0, min(maximum, value))


def single_parameter_nudge(patch: Patch, rng: random.Random, *, max_step: int = 4) -> Patch:
    """Nudge exactly one searchable field of one operator by a small signed step."""
    op_index = rng.randrange(6)
    field_name = rng.choice(list(LIMITS.keys()))
    operators = list(patch.operators)
    operator = operators[op_index]
    step = rng.randint(-max_step, max_step) or 1
    current = getattr(operator, field_name)
    new_value = _clamp(current + step, LIMITS[field_name])
    operators[op_index] = replace(operator, **{field_name: new_value})
    return validate_patch(Patch(algorithm=patch.algorithm, feedback=patch.feedback, operators=tuple(operators)))


def operator_block_swap(patch: Patch, rng: random.Random) -> Patch:
    """Swap the searchable byte blocks of two distinct operators, keeping
    algorithm/feedback fixed. Explores role reassignment within a topology
    without ever inventing new parameter values."""
    i, j = rng.sample(range(6), 2)
    operators = list(patch.operators)
    op_i, op_j = operators[i], operators[j]
    operators[i] = replace(op_i, coarse=op_j.coarse, fine=op_j.fine, detune=op_j.detune,
                            mode=op_j.mode, level=op_j.level)
    operators[j] = replace(op_j, coarse=op_i.coarse, fine=op_i.fine, detune=op_i.detune,
                            mode=op_i.mode, level=op_i.level)
    return validate_patch(Patch(algorithm=patch.algorithm, feedback=patch.feedback, operators=tuple(operators)))


def algorithm_hop(patch: Patch, rng: random.Random) -> Patch:
    """Move the same operator parameters to a different algorithm (topology),
    exploring how one parameter set behaves under a different routing."""
    candidates = [a for a in range(ALGORITHM_RANGE[0], ALGORITHM_RANGE[1] + 1) if a != patch.algorithm]
    new_algorithm = rng.choice(candidates)
    return validate_patch(Patch(algorithm=new_algorithm, feedback=patch.feedback, operators=patch.operators))


def feedback_sweep(patch: Patch, rng: random.Random) -> Patch:
    """Move feedback to a different legal value, keeping everything else fixed."""
    candidates = [f for f in range(FEEDBACK_RANGE[0], FEEDBACK_RANGE[1] + 1) if f != patch.feedback]
    new_feedback = rng.choice(candidates)
    return validate_patch(Patch(algorithm=patch.algorithm, feedback=new_feedback, operators=patch.operators))


_FAMILY_FUNCTIONS = {
    "single_parameter_nudge": single_parameter_nudge,
    "operator_block_swap": operator_block_swap,
    "algorithm_hop": algorithm_hop,
    "feedback_sweep": feedback_sweep,
}


def mutate(patch: Patch, rng: random.Random, family: str | None = None) -> tuple[Patch, str]:
    """Apply one named mutation family (or a randomly chosen one) and return
    ``(mutated_patch, family_name)``."""
    family = family or rng.choice(MUTATION_FAMILIES)
    if family not in _FAMILY_FUNCTIONS:
        raise ValueError(f"Unknown mutation family: {family!r}. Known: {MUTATION_FAMILIES}")
    return _FAMILY_FUNCTIONS[family](patch, rng), family
