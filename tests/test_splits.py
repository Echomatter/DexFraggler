import pytest

from dexfrag.splits import assign_split, benchmark_holdout, lineage_root_key


def test_lineage_root_key_independent_vs_mutated():
    assert lineage_root_key("abc", None) == "abc"
    assert lineage_root_key("child-key", "root-key") == "root-key"


def test_assign_split_is_deterministic():
    key = "deadbeef" * 4
    first = assign_split(key)
    second = assign_split(key)
    assert first == second
    assert first in {"train", "validation", "test"}


def test_assign_split_respects_ratios_at_scale():
    counts = {"train": 0, "validation": 0, "test": 0}
    for i in range(4000):
        split = assign_split(f"patch-{i}")
        counts[split] += 1
    total = sum(counts.values())
    assert counts["train"] / total == pytest.approx(0.90, abs=0.03)
    assert counts["validation"] / total == pytest.approx(0.05, abs=0.02)
    assert counts["test"] / total == pytest.approx(0.05, abs=0.02)


def test_assign_split_rejects_bad_ratios():
    with pytest.raises(ValueError):
        assign_split("key", ratios={"train": 0.5, "validation": 0.2})


def test_mutation_family_shares_one_split_with_root():
    # A whole lineage family (root + descendants) must resolve to one split,
    # since every descendant's split key is the same lineage root key.
    root_key = "root-patch-key-0001"
    child_split_key = lineage_root_key("child-key-a", root_key)
    grandchild_split_key = lineage_root_key("child-key-b", root_key)
    assert child_split_key == grandchild_split_key == root_key
    assert assign_split(child_split_key) == assign_split(grandchild_split_key) == assign_split(root_key)


def test_benchmark_holdout_independent_of_split_assignment():
    # Not a strict subset check -- just confirm it's a stable, deterministic
    # boolean function of the split key, using a different hash space.
    key = "some-lineage-root"
    assert benchmark_holdout(key) == benchmark_holdout(key)
    flagged = sum(1 for i in range(2000) if benchmark_holdout(f"k{i}"))
    assert 0 < flagged < 200  # roughly 2% of 2000, generously bounded
