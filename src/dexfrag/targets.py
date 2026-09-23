"""Black-box target adapter: generated wavetables -> waveform-derived records.

Bridges the curriculum producer (curriculum.py) and the existing black-box
target boundary (features.validate_wavetable / features.black_box_target_features)
into the derived TARGET_RECORD_SCHEMA store (storage.py).

Black-box rule (Master Overview principle #5): the model/search system must
never receive generator provenance. This adapter deliberately stores only
waveform-derived features plus allow-listed opaque bookkeeping
(source_file_hash, table_hash, frame_index, experiment_id, target_hash).
Seed, recipe, multiplex count, generator identity, and difficulty labels are
rejected at the boundary by FORBIDDEN_TARGET_KEYS.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Sequence

import numpy as np
from scipy.io import wavfile

from .features import (
    black_box_target_features,
    validate_wavetable,
    CANONICAL_WAVETABLE_FRAMES,
    DEFAULT_FRAME_LENGTH,
    FeatureError,
)
from .storage import TARGET_RECORD_SCHEMA_VERSION, append_target_records


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_wavetable_frames(
    path: Path | str,
    *,
    expected_frame_count: int = CANONICAL_WAVETABLE_FRAMES,
    expected_frame_length: int = DEFAULT_FRAME_LENGTH,
) -> np.ndarray:
    """Read one generated wavetable WAV into a [256, 2048] float64 frame table.

    int16 PCM is normalized to [-1, 1] exactly as quantized at generation time.
    Mono only; the exact canonical shape is enforced with no frame reduction
    (Phase 1 gate: a canonical wavetable ingests without reduction).
    """
    path = Path(path)
    _, data = wavfile.read(path)
    if data.ndim != 1:
        raise FeatureError("A canonical target wavetable WAV must be mono.")
    expected_samples = expected_frame_count * expected_frame_length
    if data.shape[0] != expected_samples:
        raise FeatureError(
            f"A canonical target wavetable must contain {expected_frame_count} frames of "
            f"{expected_frame_length} samples ({expected_samples} PCM samples); got {data.shape[0]}."
        )
    if np.issubdtype(data.dtype, np.integer):
        frames = data.astype(np.float64) / 32768.0
    else:
        frames = data.astype(np.float64)
    return frames.reshape(expected_frame_count, expected_frame_length)


def ingest_wavetable_frames(
    frames: Sequence[Sequence[float]],
    *,
    source_file_hash: str | None = None,
    table_hash: str | None = None,
    experiment_id: str | None = None,
) -> list[dict]:
    """Convert a validated canonical wavetable into TARGET_RECORD_SCHEMA rows.

    Every frame becomes one opaque target: waveform-derived features plus
    allow-listed bookkeeping only. Raises FeatureError if the frames violate
    the canonical [256, 2048] contract or bookkeeping is not allow-listed.
    """
    validate_wavetable(frames)
    array = np.asarray(frames, dtype=np.float64)
    if array.shape != (CANONICAL_WAVETABLE_FRAMES, DEFAULT_FRAME_LENGTH):
        raise FeatureError(
            f"Expected a [{CANONICAL_WAVETABLE_FRAMES}, {DEFAULT_FRAME_LENGTH}] "
            f"canonical wavetable; got {array.shape}."
        )
    if table_hash is None:
        table_hash = _sha256_hex(array.tobytes())

    rows: list[dict] = []
    for index, frame_array in enumerate(array):
        target_hash = _sha256_hex(frame_array.tobytes())
        bookkeeping: dict = {"frame_index": index, "table_hash": table_hash}
        if source_file_hash is not None:
            bookkeeping["source_file_hash"] = source_file_hash
        if experiment_id is not None:
            bookkeeping["experiment_id"] = experiment_id
        features = black_box_target_features(frame_array.tolist(), bookkeeping=bookkeeping)
        rows.append(
            {
                "schema_version": TARGET_RECORD_SCHEMA_VERSION,
                "target_hash": target_hash,
                "source_file_hash": source_file_hash,
                "frame_index": index,
                "table_hash": table_hash,
                "experiment_id": experiment_id,
                "frame_length": DEFAULT_FRAME_LENGTH,
                "features_json": json.dumps(features),
                "created_at": time.time(),
            }
        )
    return rows


def ingest_wavetable_file(
    path: Path | str,
    *,
    experiment_id: str = "curriculum-v1",
) -> list[dict]:
    """Read + ingest one generated wavetable WAV as black-box target records."""
    path = Path(path)
    frames = read_wavetable_frames(path)
    source_file_hash = _sha256_hex(path.read_bytes())
    return ingest_wavetable_frames(
        frames,
        source_file_hash=source_file_hash,
        experiment_id=experiment_id,
    )


def ingest_wavetable_folder(
    folder: Path | str,
    output: Path | str,
    *,
    experiment_id: str = "curriculum-v1",
) -> dict:
    """Ingest every generated wavetable WAV in a folder into one Parquet store."""
    folder = Path(folder)
    output = Path(output)
    wav_files = sorted(folder.glob("*.wav"))
    total_records = 0
    for path in wav_files:
        rows = ingest_wavetable_file(path, experiment_id=experiment_id)
        append_target_records(output, rows)
        total_records += len(rows)
    return {
        "source_files": len(wav_files),
        "records": total_records,
        "output": str(output),
    }