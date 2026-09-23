"""Tests for the black-box target adapter (targets.py) and the derived target store."""
import json

import pytest

from dexfrag.curriculum import GeneratorConfig, generate_wavetables
from dexfrag.features import FeatureError
from dexfrag.storage import (
    TARGET_RECORD_SCHEMA_VERSION,
    append_target_records,
    read_target_records,
)
from dexfrag.targets import (
    ingest_wavetable_file,
    ingest_wavetable_folder,
    ingest_wavetable_frames,
    read_wavetable_frames,
)


def _synthetic_canonical_frames():
    # 256 distinct finite frames, each exactly 2048 samples.
    return [[float(j)] * 2048 for j in range(256)]


def test_empty_target_store_round_trip(tmp_path):
    store = tmp_path / "targets.parquet"
    table = read_target_records(store)
    assert table.num_rows == 0


def test_append_target_records_round_trip_and_dedup(tmp_path):
    store = tmp_path / "targets.parquet"
    rows = ingest_wavetable_frames(_synthetic_canonical_frames(), table_hash="tbl", experiment_id="e1")
    appended = append_target_records(store, rows)
    assert appended.num_rows == 256
    assert set(appended.column("frame_index").to_pylist()) == set(range(256))
    # Exact duplicate targets (same target_hash) are skipped, not re-appended.
    again = append_target_records(store, rows)
    assert again.num_rows == 256
    # A distinct table (different samples -> different target hashes) still
    # appends on top.
    more = ingest_wavetable_frames(
        [[float(j) + 0.5] * 2048 for j in range(256)], table_hash="tbl2", experiment_id="e1"
    )
    merged = append_target_records(store, more)
    assert merged.num_rows == 512


def test_wavetable_file_to_store_end_to_end(tmp_path):
    config = GeneratorConfig(tables=1, frame_size=2048, frame_count=256, seed=21, folder=tmp_path)
    generate_wavetables(config)
    store = tmp_path / "targets.parquet"
    summary = ingest_wavetable_folder(tmp_path, store, experiment_id="curriculum-v1")
    assert summary["source_files"] == 1
    assert summary["records"] == 256
    table = read_target_records(store)
    assert table.num_rows == 256
    versions = table.column("schema_version").to_pylist()
    assert all(v == TARGET_RECORD_SCHEMA_VERSION for v in versions)


def test_target_features_are_waveform_derived_only(tmp_path):
    config = GeneratorConfig(tables=1, frame_size=2048, frame_count=256, seed=23, folder=tmp_path)
    created, _ = generate_wavetables(config)
    # The generated filename itself embeds Seed-23; provenance must never leak.
    assert "Seed-23" in created[0].name
    records = ingest_wavetable_file(created[0], experiment_id="curriculum-v1")
    features = json.loads(records[0]["features_json"])
    for forbidden in (
        "seed", "recipe", "generator", "generator_name", "multiplex",
        "multiplex_count", "waveform_class", "shape", "source_family", "difficulty",
    ):
        assert forbidden not in features
    assert features["frame_index"] == 0
    assert features["experiment_id"] == "curriculum-v1"
    assert features["frame_length"] == 2048
    assert "sin_coefficients" in features
    assert "cos_coefficients" in features


def test_read_rejects_canonical_shape_violation(tmp_path):
    config = GeneratorConfig(tables=1, frame_size=2048, frame_count=32, seed=25, folder=tmp_path)
    created, _ = generate_wavetables(config)
    # 32-frame tables are not canonical: no frame reduction is permitted.
    with pytest.raises(FeatureError):
        read_wavetable_frames(created[0])