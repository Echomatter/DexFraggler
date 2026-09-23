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

SHARD_MAX_ROWS = 1000

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
    pa.field("parent_key", pa.string(), nullable=True),  # mutation lineage (immediate parent)
    pa.field("lineage_root_key", pa.string()),  # split.py's split key: family root patch_key
    pa.field("validity_class", pa.string()),  # valid | silent | near_silent | clipped | unstable
    pa.field("split", pa.string()),  # train | validation | test
    pa.field("benchmark_holdout", pa.bool_()),  # stricter structural-family holdout (splits.benchmark_holdout)
    pa.field("split_scheme_version", pa.string()),
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


def _is_shard_mode(path: Path) -> bool:
    return path.suffix != ".parquet"


def _shard_path(directory: Path, index: int) -> Path:
    return directory / f"shard_{index:05d}.parquet"


def _keys_index_path(directory: Path) -> Path:
    return directory / "keys_index.json"


def _read_keys_index(directory: Path) -> dict[str, int]:
    idx_path = _keys_index_path(directory)
    if idx_path.exists():
        with open(idx_path, "r", encoding="utf-8") as f:
            return json.load(f)
    index: dict[str, int] = {}
    for shard_file in sorted(directory.glob("shard_*.parquet")):
        shard_num = int(shard_file.stem.split("_")[1])
        table = pq.read_table(shard_file, columns=["key"])
        for k in table.column("key").to_pylist():
            index[k] = shard_num
    _write_keys_index(directory, index)
    return index


def _write_keys_index(directory: Path, index: dict[str, int]) -> None:
    idx_path = _keys_index_path(directory)
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f)


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
    if _is_shard_mode(path):
        if not path.is_dir():
            return NATIVE_OBSERVATION_SCHEMA.empty_table()
        shard_files = sorted(path.glob("shard_*.parquet"))
        if not shard_files:
            return NATIVE_OBSERVATION_SCHEMA.empty_table()
        tables = [pq.read_table(sf, schema=NATIVE_OBSERVATION_SCHEMA) for sf in shard_files]
        return pa.concat_tables(tables)
    return pq.read_table(path, schema=NATIVE_OBSERVATION_SCHEMA)


def append_observations(path: Path | str, rows: list[dict]) -> pa.Table:
    """Append rows to the observation table, skipping exact-key duplicates.

    Single-file mode (path ends with ``.parquet``): rewrites the whole file
    atomically. Acceptable for Phase 1/2 smoke scale.

    Shard mode (any other path): appends to numbered shard files inside the
    directory, starting a new shard once the current one reaches
    ``SHARD_MAX_ROWS``. A sidecar ``keys_index.json`` tracks key→shard
    mappings for O(1) dedup without reading every shard.
    """
    path = Path(path)
    if not _is_shard_mode(path):
        existing = read_observations(path)
        existing_keys = set(existing.column("key").to_pylist()) if existing.num_rows else set()
        seen_keys = set(existing_keys)
        new_rows = []
        for row in rows:
            if row["key"] not in seen_keys:
                new_rows.append(row)
                seen_keys.add(row["key"])
        if not new_rows:
            return existing
        new_table = pa.Table.from_pylist(new_rows, schema=NATIVE_OBSERVATION_SCHEMA)
        combined = pa.concat_tables([existing, new_table]) if existing.num_rows else new_table
        _atomic_write_table(path, combined)
        return combined

    path.mkdir(parents=True, exist_ok=True)
    key_index = _read_keys_index(path)
    seen_keys = set(key_index)
    new_rows = []
    for row in rows:
        if row["key"] not in seen_keys:
            new_rows.append(row)
            seen_keys.add(row["key"])
    if not new_rows:
        return read_observations(path)

    shard_files = sorted(path.glob("shard_*.parquet"))
    if shard_files:
        current_shard_idx = int(shard_files[-1].stem.split("_")[1])
        current_shard_table = pq.read_table(shard_files[-1], schema=NATIVE_OBSERVATION_SCHEMA)
        current_row_count = current_shard_table.num_rows
    else:
        current_shard_idx = 0
        current_shard_table = None
        current_row_count = 0
    if current_row_count >= SHARD_MAX_ROWS:
        current_shard_idx += 1
        current_shard_table = None
        current_row_count = 0

    batch: list[dict] = []
    for row in new_rows:
        if current_row_count + len(batch) >= SHARD_MAX_ROWS and batch:
            batch_table = pa.Table.from_pylist(batch, schema=NATIVE_OBSERVATION_SCHEMA)
            if current_shard_table is not None:
                merged = pa.concat_tables([current_shard_table, batch_table])
            else:
                merged = batch_table
            _atomic_write_table(_shard_path(path, current_shard_idx), merged)
            for r in batch:
                key_index[r["key"]] = current_shard_idx
            current_shard_table = None
            current_shard_idx += 1
            current_row_count = 0
            batch = []
        batch.append(row)

    if batch:
        batch_table = pa.Table.from_pylist(batch, schema=NATIVE_OBSERVATION_SCHEMA)
        if current_shard_table is not None:
            merged = pa.concat_tables([current_shard_table, batch_table])
        else:
            merged = batch_table
        _atomic_write_table(_shard_path(path, current_shard_idx), merged)
        for r in batch:
            key_index[r["key"]] = current_shard_idx

    _write_keys_index(path, key_index)
    return read_observations(path)


def observation_row_from_capture(capture, canonical_frames: dict, *, acquisition_source: str,
                                  validity_class: str, split: str, lineage_root_key: str,
                                  benchmark_holdout: bool = False, parent_key: str | None = None,
                                  include_waveforms: bool = True) -> dict:
    """Build one Parquet row from a NativeCapture + per-note CanonicalFrame map.

    ``canonical_frames`` maps note (int) -> CanonicalFrame.
    """
    from .algorithms import topology_for
    from .splits import SPLIT_SCHEME_VERSION

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
        "lineage_root_key": lineage_root_key,
        "validity_class": validity_class,
        "split": split,
        "benchmark_holdout": benchmark_holdout,
        "split_scheme_version": SPLIT_SCHEME_VERSION,
        "created_at": capture.rendered_at,
    }


TARGET_RECORD_SCHEMA_VERSION = "dexfrag-target-record-v1"


def read_target_records(path: Path | str) -> pa.Table:
    """Read a black-box target-record store (empty table when missing)."""
    path = Path(path)
    if not path.exists():
        return TARGET_RECORD_SCHEMA.empty_table()
    return pq.read_table(path, schema=TARGET_RECORD_SCHEMA)


def append_target_records(path: Path | str, rows: list[dict]) -> pa.Table:
    """Append target-record rows to the derived target store, skipping exact
    ``target_hash`` duplicates via an atomic single-file rewrite.

    Mirror of ``append_observations``' single-file path for the derived
    target-records table. Target records are regenerable experiment data and
    stay physically separate from permanent native observations.
    """
    path = Path(path)
    existing = read_target_records(path)
    existing_hashes = (
        set(existing.column("target_hash").to_pylist()) if existing.num_rows else set()
    )
    new_rows: list[dict] = []
    for row in rows:
        if row["target_hash"] not in existing_hashes:
            existing_hashes.add(row["target_hash"])
            new_rows.append(row)
    if not new_rows:
        return existing
    new_table = pa.Table.from_pylist(new_rows, schema=TARGET_RECORD_SCHEMA)
    combined = pa.concat_tables([existing, new_table]) if existing.num_rows else new_table
    _atomic_write_table(path, combined)
    return combined