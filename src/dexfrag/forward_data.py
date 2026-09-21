"""Read-only, projected Phase 3 corpus prerequisite audit.

No waveform labels (including protected test labels) are read by this audit.
An audit is not evidence of prediction quality or label correctness.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

import pyarrow.parquet as pq
import pyarrow.dataset as ds
import torch
from torch.utils.data import Dataset

from .algorithms import topology_for
from .features import FEATURE_VERSION
from .patch import patch_key, validate_patch
from .splits import SPLIT_SCHEME_VERSION, assign_split, benchmark_holdout
from .storage import NATIVE_OBSERVATION_SCHEMA, OBSERVATION_SCHEMA_VERSION


AUDIT_COLUMNS = [name for name in NATIVE_OBSERVATION_SCHEMA.names
                 if name not in {"waveforms_json", "canonical_frames_json", "created_at"}]
REFERENCE = {"sample_rate": 48000, "velocity": 100, "offset_samples": 7200,
             "capture_samples": 4096, "notes": [45, 57, 69],
             "canonical_frame_length": 2048}


def audit_forward_corpus(path: str | Path) -> dict:
    """Check identities, versions, reference conditions and family isolation.

    Missing parents/roots are blockers: lineage cannot be verified locally.
    Only default v1 split ratios are accepted, since rows do not record custom
    ratios. Benchmark coverage is reported separately from routine splits.
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Corpus does not exist: {path}")
    files = sorted(path.glob("shard_*.parquet")) if path.is_dir() else [path]
    if not files:
        raise ValueError(f"Corpus has no observation shards: {path}")
    errors: Counter = Counter()
    examples: dict[str, list[str]] = {}

    def fail(reason: str, key: str) -> None:
        errors[reason] += 1
        samples = examples.setdefault(reason, [])
        if len(samples) < 3:
            samples.append(key)

    rows = []
    for file in files:
        schema = pq.read_schema(file)
        if any(name not in schema.names or schema.field(name).type !=
               NATIVE_OBSERVATION_SCHEMA.field(name).type for name in AUDIT_COLUMNS):
            fail("incompatible_schema", str(file))
            continue
        rows.extend(pq.read_table(file, columns=AUDIT_COLUMNS).to_pylist())
    by_key = {}
    validity: Counter = Counter()
    coverage = {split: Counter() for split in ("train", "validation", "test", "benchmark")}
    provenance: Counter = Counter()
    for row in rows:
        key = row["key"]
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{310}", key):
            fail("malformed_key", str(key))
            continue
        if key in by_key:
            fail("duplicate_key", key)
        by_key[key] = row
        try:
            patch = validate_patch(json.loads(row["patch_json"]))
            if patch_key(patch) != key:
                fail("identity_mismatch", key)
            if (row["algorithm"] != patch.algorithm or row["feedback"] != patch.feedback or
                    row["algorithm_topology_signature"] != topology_for(patch.algorithm).topology_signature):
                fail("structure_mismatch", key)
        except (ValueError, TypeError, KeyError):
            fail("invalid_patch", key)
        for field, expected in {"schema_version": OBSERVATION_SCHEMA_VERSION,
                                "feature_version": FEATURE_VERSION,
                                "split_scheme_version": SPLIT_SCHEME_VERSION,
                                **REFERENCE}.items():
            if row[field] != expected:
                fail(f"unexpected_{field}", key)
        root = row["lineage_root_key"]
        if not isinstance(root, str) or not re.fullmatch(r"[0-9a-f]{310}", root):
            fail("invalid_lineage_root", key)
        else:
            if row["split"] != assign_split(root):
                fail("split_mismatch", key)
            if row["benchmark_holdout"] != benchmark_holdout(root):
                fail("benchmark_mismatch", key)
        sha = row["binary_sha256"]
        manifest = row["source_manifest"]
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha) or not manifest:
            fail("missing_or_invalid_provenance", key)
        provenance[(sha, manifest)] += 1
        validity[row["validity_class"]] += 1
        if row["validity_class"] not in {"valid", "silent", "near_silent", "clipped", "unstable"}:
            fail("unknown_validity", key)
        if row["validity_class"] == "valid":
            group = "benchmark" if row["benchmark_holdout"] else row["split"]
            if group in coverage:
                coverage[group][row["algorithm"]] += 1

    for key, row in by_key.items():
        root = by_key.get(row["lineage_root_key"])
        parent_key = row["parent_key"]
        if root is None:
            fail("missing_root", key)
        elif root["parent_key"] is not None or root["lineage_root_key"] != root["key"]:
            fail("invalid_root", key)
        if parent_key is None:
            if row["lineage_root_key"] != key:
                fail("independent_root_mismatch", key)
        else:
            parent = by_key.get(parent_key)
            if parent is None:
                fail("missing_parent", key)
            elif any(parent[field] != row[field] for field in
                     ("lineage_root_key", "split", "benchmark_holdout")):
                fail("parent_family_mismatch", key)
        # Follow the actual ancestry, not merely its claimed root.
        seen = {key}
        cursor = parent_key
        while cursor in by_key:
            if cursor in seen:
                fail("lineage_cycle", key)
                break
            seen.add(cursor)
            cursor = by_key[cursor]["parent_key"]

    if len(provenance) != 1:
        fail("incoherent_provenance", "corpus")
    for split in ("train", "validation", "test"):
        if not coverage[split]:
            fail(f"empty_valid_{split}", "corpus")
    return {
        "path": str(path), "files": len(files), "rows": len(rows),
        "ready_for_loader": not errors, "errors": dict(errors), "examples": examples,
        "validity": dict(validity),
        "valid_coverage": {split: {"rows": sum(counts.values()),
                                   "by_algorithm": dict(sorted(counts.items())),
                                   "missing_algorithms": sorted(set(range(1, 33)) - counts.keys())}
                           for split, counts in coverage.items()},
        "provenance": [{"binary_sha256": sha, "source_manifest": manifest, "rows": count}
                       for (sha, manifest), count in provenance.items()],
        "limitations": ["Metadata only: canonical label contents are not checked.",
                        "Source manifest is a recorded identifier, not verified source content.",
                        "Benchmark grouping is lineage-based, not a topology-disjoint holdout."],
    }


class ForwardDataset(Dataset):
    """Validated, in-memory canonical labels with explicit protected access.

    Algorithm IDs remain 1-based categorical IDs, not normalized scalars.
    Operators retain canonical OP1..OP6 ordering and raw legal parameters;
    encoding and topology features belong to the model, not the dataset.
    Load from a quiescent corpus: concurrent collection/replacement is not
    supported. Labels are held in RAM; max_rows bounds the retained subset,
    while the prerequisite metadata audit always covers the whole corpus.
    """

    def __init__(self, path: str | Path, split: str = "train", *,
                 allow_protected: bool = False, max_rows: int | None = None):
        if split not in {"train", "validation", "test", "benchmark"}:
            raise ValueError(f"Unknown forward split: {split}")
        if split in {"test", "benchmark"} and not allow_protected:
            raise ValueError("Protected labels require allow_protected=True")
        if max_rows is not None and (type(max_rows) is not int or max_rows <= 0):
            raise ValueError("max_rows must be a positive integer")
        self.audit = audit_forward_corpus(path)
        if not self.audit["ready_for_loader"]:
            raise ValueError(f"Corpus audit failed: {self.audit['errors']}")
        path = Path(path)
        files = sorted(path.glob("shard_*.parquet")) if path.is_dir() else [path]
        source = ds.dataset([str(file) for file in files], format="parquet")
        selection = ds.field("validity_class") == "valid"
        if split == "benchmark":
            selection = selection & (ds.field("benchmark_holdout") == True)
        else:
            selection = selection & (ds.field("benchmark_holdout") == False) & (ds.field("split") == split)
        scanner = source.scanner(columns=["key", "patch_json", "lineage_root_key",
                                           "algorithm_topology_signature", "canonical_frames_json"],
                                 filter=selection, batch_size=128)
        self.items = []
        self.split = split
        for batch in scanner.to_batches():
            for row in batch.to_pylist():
                try:
                    frames = json.loads(row["canonical_frames_json"])
                    if set(frames) != {"45", "57", "69"}:
                        raise ValueError("Expected exactly notes 45/57/69")
                    samples = []
                    for note in (45, 57, 69):
                        frame = frames[str(note)]
                        for field, expected in {"version": FEATURE_VERSION, "note_midi": note,
                                                "sample_rate": 48000, "frame_length": 2048}.items():
                            if frame[field] != expected:
                                raise ValueError(f"Invalid frame {field}")
                        values = frame["samples"]
                        if (not isinstance(values, list) or len(values) != 2048 or
                                any(type(v) not in (int, float) for v in values)):
                            raise ValueError("Expected 2048 numeric samples")
                        samples.append(values)
                    waveform = torch.tensor(samples, dtype=torch.float32)
                    if waveform.shape != (3, 2048) or not torch.isfinite(waveform).all():
                        raise ValueError("Invalid or nonfinite canonical waveform")
                except (ValueError, TypeError, KeyError, RuntimeError, OverflowError) as exc:
                    raise ValueError(f"Invalid canonical labels for {row['key']}: {exc}") from exc
                patch = validate_patch(json.loads(row["patch_json"]))
                self.items.append({
                    "key": row["key"], "lineage_root_key": row["lineage_root_key"],
                    "topology_signature": row["algorithm_topology_signature"],
                    "algorithm": torch.tensor(patch.algorithm, dtype=torch.long),
                    "feedback": torch.tensor(patch.feedback, dtype=torch.long),
                    "operators": torch.tensor([[getattr(op, field) for field in
                                                ("coarse", "fine", "detune", "mode", "level")]
                                               for op in patch.operators], dtype=torch.long),
                    "waveform": waveform,
                })
                if max_rows is not None and len(self.items) >= max_rows:
                    return
        if not self.items:
            raise ValueError(f"No valid observations in split {split}")

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> dict:
        return {key: value.clone() if isinstance(value, torch.Tensor) else value
                for key, value in self.items[index].items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    args = parser.parse_args()
    report = audit_forward_corpus(args.corpus)
    print(json.dumps(report, indent=2))
    return 0 if report["ready_for_loader"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
