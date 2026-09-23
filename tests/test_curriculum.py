"""Tests for the ported black-box target curriculum producer (curriculum.py).

Covers exact deterministic reproduction (same seed -> byte-identical WAVs),
run-level int16 PCM slice uniqueness, canonical [256, 2048] distribution, and
the black-box ingestion contract of the produced tables.
"""
from math import perm

import numpy as np
import pytest

from dexfrag.curriculum import (
    GeneratorConfig,
    build_global_slice_pool,
    distribute_slice_pool,
    frame_audio_key,
    generate_wavetables,
    recipe_capacity,
    wavetable_filename,
    waveforms,
)
from dexfrag.targets import ingest_wavetable_frames, read_wavetable_frames


def test_deterministic_reproduction(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    config_a = GeneratorConfig(tables=2, frame_size=2048, frame_count=16, seed=7, folder=a)
    config_b = GeneratorConfig(tables=2, frame_size=2048, frame_count=16, seed=7, folder=b)
    files_a, _ = generate_wavetables(config_a)
    files_b, _ = generate_wavetables(config_b)
    assert [f.name for f in files_a] == [f.name for f in files_b]
    for fa, fb in zip(files_a, files_b):
        assert fa.read_bytes() == fb.read_bytes()


def test_run_level_slice_uniqueness():
    config = GeneratorConfig(tables=2, frame_size=2048, frame_count=16, seed=3)
    pool = build_global_slice_pool(config)
    assert len(pool) == config.tables * config.frame_count
    keys = [frame_audio_key(record.frame) for record in pool]
    assert len(set(keys)) == len(keys)


def test_distributed_tables_have_full_frame_counts():
    config = GeneratorConfig(tables=3, frame_size=2048, frame_count=16, seed=11)
    pool = build_global_slice_pool(config)
    tables = distribute_slice_pool(config, pool)
    assert [len(frames) for frames in tables] == [16, 16, 16]


def test_generated_table_ingests_as_canonical_256x2048(tmp_path):
    config = GeneratorConfig(tables=1, frame_size=2048, frame_count=256, seed=13, folder=tmp_path)
    created, _ = generate_wavetables(config)
    assert len(created) == 1
    frames = read_wavetable_frames(created[0])
    assert frames.shape == (256, 2048)
    records = ingest_wavetable_frames(frames, table_hash="tbl", experiment_id="curriculum-v1")
    assert len(records) == 256
    assert records[0]["frame_length"] == 2048
    assert records[0]["frame_index"] == 0
    assert records[-1]["frame_index"] == 255


def test_filenames_are_self_describing():
    config = GeneratorConfig(tables=2000, frame_size=2048, frame_count=256, seed=1994)
    assert wavetable_filename(config, 0) == (
        "Wavetable_0001-of-2000__FrameSize-2048__FrameCount-256__Seed-1994.wav"
    )


def test_recipe_capacity_matches_waveform_count():
    capacities = recipe_capacity()
    source_count = len(waveforms)
    assert source_count == 41
    assert capacities[0] == source_count
    assert capacities[2] == perm(source_count, 2)
    assert capacities[3] == perm(source_count, 3)
    assert capacities[5] == perm(source_count, 5)


def test_config_validation_rejects_bad_inputs():
    with pytest.raises(ValueError):
        GeneratorConfig(tables=0).validate()
    with pytest.raises(ValueError):
        GeneratorConfig(frame_size=64).validate()
    with pytest.raises(ValueError):
        GeneratorConfig(frame_count=0).validate()
    with pytest.raises(ValueError):
        GeneratorConfig(seed=-1).validate()