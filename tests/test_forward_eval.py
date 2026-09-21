"""Focused Phase 3 evaluate-forward tests (test/benchmark only, synthetic corpus)."""
import json

import pyarrow as pa
import pyarrow.parquet as pq
import torch

from dexfrag.algorithms import topology_for
from dexfrag.features import FEATURE_VERSION
from dexfrag.forward_data import REFERENCE
from dexfrag.forward_eval import (
    DEFAULT_MAX_CANDIDATES_PER_TARGET,
    EVAL_SPLITS,
    MAX_CANDIDATES_PER_TARGET,
    evaluate_forward,
    evaluate_grouped,
    evaluate_ranking,
    load_eval_dataset,
)
from dexfrag.forward_model import ForwardModel
from dexfrag.forward_training import save_checkpoint
from dexfrag.patch import blank_patch, patch_key
from dexfrag.splits import SPLIT_SCHEME_VERSION, assign_split, benchmark_holdout
from dexfrag.storage import NATIVE_OBSERVATION_SCHEMA, OBSERVATION_SCHEMA_VERSION


def _row(patch, level):
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


def _build_corpus(path, n_test=6, n_bench=2):
    wanted = {"train": 2, "validation": 2, "test": n_test, "benchmark": n_bench}
    found = {name: [] for name in wanted}
    i = 0
    while any(len(found[n]) < wanted[n] for n in wanted):
        patch = blank_patch().to_dict()
        patch["algorithm"] = i % 32 + 1
        patch["operators"][0]["fine"] = i // 32
        patch["operators"][1]["level"] = (i * 7) % 100
        row = _row(patch, (i * 7) % 100)
        group = "benchmark" if row["benchmark_holdout"] else row["split"]
        if group in wanted and len(found[group]) < wanted[group]:
            found[group].append(row)
        i += 1
        if i > 60000:
            raise AssertionError("could not sample required split groups")
    rows = [r for group in found.values() for r in group]
    target = path / "data.parquet" if path.is_dir() else path
    pq.write_table(pa.Table.from_pylist(rows, schema=NATIVE_OBSERVATION_SCHEMA), target)
    return target


def test_eval_splits_only(tmp_path):
    corpus = _build_corpus(tmp_path)
    assert set(EVAL_SPLITS) == {"test", "benchmark"}
    assert "train" not in EVAL_SPLITS and "validation" not in EVAL_SPLITS
    data = load_eval_dataset(corpus, "test")
    assert len(data) >= 2
    bench = load_eval_dataset(corpus, "benchmark")
    assert len(bench) >= 1
    for bad in ("train", "validation"):
        try:
            load_eval_dataset(corpus, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"non-eval split {bad} must be refused")


def test_grouped_metrics_structure(tmp_path):
    corpus = _build_corpus(tmp_path)
    data = load_eval_dataset(corpus, "test")
    grouped = evaluate_grouped(ForwardModel(), data, "cpu", batch_size=2)
    assert grouped["split"] == "test"
    assert grouped["count"] == len(data)
    assert set(grouped["overall"]) == {"loss", "waveform_mse", "complex_harmonic_mse", "correlation_loss"}
    assert all(v >= 0 for v in grouped["overall"].values())
    assert sum(v["count"] for v in grouped["by_algorithm"].values()) == len(data)
    assert sum(v["count"] for v in grouped["by_topology_signature"].values()) == len(data)
    # Per-algorithm means lie within the pooled overall range sanity check.
    losses = [v["loss"] for v in grouped["by_algorithm"].values()]
    assert min(losses) <= grouped["overall"]["loss"] <= max(losses)


def test_ranking_excludes_self_and_bounds_pool(tmp_path):
    corpus = _build_corpus(tmp_path, n_test=6)
    data = load_eval_dataset(corpus, "test")
    result = evaluate_ranking(ForwardModel(), data, "cpu", max_targets=3, max_candidates=2, seed=0)
    assert result["self_matches_excluded"] is True
    assert result["candidate_count"] <= 2
    assert result["target_count"] <= 3
    assert result["candidate_pool_bound"] == MAX_CANDIDATES_PER_TARGET
    assert "pairwise_accuracy" in result and "top1_regret" in result
    assert "random_expected_regret" in result
    # Deterministic under the same seed.
    again = evaluate_ranking(ForwardModel(), data, "cpu", max_targets=3, max_candidates=2, seed=0)
    assert again["target_count"] == result["target_count"]
    # Pool bound is enforced even when more rows exist.
    big = evaluate_ranking(
        ForwardModel(), data, "cpu", max_targets=10,
        max_candidates=DEFAULT_MAX_CANDIDATES_PER_TARGET + 1000, seed=1,
    )
    assert big["candidate_count"] <= MAX_CANDIDATES_PER_TARGET


def test_evaluate_forward_end_to_end(tmp_path):
    corpus = _build_corpus(tmp_path)
    model = ForwardModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    checkpoint = tmp_path / "model.pt"
    save_checkpoint(checkpoint, model, optimizer, epoch=0, global_step=1, best_val=1.0)
    summary = evaluate_forward(corpus, checkpoint, device="cpu", max_targets=2, max_candidates=2, seed=0)
    assert summary["split"] == "test"
    assert summary["by_algorithm"] and summary["overall"]
    assert summary["ranking"]["candidate_count"] <= 2
    assert json.dumps(summary)  # JSON-serializable for the CLI
