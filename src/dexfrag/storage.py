"""Append-friendly Parquet observation storage.

Defines the permanent NativeObservation schema (patch identity, exact patch
bytes, algorithm structure, A2/A3/A4 native captures, canonical waveform
features, provenance, acquisition metadata) and keeps it strictly separate
from target-specific derived data (target records, target/patch scores,
search traces), per the Master Overview's "permanent truth vs experiment
data" principle. This module only defines/validates the schema and provides
atomic append/read helpers; Phase 2 owns the actual collection loop.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

OBSERVATION_SCHEMA_VERSION = "dexfrag-observation-v1"

NATIVE_OBSERVATION_SCHEMA = pa.schema([
    pa.field("schema_version", pa.string()),
    pa.field("key", pa.string()),  # exact patch identity (hex of 155 VCED bytes)
    pa.field("patch_json", pa.string()),  # canonical Patch.to_dict() JSON
    pa.field("algorithm", pa.int32()),
    pa.field("feedback", pa.int32()),
    pa.field("algorithm_topology_signature", pa.string()),
    pa.field("sample_rate", pa.int32()),
    pa.field("velocity", pa.int32()),
    pa.field("offset_samples", pa.int32()),
    pa.field("capture_samples", pa.int32()),
    pa.field("notes", pa.list_(pa.int32())),
    pa.field("binary_sha256", pa.string()),
    pa.field("source_manifest", pa.string()),
    pa.field("feature_version", pa.string()),
    pa.field("canonical_frame_length", pa.int32()),
    pa.field("canonical_frames_json", pa.string()),  # per-note CanonicalFrame.to_dict()
    pa.field("waveforms_json", pa.string(), nullable=True),  # raw 4096-sample captures, optional
    pa.field("acquisition_source", pa.string()),
    pa.field("parent_key", pa.string(), nullable=True),  # mutation lineage
    pa.field("validity_class", pa.string()),  # valid | silent | near_silent | clipped | unstable | render_failure
    pa.field("split", pa.string()),  # train | validation | test
    pa.field("created_at", pa.float64()),
])

TARGET_RECORD_SCHEMA = pa.schema([
    pa.field("schema_version", pa.string()),
    pa.field("target_hash", pa.string()),
    pa.field("source_file_hash", pa.string(), nullable=True),
    pa.field("frame_index", pa.int32(), nullable=True),
    pa.field("table_hash", pa.string(), nullable=True),
    pa.field("experiment_id", pa.string(), nullable=True),
    pa.field("frame_length", pa.int32()),
    pa.field("features_json", pa.string()),
    pa.field("created_at", pa.float64()),
])

TARGET_PATCH_SCORE_SCHEMA = pa.schema([
    pa.field("schema_version", pa.string()),
    pa.field("target_hash", pa.string()),
    pa.field("patch_key", pa.string()),
    pa.field("metric_version", pa.string()),
    pa.field("score", pa.float64()),
    pa.field("error", pa.float64()),
    pa.field("source", pa.string()),  # e.g. "native_verified" | "forward_predicted" | "compatibility_predicted"
    pa.field("experiment_id", pa.string(), nullable=True),
    pa.field("created_at", pa.float64()),
])


def _atomic_write_table(path: Path, table: pa.Table) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=directory, suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        pq.write_table(table, tmp_path)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def read_observations(path: Path | str) -> pa.Table:
    path = Path(path)
    if not path.exists():
        return NATIVE_OBSERVATION_SCHEMA.empty_table()
    return pq.read_table(path, schema=NATIVE_OBSERVATION_SCHEMA)


def append_observations(path: Path | str, rows: list[dict]) -> pa.Table:
    """Append rows to the observation table, skipping exact-key duplicates.

    Rewrites the whole file atomically (append-only Parquet without native
    row-group append support is not safe against partial writes). Acceptable
    for Phase 1/2 smoke scale; Phase 2's real collector may shard files by
    session instead of rewriting one growing file.
    """
    path = Path(path)
    existing = read_observations(path)
    existing_keys = set(existing.column("key").to_pylist()) if existing.num_rows else set()
    new_rows = [row for row in rows if row["key"] not in existing_keys]
    if not new_rows:
        return existing
    new_table = pa.Table.from_pylist(new_rows, schema=NATIVE_OBSERVATION_SCHEMA)
    combined = pa.concat_tables([existing, new_table]) if existing.num_rows else new_table
    _atomic_write_table(path, combined)
    return combined


def observation_row_from_capture(capture, canonical_frames: dict, *, acquisition_source: str,
                                  validity_class: str, split: str, parent_key: str | None = None,
                                  include_waveforms: bool = True) -> dict:
    """Build one Parquet row from a NativeCapture + per-note CanonicalFrame map.

    ``canonical_frames`` maps note (int) -> CanonicalFrame.
    """
    from .algorithms import topology_for

    topology = topology_for(capture.patch.algorithm)
    frames_payload = {str(note): frame.to_dict(include_samples=True) for note, frame in canonical_frames.items()}
    any_frame = next(iter(canonical_frames.values()))
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "key": capture.patch_key,
        "patch_json": json.dumps(capture.patch.to_dict()),
        "algorithm": capture.patch.algorithm,
        "feedback": capture.patch.feedback,
        "algorithm_topology_signature": topology.topology_signature,
        "sample_rate": capture.sample_rate,
        "velocity": capture.velocity,
        "offset_samples": capture.offset_samples,
        "capture_samples": capture.capture_samples,
        "notes": list(capture.notes),
        "binary_sha256": capture.binary_sha256,
        "source_manifest": capture.source_manifest,
        "feature_version": any_frame.version,
        "canonical_frame_length": any_frame.frame_length,
        "canonical_frames_json": json.dumps(frames_payload),
        "waveforms_json": json.dumps([list(w) for w in capture.waveforms]) if include_waveforms else None,
        "acquisition_source": acquisition_source,
        "parent_key": parent_key,
        "validity_class": validity_class,
        "split": split,
        "created_at": capture.rendered_at,
    }
