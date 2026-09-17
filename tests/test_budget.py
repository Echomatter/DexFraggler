import time

import pytest

from dexfrag.budget import Budget, BudgetCaps, BudgetExceeded


def test_budget_persists_and_resumes_across_sessions(tmp_path):
    dataset_path = tmp_path / "obs.parquet"

    budget = Budget.load(dataset_path)
    assert budget.renders_attempted == 0
    assert budget.sessions == 1
    budget.record_attempt(valid=True)
    budget.record_attempt(valid=False)
    budget.save()

    resumed = Budget.load(dataset_path)
    assert resumed.renders_attempted == 2
    assert resumed.renders_valid == 1
    assert resumed.sessions == 2  # resumed once more


def test_budget_enforces_max_renders_attempted(tmp_path):
    dataset_path = tmp_path / "obs.parquet"
    budget = Budget.load(dataset_path)
    caps = BudgetCaps(max_renders_attempted=2)

    budget.check_can_attempt_one_more(caps)
    budget.record_attempt(valid=True)
    budget.check_can_attempt_one_more(caps)
    budget.record_attempt(valid=True)
    with pytest.raises(BudgetExceeded):
        budget.check_can_attempt_one_more(caps)


def test_budget_enforces_max_elapsed_seconds(tmp_path):
    dataset_path = tmp_path / "obs.parquet"
    budget = Budget.load(dataset_path)
    caps = BudgetCaps(max_elapsed_seconds=0.01)
    time.sleep(0.02)
    with pytest.raises(BudgetExceeded):
        budget.check_can_attempt_one_more(caps)


def test_budget_enforces_max_dataset_bytes(tmp_path):
    dataset_path = tmp_path / "obs.parquet"
    dataset_path.write_bytes(b"0" * 1000)
    budget = Budget.load(dataset_path)
    budget.refresh_dataset_bytes(dataset_path)
    caps = BudgetCaps(max_dataset_bytes=500)
    with pytest.raises(BudgetExceeded):
        budget.check_can_attempt_one_more(caps)


def test_budget_ledger_file_written_next_to_dataset(tmp_path):
    dataset_path = tmp_path / "obs.parquet"
    budget = Budget.load(dataset_path)
    budget.record_attempt(valid=True)
    budget.save()
    ledger_path = tmp_path / "obs.parquet.budget.json"
    assert ledger_path.exists()
