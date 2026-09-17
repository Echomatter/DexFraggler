"""Dataset split assignment (Phase 2 design decision, pinned down here).

Design decision (see docs/plan/ERRATA_AND_REVISIONS.md item 4a): splits must
be (a) deterministic given only the patch's identity/lineage, so they never
change as the dataset grows or is rewritten, and (b) resistant to trivial
leakage from local-mutation acquisition, where a mutated child can be nearly
sonically identical to its parent.

The resolution: every observation carries a **split key**. For an
independently-sampled patch (broad/random/structure-aware acquisition) the
split key is its own ``patch_key``. For a mutation-derived patch, the split
key is its **lineage root's** ``patch_key`` -- the original ancestor at the
head of its mutation chain, not its immediate parent. This guarantees an
entire mutation family (parent + every descendant, however deep) is assigned
to exactly one split, so a train-set parent can never have a near-identical
child leak into the validation/test set, and vice versa.

Split assignment itself is a stable hash of the split key mapped onto
``[0, 1)`` and bucketed by cumulative ratio -- no shuffling, no dependence on
row order or collection time, no external state. Appending new data never
reassigns an existing key.
"""
from __future__ import annotations

import hashlib

DEFAULT_RATIOS = {"train": 0.90, "validation": 0.05, "test": 0.05}
SPLIT_SCHEME_VERSION = "dexfrag-split-v1"


def _unit_interval(split_key: str) -> float:
    """Stable hash of split_key mapped onto [0, 1)."""
    digest = hashlib.sha256(split_key.encode("utf-8")).digest()
    as_int = int.from_bytes(digest[:8], byteorder="big")
    return as_int / 2.0 ** 64


def lineage_root_key(patch_key: str, parent_lineage_root_key: str | None) -> str:
    """The split key a new observation should carry.

    ``parent_lineage_root_key`` is the *parent's own* lineage_root_key value
    (None if the parent is itself an independent, non-mutated observation, in
    which case the parent's own patch_key becomes the root). Independent
    (non-mutated) observations pass ``parent_lineage_root_key=None`` and get
    their own ``patch_key`` back, i.e. they are the root of their own family.
    """
    return parent_lineage_root_key or patch_key


def assign_split(split_key: str, ratios: dict[str, float] | None = None) -> str:
    """Deterministically assign a split name for a given split key.

    ``ratios`` must be positive and sum to 1.0 (within floating tolerance).
    The mapping from ``split_key`` to bucket is stable across runs/appends;
    the smallest ("test") and next-smallest ("validation") splits claim the
    low end of the hash space first, so growing "train" (or adding new
    acquisition sources) never reshuffles an existing test/validation key.
    """
    ratios = ratios or DEFAULT_RATIOS
    total = sum(ratios.values())
    if total <= 0 or abs(total - 1.0) > 1e-6:
        raise ValueError(f"split ratios must sum to 1.0, got {total}.")
    ordering = [name for name in ("test", "validation", "train") if name in ratios]
    ordering += [name for name in ratios if name not in ordering]
    point = _unit_interval(split_key)
    cumulative = 0.0
    for name in ordering:
        cumulative += ratios[name]
        if point < cumulative:
            return name
    return ordering[-1]


def benchmark_holdout(split_key: str, holdout_fraction: float = 0.02) -> bool:
    """A stricter, independent structural-family holdout grouping.

    Returns True if this split_key's entire lineage family should be held out
    of *all* training use (not just test-scored), for a benchmark that proves
    generalization to families never seen during training or validation.
    Uses a different hash salt than ``assign_split`` so the two groupings are
    independent rather than nested subsets of each other.
    """
    digest = hashlib.sha256(("benchmark-holdout:" + split_key).encode("utf-8")).digest()
    as_int = int.from_bytes(digest[:8], byteorder="big")
    return (as_int / 2.0 ** 64) < holdout_fraction
