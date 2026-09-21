import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch
from torch.utils.data import DataLoader

from dexfrag.algorithms import topology_for
from dexfrag.features import FEATURE_VERSION
from dexfrag.forward_data import ForwardDataset, REFERENCE, audit_forward_corpus
from dexfrag.patch import blank_patch, patch_key
from dexfrag.splits import SPLIT_SCHEME_VERSION, assign_split, benchmark_holdout
from dexfrag.storage import NATIVE_OBSERVATION_SCHEMA, OBSERVATION_SCHEMA_VERSION


@pytest.fixture
def rows():
    groups = {}
    for i in range(1000):
        patch = blank_patch().to_dict()
        patch["algorithm"] = i % 32 + 1
        patch["operators"][0]["fine"] = i // 32
        key = patch_key(patch)
        split = assign_split(key)
        held = benchmark_holdout(key)
        group = "benchmark" if held else split
        if group in groups:
            continue
        groups[group] = {
            "schema_version": OBSERVATION_SCHEMA_VERSION, "key": key,
            "patch_json": json.dumps(patch), "algorithm": patch["algorithm"], "feedback": 0,
            "algorithm_topology_signature": topology_for(patch["algorithm"]).topology_signature,
            **REFERENCE, "binary_sha256": "a" * 64, "source_manifest": "synthetic-manifest",
            "feature_version": FEATURE_VERSION, "acquisition_source": "broad_random",
            "parent_key": None, "lineage_root_key": key, "validity_class": "valid",
            "split": split, "benchmark_holdout": held, "split_scheme_version": SPLIT_SCHEME_VERSION,
            "created_at": 0.0, "waveforms_json": "RAW LABELS MUST NOT BE READ",
            "canonical_frames_json": json.dumps({str(note): {
                "version": FEATURE_VERSION, "note_midi": note, "sample_rate": 48000,
                "frame_length": 2048, "samples": [0.125] * 2048,
            } for note in (45, 57, 69)}),
        }
        if len(groups) == 4:
            return groups
    raise AssertionError("Could not construct all split groups")


def write(path, rows):
    pq.write_table(pa.Table.from_pylist(list(rows), schema=NATIVE_OBSERVATION_SCHEMA), path)
    return path


def test_audit_and_loader(tmp_path, rows):
    path = write(tmp_path / "data.parquet", rows.values())
    report = audit_forward_corpus(path)
    assert report["ready_for_loader"]
    assert report["rows"] == 4
    for split in ("train", "validation"):
        data = ForwardDataset(path, split)
        assert len(data) == 1
        assert data[0]["key"] == rows[split]["key"]
        batch = next(iter(DataLoader(data, batch_size=2)))
        assert batch["waveform"].shape == (1, 3, 2048)
        assert batch["operators"].shape == (1, 6, 5)
        assert batch["algorithm"].dtype == torch.long
        assert torch.all(batch["waveform"] == 0.125)  # no amplitude normalization
        data[0]["waveform"].zero_()
        assert torch.all(data[0]["waveform"] == 0.125)


@pytest.mark.parametrize("split", ["test", "benchmark"])
def test_protected_access(tmp_path, rows, split):
    with pytest.raises(ValueError, match="Protected"):
        ForwardDataset(tmp_path / "missing", split)
    path = write(tmp_path / "data.parquet", rows.values())
    assert ForwardDataset(path, split, allow_protected=True)[0]["key"] == rows[split]["key"]


@pytest.mark.parametrize("field,value,error", [
    ("key", "f" * 310, "identity_mismatch"),
    ("sample_rate", 44100, "unexpected_sample_rate"),
    ("feature_version", "old", "unexpected_feature_version"),
    ("binary_sha256", "b" * 64, "incoherent_provenance"),
    ("source_manifest", "", "missing_or_invalid_provenance"),
    ("split", "test", "split_mismatch"),
    ("benchmark_holdout", True, "benchmark_mismatch"),
    ("parent_key", "f" * 310, "missing_parent"),
    ("lineage_root_key", "f" * 310, "missing_root"),
])
def test_audit_rejects_corruption(tmp_path, rows, field, value, error):
    rows["train"][field] = value
    path = write(tmp_path / "data.parquet", rows.values())
    assert error in audit_forward_corpus(path)["errors"]
    with pytest.raises(ValueError, match="audit failed"):
        ForwardDataset(path)


def test_duplicate_and_cycle(tmp_path, rows):
    rows["train"]["parent_key"] = rows["train"]["key"]
    path = write(tmp_path / "data.parquet", [*rows.values(), rows["train"]])
    errors = audit_forward_corpus(path)["errors"]
    assert "duplicate_key" in errors
    assert "lineage_cycle" in errors


def test_protected_labels_not_decoded(tmp_path, rows):
    rows["test"]["canonical_frames_json"] = "invalid JSON"
    rows["benchmark"]["canonical_frames_json"] = "invalid JSON"
    path = write(tmp_path / "data.parquet", rows.values())
    assert len(ForwardDataset(path)) == 1
    with pytest.raises(ValueError, match="Invalid canonical labels"):
        ForwardDataset(path, "test", allow_protected=True)


@pytest.mark.parametrize("samples", [[float("nan")] * 2048, [1.0], [True] * 2048])
def test_bad_labels(tmp_path, rows, samples):
    frames = json.loads(rows["train"]["canonical_frames_json"])
    frames["45"]["samples"] = samples
    rows["train"]["canonical_frames_json"] = json.dumps(frames)
    path = write(tmp_path / "data.parquet", rows.values())
    with pytest.raises(ValueError, match="Invalid canonical labels"):
        ForwardDataset(path)


def test_shards_and_row_bound(tmp_path, rows):
    write(tmp_path / "shard_00000.parquet", rows.values())
    (tmp_path / "keys_index.json").write_text("not consulted", encoding="utf-8")
    assert len(ForwardDataset(tmp_path, max_rows=1)) == 1
    with pytest.raises(ValueError, match="positive integer"):
        ForwardDataset(tmp_path, max_rows=0)


def test_missing_and_wrong_schema(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        audit_forward_corpus(tmp_path / "absent")
    path = tmp_path / "bad.parquet"
    pq.write_table(pa.table({"key": ["bad"]}), path)
    assert "incompatible_schema" in audit_forward_corpus(path)["errors"]


def test_invalid_observations_excluded(tmp_path, rows):
    # A legal descendant in the training family, but not a clean periodic label.
    child = dict(rows["train"])
    patch = json.loads(child["patch_json"])
    patch["feedback"] = 1
    child.update(key=patch_key(patch), patch_json=json.dumps(patch), feedback=1,
                 parent_key=rows["train"]["key"], validity_class="unstable",
                 canonical_frames_json="must not decode this")
    path = write(tmp_path / "data.parquet", [*rows.values(), child])
    assert audit_forward_corpus(path)["ready_for_loader"]
    assert len(ForwardDataset(path)) == 1


def test_frame_reference_and_parent_family(tmp_path, rows):
    frames = json.loads(rows["train"]["canonical_frames_json"])
    frames["45"]["note_midi"] = 57
    rows["train"]["canonical_frames_json"] = json.dumps(frames)
    path = write(tmp_path / "data.parquet", rows.values())
    with pytest.raises(ValueError, match="Invalid frame note_midi"):
        ForwardDataset(path)
    rows["train"]["parent_key"] = rows["validation"]["key"]
    write(path, rows.values())
    assert "parent_family_mismatch" in audit_forward_corpus(path)["errors"]
