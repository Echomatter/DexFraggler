"""Focused TensorBoard + interrupt-safety tests for forward training."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

import dexfrag.forward_training as ft
from dexfrag.algorithms import topology_for
from dexfrag.features import FEATURE_VERSION
from dexfrag.forward_model import ForwardModel
from dexfrag.forward_training import TrainConfig, load_checkpoint, train
from dexfrag.patch import blank_patch, patch_key
from dexfrag.splits import SPLIT_SCHEME_VERSION, assign_split, benchmark_holdout
from dexfrag.storage import NATIVE_OBSERVATION_SCHEMA, OBSERVATION_SCHEMA_VERSION
from dexfrag.forward_data import REFERENCE


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


def _scalar_tags(log_dir: Path):
    ea = EventAccumulator(str(log_dir))
    ea.Reload()
    return set(ea.Tags()["scalars"])


def test_tensorboard_writer_logs_scalars(corpus, tmp_path):
    tb_dir = tmp_path / "runs" / "tb-param"
    config = _config(corpus, tmp_path, epochs=1)
    summary = train(
        config,
        model=ForwardModel(hidden_dims=(16, 16), algorithm_dim=4),
        tensorboard_dir=tb_dir,
    )
    assert summary["epochs_run"] == 1
    assert list(tb_dir.glob("events.out.tfevents.*")), "expected a TB event file"
    tags = _scalar_tags(tb_dir)
    for expected in ("train_loss", "val_loss", "best_val", "learning_rate", "global_step"):
        assert expected in tags, f"missing TensorBoard scalar: {expected} (got {sorted(tags)})"


def test_tensorboard_dir_from_config(corpus, tmp_path):
    tb_dir = tmp_path / "runs" / "tb-config"
    config = _config(corpus, tmp_path, epochs=1, tensorboard_dir=tb_dir)
    summary = train(config, model=ForwardModel(hidden_dims=(16, 16), algorithm_dim=4))
    assert summary["epochs_run"] == 1
    assert list(tb_dir.glob("events.out.tfevents.*")), "expected a TB event file"
    assert {"train_loss", "val_loss", "best_val"} <= _scalar_tags(tb_dir)


def test_interrupt_leaves_valid_checkpoint(corpus, tmp_path):
    config = _config(corpus, tmp_path, epochs=3)
    calls = {"n": 0}
    original = ft.forward_loss

    def flaky(pred, target):
        calls["n"] += 1
        if calls["n"] > 3:  # first epoch (2 train + 1 val calls) completes
            raise KeyboardInterrupt("simulated interrupt")
        return original(pred, target)

    import unittest.mock as mock

    with mock.patch.object(ft, "forward_loss", side_effect=flaky):
        with pytest.raises(KeyboardInterrupt):
            train(config, model=ForwardModel(hidden_dims=(16, 16), algorithm_dim=4))
    assert config.last_path.exists(), "interrupt must still leave last.pt"
    revived = ForwardModel(hidden_dims=(16, 16), algorithm_dim=4)
    state = load_checkpoint(config.last_path, revived)
    assert state["epoch"] == 1  # current (interrupted) epoch is checkpointed
    assert state["completed_epochs"] == 1  # only epoch 0 fully completed
    assert state["global_step"] == 2


def test_config_tensorboard_default(corpus, tmp_path):
    config = _config(corpus, tmp_path)
    assert config.tensorboard_dir is None
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, tensorboard_dir="runs/tb")
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, tensorboard_dir=123)
