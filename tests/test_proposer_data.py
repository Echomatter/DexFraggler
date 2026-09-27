import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch

from dexfrag.algorithms import topology_for
from dexfrag.features import FEATURE_VERSION
from dexfrag.forward_data import REFERENCE
from dexfrag.patch import blank_patch, patch_key
from dexfrag.proposer_data import ProposerDataset, ProposerTargetDataset
from dexfrag.proposer_model import ProposerModel, generate_candidates
from dexfrag.splits import SPLIT_SCHEME_VERSION, assign_split, benchmark_holdout
from dexfrag.storage import NATIVE_OBSERVATION_SCHEMA, OBSERVATION_SCHEMA_VERSION
from dexfrag.targets import ingest_wavetable_frames


def _native_row(patch):
    key = patch_key(patch)
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION, "key": key,
        "patch_json": json.dumps(patch), "algorithm": patch["algorithm"], "feedback": patch["feedback"],
        "algorithm_topology_signature": topology_for(patch["algorithm"]).topology_signature,
        **REFERENCE, "binary_sha256": "a" * 64, "source_manifest": "synthetic",
        "feature_version": FEATURE_VERSION, "acquisition_source": "synthetic",
        "parent_key": None, "lineage_root_key": key, "validity_class": "valid",
        "split": assign_split(key), "benchmark_holdout": benchmark_holdout(key),
        "split_scheme_version": SPLIT_SCHEME_VERSION, "created_at": 0.0,
        "waveforms_json": None,
        "canonical_frames_json": json.dumps({str(note): {
            "version": FEATURE_VERSION, "note_midi": note, "sample_rate": 48000,
            "frame_length": 2048, "samples": [0.125] * 2048,
        } for note in (45, 57, 69)}),
    }


def _corpus(path):
    groups = {}
    index = 0
    while "validation" not in groups or "train" not in groups or "test" not in groups:
        patch = blank_patch().to_dict()
        patch["algorithm"] = index % 32 + 1
        patch["operators"][0]["fine"] = index // 32
        row = _native_row(patch)
        group = "benchmark" if row["benchmark_holdout"] else row["split"]
        if group in {"train", "validation", "test"} and group not in groups:
            groups[group] = row
        index += 1
        if index > 10000:
            raise AssertionError("could not construct split fixture")
    rows = list(groups.values())
    pq.write_table(pa.Table.from_pylist(rows, schema=NATIVE_OBSERVATION_SCHEMA), path)
    return path


def test_native_proposer_dataset_preserves_labels_and_waveforms(tmp_path):
    path = _corpus(tmp_path / "native.parquet")
    dataset = ProposerDataset(path, "train")
    item = dataset[0]
    assert item["waveform"].shape == (3, 2048)
    assert item["operators"].shape == (6, 5)
    assert item["target_hash"] == item["key"]
    with pytest.raises(ValueError):
        ProposerDataset(path, "test")


def test_black_box_target_dataset_uses_waveform_samples_only(tmp_path):
    frames = [[float(index)] * 2048 for index in range(256)]
    rows = ingest_wavetable_frames(frames, table_hash="table", experiment_id="experiment")
    import pyarrow as pa
    from dexfrag.storage import TARGET_RECORD_SCHEMA
    path = tmp_path / "targets.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=TARGET_RECORD_SCHEMA), path)
    dataset = ProposerTargetDataset(path, max_rows=2)
    assert len(dataset) == 2
    item = dataset[1]
    assert item["waveform"].shape == (1, 2048)
    assert item["waveform"][0, 0].item() == 1.0
    assert "algorithm" not in item
    assert "generator" not in item
    assert "seed" not in item
    assert torch.isfinite(item["waveform"]).all()
    candidates = generate_candidates(
        ProposerModel(hidden_dim=16, harmonic_bands=8, conv_channels=4),
        item["waveform"], count=4, seed=7,
    )
    assert len(candidates) == 4
    assert all(1 <= candidate.algorithm <= 32 for candidate in candidates)


def test_target_dataset_rejects_forbidden_features(tmp_path):
    frames = [[0.0] * 2048 for _ in range(256)]
    rows = ingest_wavetable_frames(frames, table_hash="table", experiment_id="experiment")
    for row in rows:
        features = json.loads(row["features_json"])
        features["seed"] = 17
        row["features_json"] = json.dumps(features)
    from dexfrag.storage import TARGET_RECORD_SCHEMA
    path = tmp_path / "targets.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=TARGET_RECORD_SCHEMA), path)
    with pytest.raises(ValueError, match="forbidden provenance"):
        ProposerTargetDataset(path)


def test_target_dataset_rejects_bad_record(tmp_path):
    from dexfrag.storage import TARGET_RECORD_SCHEMA
    path = tmp_path / "targets.parquet"
    pq.write_table(pa.Table.from_pylist([{
        "schema_version": "wrong", "target_hash": "x", "source_file_hash": None,
        "frame_index": None, "table_hash": None, "experiment_id": None,
        "frame_length": 2048, "features_json": "{}", "created_at": 0.0,
    }], schema=TARGET_RECORD_SCHEMA), path)
    with pytest.raises(ValueError):
        ProposerTargetDataset(path)
