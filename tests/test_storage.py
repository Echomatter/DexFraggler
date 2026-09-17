import math

import pytest

from dexfrag.features import canonical_frame
from dexfrag.native import NativeRenderer, DEFAULT_EXECUTABLE
from dexfrag.patch import blank_patch
from dexfrag.storage import append_observations, observation_row_from_capture, read_observations

pytestmark = pytest.mark.skipif(
    not DEFAULT_EXECUTABLE.is_file(),
    reason="native/bin/DexfragglerReference.exe is required for storage round-trip tests",
)


def test_append_and_read_round_trip(tmp_path):
    renderer = NativeRenderer()
    try:
        capture = renderer.render(blank_patch())
    finally:
        renderer.close()

    frames = {note: canonical_frame(wave, note, max_harmonics=32) for note, wave in zip(capture.notes, capture.waveforms)}
    row = observation_row_from_capture(
        capture, frames, acquisition_source="smoke_test", validity_class="valid", split="train",
    )
    dataset_path = tmp_path / "observations.parquet"
    table = append_observations(dataset_path, [row])
    assert table.num_rows == 1

    reloaded = read_observations(dataset_path)
    assert reloaded.num_rows == 1
    assert reloaded.column("key").to_pylist()[0] == row["key"]


def test_append_deduplicates_by_exact_key(tmp_path):
    renderer = NativeRenderer()
    try:
        capture = renderer.render(blank_patch())
    finally:
        renderer.close()
    frames = {note: canonical_frame(wave, note, max_harmonics=16) for note, wave in zip(capture.notes, capture.waveforms)}
    row = observation_row_from_capture(capture, frames, acquisition_source="smoke_test", validity_class="valid", split="train")

    dataset_path = tmp_path / "observations.parquet"
    append_observations(dataset_path, [row])
    table = append_observations(dataset_path, [row])  # exact duplicate, must not double-append
    assert table.num_rows == 1
