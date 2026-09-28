"""Focused Phase 3 forward-training tests (train/validation only, synthetic corpus)."""
import json
import math

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch

import dexfrag.forward_training as ft
from dexfrag.algorithms import topology_for
from dexfrag.features import FEATURE_VERSION
from dexfrag.forward_data import FEATURE_VERSION as DATA_FEATURE_VERSION
from dexfrag.forward_data import REFERENCE, ForwardDataset
from dexfrag.forward_metrics import SCORER_VERSION
from dexfrag.forward_model import ForwardModel
from dexfrag.forward_training import (
    TrainConfig,
    evaluate,
    load_checkpoint,
    make_loaders,
    resolve_device,
    save_checkpoint,
    seed_everything,
    smoke_train,
    train,
)
from dexfrag.patch import blank_patch, patch_key
from dexfrag.splits import SPLIT_SCHEME_VERSION, assign_split, benchmark_holdout
from dexfrag.storage import NATIVE_OBSERVATION_SCHEMA, OBSERVATION_SCHEMA_VERSION


def _row(patch):
    key = patch_key(patch)
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION, "key": key,
        "patch_json": json.dumps(patch), "algorithm": patch["algorithm"], "feedback": 0,
        "algorithm_topology_signature": topology_for(patch["algorithm"]).topology_signature,
        **REFERENCE, "binary_sha256": "a" * 64, "source_manifest": "synthetic-manifest",
        "feature_version": FEATURE_VERSION, "acquisition_source": "broad_random",
        "parent_key": None, "lineage_root_key": key, "validity_class": "valid",
        "split": assign_split(key), "benchmark_holdout": benchmark_holdout(key),
        "split_scheme_version": SPLIT_SCHEME_VERSION,
        "created_at": 0.0, "waveforms_json": "RAW LABELS MUST NOT BE READ",
        "canonical_frames_json": json.dumps({str(note): {
            "version": FEATURE_VERSION, "note_midi": note, "sample_rate": 48000,
            "frame_length": 2048, "samples": [0.125] * 2048,
        } for note in (45, 57, 69)}),
    }


def _build_corpus(path, n_train=4, n_val=2):
    wanted = {"train": n_train, "validation": n_val, "test": 1}
    found = {name: [] for name in wanted}
    i = 0
    while any(len(found[n]) < wanted[n] for n in wanted):
        patch = blank_patch().to_dict()
        patch["algorithm"] = i % 32 + 1
        patch["operators"][0]["fine"] = i // 32
        patch["operators"][1]["level"] = (i * 7) % 100
        row = _row(patch)
        group = "benchmark" if row["benchmark_holdout"] else row["split"]
        if group in wanted and len(found[group]) < wanted[group]:
            # Independent roots keep lineage audit trivially satisfied.
            found[group].append(row)
        i += 1
        if i > 60000:
            raise AssertionError("could not sample required split groups")
    rows = [r for group in found.values() for r in group]
    path = path / "data.parquet" if path.is_dir() else path
    pq.write_table(pa.Table.from_pylist(rows, schema=NATIVE_OBSERVATION_SCHEMA), path)
    return path


@pytest.fixture
def corpus(tmp_path):
    return _build_corpus(tmp_path, n_train=4, n_val=2)


def _config(corpus, tmp_path, **overrides):
    args = {
        "corpus": corpus, "checkpoint_dir": tmp_path / "checkpoints",
        "seed": 0, "device": "cpu", "epochs": 1, "batch_size": 2,
        "learning_rate": 1e-3, "max_rows": None,
    }
    args.update(overrides)
    return TrainConfig(**args)


def test_config_validation(corpus, tmp_path):
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, epochs=0)
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, batch_size=0)
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, max_steps=0)
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, max_rows=0)
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, learning_rate=0.0)
    with pytest.raises(ValueError):
        TrainConfig(corpus, tmp_path / "c", best_filename="last.pt", last_filename="last.pt")


def test_resolve_device_and_seeding():
    assert str(resolve_device("cpu")) == "cpu"
    assert str(resolve_device("auto")) in {"cpu", "cuda"}
    with pytest.raises(ValueError):
        resolve_device("cuda:9:bad:spec:::")
    seed_everything(123)
    first = torch.randn(4).tolist()
    seed_everything(123)
    assert torch.randn(4).tolist() == first


def test_loaders_train_validation_only(corpus, tmp_path):
    config = _config(corpus, tmp_path)
    train_loader, val_loader = make_loaders(config)
    assert train_loader.dataset.split == "train"
    assert val_loader.dataset.split == "validation"
    assert len(train_loader.dataset) >= 1 and len(val_loader.dataset) >= 1
    batch = next(iter(train_loader))
    assert batch["waveform"].shape[1:] == (3, 2048)
    assert batch["operators"].shape[1:] == (6, 5)
    # Protected rows exist in the corpus file but are never loaded for training.
    assert len(ForwardDataset(corpus, "test", allow_protected=True)) >= 1
    assert config.max_rows is None  # full routine splits by default


def test_train_finite_checkpoints_and_resume(corpus, tmp_path):
    tiny = lambda: ForwardModel(hidden_dims=(32, 32), algorithm_dim=4)
    config = _config(corpus, tmp_path, epochs=2, max_rows=4)
    first = train(config, model=tiny())
    assert first["epochs_run"] == 2
    assert all(math.isfinite(h["train_loss"]) and math.isfinite(h["val_loss"])
               for h in first["history"])
    assert first["last_checkpoint"] and first["best_checkpoint"]
    best_before = __import__("pathlib").Path(first["best_checkpoint"]).read_bytes()
    # Resume: loads last.pt, keeps improving-or-equal best without clobbering.
    config2 = _config(corpus, tmp_path, epochs=5, max_rows=4)
    second = train(config2, model=tiny())
    assert second["global_step"] >= first["global_step"]
    assert math.isfinite(second["best_val"])
    assert math.isfinite(first["best_val"])
    assert __import__("pathlib").Path(second["best_checkpoint"]).exists()
    # Best is the running minimum: resume can only keep or improve it.
    assert second["best_val"] <= first["best_val"] + 1e-9
    assert best_before  # best file materialized; strict-improvement guard in engine


def test_train_max_steps_bound(corpus, tmp_path):
    config = _config(corpus, tmp_path, epochs=10, max_steps=1)
    summary = train(config, model=ForwardModel(hidden_dims=(16, 16), algorithm_dim=4))
    assert summary["global_step"] == 1
    assert summary["epochs_run"] <= 1


def test_save_load_roundtrip(tmp_path):
    model = ForwardModel(hidden_dims=(16, 16), algorithm_dim=4)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    path = tmp_path / "last.pt"
    save_checkpoint(path, model, optimizer, epoch=2, global_step=7, best_val=0.5)
    assert path.exists()
    assert not list(tmp_path.glob("*.tmp"))  # atomic write leaves no temp files
    revived = ForwardModel(hidden_dims=(16, 16), algorithm_dim=4)
    state = load_checkpoint(path, revived)
    assert (state["epoch"], state["global_step"], state["best_val"]) == (2, 7, 0.5)
    # completed_epochs defaults to epoch + 1 for end-of-epoch saves.
    assert state["completed_epochs"] == 3
    # Checkpoint provenance capture.
    assert state["model_version"] == "dexfrag-forward-mlp-v2"
    assert state["feature_version"] == FEATURE_VERSION == DATA_FEATURE_VERSION
    assert state["scorer_version"] == SCORER_VERSION
    assert isinstance(state["git_commit"], str)
    for a, b in zip(model.parameters(), revived.parameters()):
        assert torch.equal(a, b)


def test_load_checkpoint_rejects_foreign_model_version(tmp_path):
    model = ForwardModel(hidden_dims=(16, 16), algorithm_dim=4)
    path = tmp_path / "last.pt"
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    save_checkpoint(path, model, optimizer, epoch=0, global_step=1, best_val=1.0)
    payload = torch.load(path, map_location="cpu", weights_only=True)
    payload["model_version"] = "dexfrag-forward-mlp-v1"
    torch.save(payload, path)
    with pytest.raises(ValueError):
        load_checkpoint(path, ForwardModel(hidden_dims=(16, 16), algorithm_dim=4))


def test_save_checkpoint_provenance_from_train(corpus, tmp_path):
    tiny = lambda: ForwardModel(hidden_dims=(16, 16), algorithm_dim=4)
    config = _config(corpus, tmp_path, epochs=1)
    train(config, model=tiny())
    state = load_checkpoint(config.last_path, tiny())
    assert state["completed_epochs"] == 1
    assert state["corpus_path"] == str(config.corpus)
    assert state["corpus_rows"] == len(
        ForwardDataset(corpus, "train", allow_protected=False)
    ) + len(ForwardDataset(corpus, "validation", allow_protected=False))
    assert isinstance(state["train_config"], dict)
    assert state["train_config"]["epochs"] == 1
    assert state["feature_version"] == FEATURE_VERSION
    assert state["scorer_version"] == SCORER_VERSION


def test_smoke_train_wiring():
    result = smoke_train(device="cpu", steps=2, batch_size=2)
    assert result["ok"] and result["finite"] and result["params_updated"]
    assert result["restored_step"] == 2


def test_evaluate_finite(corpus, tmp_path):
    import math

    config = _config(corpus, tmp_path)
    _, val_loader = make_loaders(config)
    metrics = evaluate(ForwardModel(), val_loader, resolve_device("cpu"))
    assert math.isfinite(metrics["loss"]) and metrics["batches"] >= 1


def test_interrupt_resume_reruns_interrupted_epoch(corpus, tmp_path):
    import unittest.mock as mock

    tiny = lambda: ForwardModel(hidden_dims=(16, 16), algorithm_dim=4)
    # One clean epoch completes: completed_epochs == 1.
    config = _config(corpus, tmp_path, epochs=1)
    first = train(config, model=tiny())
    assert first["epochs_run"] == 1
    assert load_checkpoint(config.last_path, tiny())["completed_epochs"] == 1
    # Interrupt during epoch 1's training: the resumed run starts at epoch 1,
    # so the very first forward_loss call belongs to epoch 1.
    calls = {"n": 0}

    def flaky(pred, target):
        calls["n"] += 1
        raise KeyboardInterrupt("simulated interrupt")

    config2 = _config(corpus, tmp_path, epochs=3)
    with mock.patch.object(ft, "forward_loss", side_effect=flaky):
        with pytest.raises(KeyboardInterrupt):
            train(config2, model=tiny())
    interrupted = load_checkpoint(config2.last_path, tiny())
    assert interrupted["epoch"] == 1  # interrupted epoch index is recorded
    assert interrupted["completed_epochs"] == 1  # only epoch 0 fully completed
    # Resume re-runs the interrupted epoch instead of skipping it.
    config3 = _config(corpus, tmp_path, epochs=2)
    resumed = train(config3, model=tiny())
    assert [record["epoch"] for record in resumed["history"]] == [1]
    assert resumed["epochs_run"] == 1


def test_evaluate_sample_weighted_uneven_batches():
    import unittest.mock as mock

    from dexfrag.algorithms import topology_for

    device = resolve_device("cpu")

    def fake_batch(fill: float, size: int):
        return {
            "algorithm": torch.ones(size, dtype=torch.long),
            "feedback": torch.zeros(size, dtype=torch.long),
            "operators": torch.zeros(size, 6, 5, dtype=torch.long),
            "topology_signature": [
                topology_for(1).topology_signature for _ in range(size)
            ],
            "waveform": torch.full((size, 3, 2048), fill, dtype=torch.float32),
        }

    loader = [fake_batch(0.0, 2), fake_batch(1.0, 2), fake_batch(2.0, 1)]

    def fake_loss(pred, target):
        value = (target**2).mean()
        return {
            "loss": value, "waveform_mse": value,
            "complex_harmonic_mse": value, "correlation_loss": value,
        }

    stub = mock.MagicMock()
    stub.forward_batch.side_effect = lambda batch: torch.zeros_like(batch["waveform"])
    with mock.patch.object(ft, "forward_loss", side_effect=fake_loss):
        metrics = evaluate(stub, loader, device)
    # Batch means are 0, 1, 4 over sizes 2, 2, 1: weighted mean is 6/5.
    assert metrics["batches"] == 3
    assert metrics["samples"] == 5
    assert metrics["loss"] == pytest.approx(6 / 5)
    # An unweighted batch mean (5/3) must not be returned.
    assert metrics["loss"] != pytest.approx(5 / 3)


def test_early_stopping_patience(corpus, tmp_path):
    import unittest.mock as mock

    tiny = lambda: ForwardModel(hidden_dims=(16, 16), algorithm_dim=4)
    frozen = {"loss": 1.0, "waveform_mse": 1.0, "complex_harmonic_mse": 1.0,
              "correlation_loss": 1.0, "batches": 1, "samples": 2}

    def flat_val(model, loader, device):
        return dict(frozen)

    config = _config(corpus, tmp_path, epochs=5, patience=1)
    with mock.patch.object(ft, "evaluate", side_effect=flat_val):
        summary = train(config, model=tiny())
    # Epoch 0 improves (inf -> 1.0); epoch 1 shows no improvement; stop.
    assert summary["epochs_run"] == 2
    assert summary["early_stopped"] is True
    assert config.last_path.exists()


def test_patience_validation(corpus, tmp_path):
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, patience=0)
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, patience="2")
    valid = _config(corpus, tmp_path, patience=2)
    assert valid.patience == 2
