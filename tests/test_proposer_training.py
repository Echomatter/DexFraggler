import math
from pathlib import Path

import pytest
import torch

from dexfrag.proposer_model import ProposerModel
from dexfrag.proposer_training import (
    ProposerTrainConfig,
    evaluate,
    load_checkpoint,
    make_loaders,
    resolve_device,
    save_checkpoint,
    smoke_train,
    train,
)
from test_proposer_data import _corpus


def _config(corpus, tmp_path, **overrides):
    values = {
        "corpus": corpus, "checkpoint_dir": tmp_path / "checkpoints", "device": "cpu",
        "epochs": 1, "max_rows": 2, "batch_size": 1, "learning_rate": 1e-3,
    }
    values.update(overrides)
    return ProposerTrainConfig(**values)


def test_config_and_loader_bounds(tmp_path):
    corpus = _corpus(tmp_path / "native.parquet")
    config = _config(corpus, tmp_path)
    train_loader, validation_loader = make_loaders(config, train_shuffle=False)
    assert len(train_loader.dataset) == 1
    assert len(validation_loader.dataset) == 1
    with pytest.raises(ValueError):
        ProposerTrainConfig(corpus, tmp_path / "bad", max_rows=1)
    with pytest.raises(ValueError):
        ProposerTrainConfig(corpus, tmp_path / "bad", candidate_count=257)
    with pytest.raises(ValueError):
        ProposerTrainConfig(corpus, tmp_path / "bad", max_seconds=0)


def test_training_checkpoint_resume_and_evaluate(tmp_path):
    corpus = _corpus(tmp_path / "native.parquet")
    config = _config(corpus, tmp_path, epochs=1)
    model = ProposerModel(algorithm_dim=4, hidden_dim=16, harmonic_bands=8, conv_channels=4)
    summary = train(config, model=model)
    assert summary["epochs_run"] == 1
    assert math.isfinite(summary["best_val"])
    assert summary["parameter_count"] > 0
    assert summary["smoke_candidate_metrics"]["legal_rate"] == 1.0
    assert Path(summary["best_checkpoint"]).exists()
    _, validation_loader = make_loaders(config, train_shuffle=False)
    metrics = evaluate(ProposerModel(algorithm_dim=4, hidden_dim=16, harmonic_bands=8, conv_channels=4), validation_loader, resolve_device("cpu"))
    assert math.isfinite(metrics["loss"])
    resumed_config = _config(corpus, tmp_path, epochs=2)
    resumed = train(resumed_config)
    assert resumed["completed_epochs"] >= 1


def test_checkpoint_roundtrip_and_atomic_save(tmp_path):
    model = ProposerModel(algorithm_dim=4, hidden_dim=16, harmonic_bands=8, conv_channels=4)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    path = save_checkpoint(tmp_path / "last.pt", model, optimizer, epoch=2, completed_epochs=3,
                           global_step=7, best_val=0.5)
    assert path.exists()
    assert not list(tmp_path.glob("*.tmp"))
    revived = ProposerModel(algorithm_dim=4, hidden_dim=16, harmonic_bands=8, conv_channels=4)
    state = load_checkpoint(path, revived)
    assert state["global_step"] == 7 and state["completed_epochs"] == 3
    assert state["model_config"] == model.architecture_config()
    assert all(torch.equal(left, right) for left, right in zip(model.parameters(), revived.parameters()))


def test_smoke_train_is_finite_and_resumable():
    result = smoke_train(steps=2, batch_size=2)
    assert result["ok"] and result["finite"] and result["params_updated"]
    assert result["restored_step"] == 2
    assert result["candidate_metrics"]["legal_rate"] == 1.0


def test_max_steps_is_bounded(tmp_path):
    corpus = _corpus(tmp_path / "native.parquet")
    config = _config(corpus, tmp_path, epochs=4, max_steps=1)
    result = train(config, model=ProposerModel(algorithm_dim=4, hidden_dim=16, harmonic_bands=8, conv_channels=4))
    assert result["global_step"] == 1
    assert result["epochs_run"] <= 1


def test_progress_callback_reports_counts(tmp_path):
    corpus = _corpus(tmp_path / "native.parquet")
    config = _config(corpus, tmp_path, epochs=3)
    events = []
    result = train(config, model=ProposerModel(algorithm_dim=4, hidden_dim=16, harmonic_bands=8, conv_channels=4),
                   progress_callback=events.append)
    kinds = [event["event"] for event in events]
    assert kinds[0] == "ready"
    assert kinds[-1] == "finished"
    assert kinds.count("epoch_end") == result["epochs_run"] == 3
    steps = [event for event in events if event["event"] == "step"]
    assert steps
    assert {event["epoch"] for event in steps} == {1, 2, 3}
    for event in steps[:2]:
        assert event["batch"] <= event["batches"]
        assert event["samples_seen"] <= event["train_samples"]
        assert math.isfinite(event["loss"])
    assert events[-1]["result"]["global_step"] == result["global_step"]


def test_progress_callbacks_must_be_callable(tmp_path):
    corpus = _corpus(tmp_path / "native.parquet")
    config = _config(corpus, tmp_path)
    with pytest.raises(ValueError, match="progress_callback"):
        train(config, progress_callback="not-a-callback")
    with pytest.raises(ValueError, match="stop_requested"):
        train(config, stop_requested="not-a-callback")


def test_stop_request_halts_and_checkpoints(tmp_path):
    corpus = _corpus(tmp_path / "native.parquet")
    config = _config(corpus, tmp_path, epochs=20, max_rows=16, batch_size=4)
    seen = {"steps": 0}

    def stop_after_two():
        return seen["steps"] >= 2

    def watch(event):
        if event["event"] == "step":
            seen["steps"] += 1

    result = train(config, model=ProposerModel(algorithm_dim=4, hidden_dim=16, harmonic_bands=8, conv_channels=4),
                   progress_callback=watch, stop_requested=stop_after_two)
    assert result["stopped"] is True
    assert result["global_step"] <= 3
    assert config.last_path.exists()
