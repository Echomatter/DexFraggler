import json

import pytest

from dexfrag.budget import Budget, BudgetCaps
from dexfrag.collector import collect
from dexfrag.native import DEFAULT_EXECUTABLE
from dexfrag.storage import read_observations

pytestmark = pytest.mark.skipif(
    not DEFAULT_EXECUTABLE.is_file(),
    reason="native/bin/DexfragglerReference.exe is required for collector tests",
)

TINY_PLAN = {"broad_structured": 3, "random_legal": 3, "structure_aware": 2, "local_mutation": 0}


def test_collect_is_bounded_by_max_renders(tmp_path):
    dataset_path = tmp_path / "obs.parquet"
    caps_summary = collect(
        dataset_path, plan=TINY_PLAN, seed=1,
        caps=BudgetCaps(max_renders_attempted=4),
    )
    assert caps_summary.rendered + caps_summary.render_failures <= 4
    assert caps_summary.stopped_reason is not None


def test_collect_writes_observations_and_is_resumable(tmp_path):
    dataset_path = tmp_path / "obs.parquet"
    first = collect(dataset_path, plan=TINY_PLAN, seed=2)
    assert first.rendered > 0
    table = read_observations(dataset_path)
    assert table.num_rows == first.rendered

    # Resuming with the same seed/plan must not duplicate any existing patch.
    second = collect(dataset_path, plan=TINY_PLAN, seed=2)
    table_after = read_observations(dataset_path)
    assert table_after.num_rows == table.num_rows  # identical plan+seed => all duplicates
    assert second.duplicates_skipped == second.requested
    assert second.rendered == 0


def test_collect_assigns_splits_and_lineage_deterministically(tmp_path):
    dataset_path = tmp_path / "obs.parquet"
    collect(dataset_path, plan=TINY_PLAN, seed=3)
    table = read_observations(dataset_path)
    assert table.num_rows > 0
    splits = set(table.column("split").to_pylist())
    assert splits <= {"train", "validation", "test"}
    lineage_roots = table.column("lineage_root_key").to_pylist()
    keys = table.column("key").to_pylist()
    parent_keys = table.column("parent_key").to_pylist()
    for key, root, parent in zip(keys, lineage_roots, parent_keys):
        if parent is None:
            assert root == key  # independent acquisition: root is itself


def test_collect_records_validity_classes(tmp_path):
    dataset_path = tmp_path / "obs.parquet"
    summary = collect(dataset_path, plan=TINY_PLAN, seed=4)
    table = read_observations(dataset_path)
    valid_classes = set(table.column("validity_class").to_pylist())
    assert valid_classes <= {"valid", "silent", "near_silent", "clipped", "unstable"}
    assert sum(summary.by_validity.values()) == summary.rendered


def test_collect_budget_ledger_persists_across_calls(tmp_path):
    dataset_path = tmp_path / "obs.parquet"
    collect(dataset_path, plan=TINY_PLAN, seed=5)
    budget = Budget.load(dataset_path)
    assert budget.renders_attempted > 0
    assert budget.sessions >= 2  # one from collect(), one from this explicit load


def test_collect_local_mutation_uses_prior_valid_observations(tmp_path):
    dataset_path = tmp_path / "obs.parquet"
    collect(dataset_path, plan={"broad_structured": 4, "random_legal": 0, "structure_aware": 0, "local_mutation": 0}, seed=6)
    before = read_observations(dataset_path).num_rows
    summary = collect(
        dataset_path,
        plan={"broad_structured": 0, "random_legal": 0, "structure_aware": 0, "local_mutation": 4},
        seed=6,
    )
    table = read_observations(dataset_path)
    assert table.num_rows >= before  # mutation children may be added
    mutation_rows = [p for p in table.column("acquisition_source").to_pylist() if p == "local_mutation"]
    if summary.rendered:
        assert len(mutation_rows) > 0


def test_collect_writes_failures_log_on_error(tmp_path, monkeypatch):
    dataset_path = tmp_path / "obs.parquet"
    import dexfrag.collector as collector_module

    class ExplodingRenderer:
        def __init__(self, *a, **k):
            pass

        def render(self, patch):
            raise collector_module.NativeRendererError("synthetic failure")

        def close(self):
            pass

    monkeypatch.setattr(collector_module, "NativeRenderer", ExplodingRenderer)
    summary = collect(dataset_path, plan={"broad_structured": 2, "random_legal": 0, "structure_aware": 0, "local_mutation": 0}, seed=7)
    assert summary.render_failures == 2
    failures_path = dataset_path.with_suffix(dataset_path.suffix + ".failures.jsonl")
    assert failures_path.exists()
    lines = failures_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        payload = json.loads(line)
        assert payload["error"] == "synthetic failure"
