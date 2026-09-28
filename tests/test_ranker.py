"""Focused Phase 3b ranker tests: towers, loss, coefficients, train/eval wiring."""
import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch

from dexfrag.forward_data import REFERENCE, ForwardDataset
from dexfrag.forward_model import NOTE_BANDS, NOTE_MIDIS, synthesize_frames
from dexfrag.ranker import (
    BEST_FILENAME,
    LAST_FILENAME,
    RANKER_VERSION,
    RankerModel,
    RankerTrainConfig,
    evaluate_ranker,
    frame_coefficients,
    load_checkpoint,
    native_distances,
    pairwise_accuracy,
    ranker_loss,
    save_checkpoint,
    smoke_ranker,
    train,
)
from dexfrag.storage import NATIVE_OBSERVATION_SCHEMA, OBSERVATION_SCHEMA_VERSION
from dexfrag.patch import blank_patch, patch_key
from dexfrag.splits import SPLIT_SCHEME_VERSION, assign_split, benchmark_holdout
from dexfrag.features import FEATURE_VERSION
from dexfrag.algorithms import topology_for


def _row(patch, row_index):
    key = patch_key(patch)
    phase = row_index * 0.7
    samples = [
        0.125 + 0.05 * math.sin(i / 50.0 + phase) + 0.02 * math.sin(i / 13.0 + phase * 2.0)
        for i in range(2048)
    ]
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
            "frame_length": 2048, "samples": samples,
        } for note in (45, 57, 69)}),
    }


def _build_corpus(path, n_train=4, n_val=4, n_test=4):
    wanted = {"train": n_train, "validation": n_val, "test": n_test}
    found = {name: 0 for name in wanted}
    rows = []
    i = 0
    while any(found[n] < wanted[n] for n in wanted):
        patch = blank_patch().to_dict()
        patch["algorithm"] = i % 32 + 1
        patch["operators"][0]["fine"] = i // 32
        patch["operators"][1]["level"] = (i * 7) % 100
        row = _row(patch, i)
        group = "benchmark" if row["benchmark_holdout"] else row["split"]
        if group in wanted and found[group] < wanted[group]:
            found[group] += 1
            rows.append(row)
        i += 1
        if i > 60000:
            raise AssertionError("could not sample required split groups")
    path = path / "data.parquet" if path.is_dir() else path
    pq.write_table(pa.Table.from_pylist(rows, schema=NATIVE_OBSERVATION_SCHEMA), path)
    return path


@pytest.fixture
def corpus(tmp_path):
    return _build_corpus(tmp_path)


def _patch_batch(size=4):
    algorithms = torch.tensor([(i % 32) + 1 for i in range(size)], dtype=torch.long)
    feedback = torch.tensor([i % 8 for i in range(size)], dtype=torch.long)
    operators = torch.zeros(size, 6, 5, dtype=torch.long)
    for b in range(size):
        for op in range(6):
            operators[b, op] = torch.tensor(
                [(b + op) % 32, (b * 7 + op) % 100, (b + op) % 15, (b + op) % 2, (b * 13 + op) % 100],
                dtype=torch.long,
            )
    from dexfrag.algorithms import topology_for

    signatures = [topology_for(int(a)).topology_signature for a in algorithms.tolist()]
    waveform = torch.randn(size, 3, 2048, dtype=torch.float32) * 0.1
    return algorithms, feedback, operators, signatures, waveform


def test_model_version_pinned():
    assert RANKER_VERSION == "dexfrag-ranker-v1"


def test_towers_shapes_normalized_and_small():
    model = RankerModel()
    algorithms, feedback, operators, signatures, waveform = _patch_batch(3)
    embeddings_p = model.embed_patches(algorithms, feedback, operators, signatures)
    coefficients = frame_coefficients(waveform)
    embeddings_w = model.embed_frames(coefficients)
    assert embeddings_p.shape == (3, model.embedding_dim)
    assert embeddings_w.shape == (3, model.embedding_dim)
    assert torch.isfinite(embeddings_p).all() and torch.isfinite(embeddings_w).all()
    assert torch.allclose(embeddings_p.square().sum(dim=1), torch.ones(3), atol=1e-4)
    assert model.count_parameters() < 500_000  # bounded: smaller than the v1 forward head alone


def test_frame_coefficients_invert_canonical_synthesis():
    generator = torch.Generator().manual_seed(0)
    sin_padded = torch.zeros(2, 3, max(NOTE_BANDS))
    cos_padded = torch.zeros(2, 3, max(NOTE_BANDS))
    for b in range(2):
        for n, bands in enumerate(NOTE_BANDS):
            sin_padded[b, n, :bands] = torch.randn(bands, generator=generator) * 0.02
            cos_padded[b, n, :bands] = torch.randn(bands, generator=generator) * 0.02
    waveform = synthesize_frames(sin_padded, cos_padded)
    recovered = frame_coefficients(waveform)
    assert recovered.shape == (2, 2 * sum(NOTE_BANDS))
    columns = []
    for n, bands in enumerate(NOTE_BANDS):
        columns.append(sin_padded[:, n, :bands])
        columns.append(cos_padded[:, n, :bands])
    expected = torch.cat(columns, dim=1)
    assert torch.allclose(recovered, expected, atol=1e-4, rtol=1e-3)
    with pytest.raises(ValueError):
        frame_coefficients(torch.zeros(2, 3, 1024))


def test_native_distances_match_brute_force():
    waveform = torch.randn(4, 3, 2048)
    dists = native_distances(waveform)
    assert dists.shape == (4, 4)
    assert torch.allclose(dists, dists.T, atol=1e-12)
    assert torch.allclose(dists.diag(), torch.zeros(4, dtype=torch.float64), atol=1e-12)
    for i in range(4):
        for j in range(4):
            expected = (waveform[i] - waveform[j]).square().mean().item()
            assert dists[i, j].item() == pytest.approx(expected, rel=1e-6)


def test_ranker_loss_finite_with_gradients_both_towers():
    algorithms, feedback, operators, signatures, waveform = _patch_batch(4)
    model = RankerModel()
    embeddings_p = model.embed_patches(algorithms, feedback, operators, signatures)
    embeddings_w = model.embed_frames(frame_coefficients(waveform))
    losses = ranker_loss(embeddings_p, embeddings_w, native_distances(waveform))
    assert set(losses) == {"loss", "listnet_loss", "alignment_loss", "temperature"}
    assert all(torch.isfinite(v).all() for v in losses.values())
    losses["loss"].backward()
    patch_grads = [p.grad for p in model.patch_tower.parameters() if p.grad is not None]
    wave_grads = [p.grad for p in model.wave_tower.parameters() if p.grad is not None]
    assert patch_grads and all(torch.isfinite(g).all() for g in patch_grads)
    assert wave_grads and all(torch.isfinite(g).all() for g in wave_grads)
    # ListNet term matches a manual softmax cross-entropy computation.
    native = native_distances(waveform)
    eye = torch.eye(len(embeddings_p), dtype=torch.bool)
    tau = native[~eye].median().clamp_min(1e-8)
    targets = torch.softmax(-native / tau, dim=1)
    predicted = torch.softmax(-torch.cdist(embeddings_p, embeddings_w) / tau, dim=1)
    manual = -(targets * predicted.clamp_min(1e-12).log()).sum(dim=1).mean()
    assert losses["listnet_loss"].item() == pytest.approx(manual.item(), rel=1e-6)
    assert losses["temperature"].item() == pytest.approx(tau.item(), rel=1e-6)


def test_pairwise_accuracy_sanity():
    native = native_distances(torch.randn(6, 3, 2048))
    assert pairwise_accuracy(native, native) == pytest.approx(1.0)
    assert pairwise_accuracy(native, -native) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        pairwise_accuracy(native, native[:4])


def _config(corpus, tmp_path, **overrides):
    args = {
        "corpus": corpus, "checkpoint_dir": tmp_path / "checkpoints",
        "seed": 0, "device": "cpu", "epochs": 1, "batch_size": 4,
        "learning_rate": 1e-3, "max_rows": None,
    }
    args.update(overrides)
    return RankerTrainConfig(**args)


def test_train_smoke_checkpoints_and_resume(corpus, tmp_path):
    config = _config(corpus, tmp_path, epochs=2)
    first = train(config)
    assert first["epochs_run"] == 2
    assert first["best_checkpoint"] and first["last_checkpoint"]
    assert first["best_val"] > 0.0  # pairwise accuracy in (0, 1]
    # Resume keeps the best as a running maximum (accuracy semantics).
    config2 = _config(corpus, tmp_path, epochs=5)
    second = train(config2)
    assert second["global_step"] >= first["global_step"]
    assert second["best_val"] >= first["best_val"] - 1e-9
    assert (tmp_path / "checkpoints" / BEST_FILENAME).exists()


def test_train_max_steps_bound(corpus, tmp_path):
    config = _config(corpus, tmp_path, epochs=10, max_steps=1)
    summary = train(config)
    assert summary["global_step"] == 1
    assert summary["epochs_run"] <= 1


def test_save_load_roundtrip(tmp_path):
    model = RankerModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    config = RankerTrainConfig(corpus=Path("unused"), checkpoint_dir=tmp_path)
    path = tmp_path / LAST_FILENAME
    save_checkpoint(path, model, optimizer, epoch=2, completed_epochs=3,
                    global_step=7, best_val=0.6)
    assert path.exists()
    assert not list(tmp_path.glob("*.tmp"))
    revived = RankerModel()
    state = load_checkpoint(path, revived)
    assert (state["epoch"], state["global_step"], state["best_val"]) == (2, 7, 0.6)
    assert state["completed_epochs"] == 3
    assert state["model_version"] == RANKER_VERSION
    for a, b in zip(model.parameters(), revived.parameters()):
        assert torch.equal(a, b)


def test_load_rejects_foreign_model_version(tmp_path):
    model = RankerModel()
    path = tmp_path / LAST_FILENAME
    save_checkpoint(path, model, None, epoch=0, completed_epochs=1,
                    global_step=1, best_val=0.5)
    payload = torch.load(path, map_location="cpu", weights_only=True)
    payload["model_version"] = "dexfrag-ranker-v0"
    torch.save(payload, path)
    with pytest.raises(ValueError):
        load_checkpoint(path, RankerModel())


def test_evaluate_ranker_deterministic_and_scored(corpus, tmp_path):
    config = _config(corpus, tmp_path, epochs=2)
    train(config)
    checkpoint = tmp_path / "checkpoints" / BEST_FILENAME
    first = evaluate_ranker(corpus, checkpoint, seed=0)
    second = evaluate_ranker(corpus, checkpoint, seed=0)
    assert first["pairwise_accuracy"] == pytest.approx(second["pairwise_accuracy"])
    assert first["top1_regret"] == pytest.approx(second["top1_regret"])
    for key in ("scorer_version", "target_count", "candidate_count", "comparable_pairs",
                "pairwise_accuracy", "top1_regret", "random_expected_regret", "split"):
        assert key in first
    assert first["scorer_version"] == "dexfrag-ranker-distance-v1"
    assert first["split"] == "test"
    assert first["self_matches_excluded"] is True
    assert 0.0 <= first["pairwise_accuracy"] <= 1.0
    assert first["top1_regret"] <= first["random_expected_regret"] + 1e-9


def test_smoke_ranker_wiring():
    result = smoke_ranker(device="cpu", steps=2, batch_size=2)
    assert result["ok"] and result["finite"] and result["params_updated"]
    assert result["restored_step"] == 2


def test_config_validation(corpus, tmp_path):
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, epochs=0)
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, batch_size=0)
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, max_steps=0)
    with pytest.raises(ValueError):
        _config(corpus, tmp_path, learning_rate=0.0)
    with pytest.raises(ValueError):
        RankerTrainConfig(corpus, tmp_path / "c", best_filename="x.pt", last_filename="x.pt")


def test_embed_patches_rejects_bad_ids():
    model = RankerModel()
    algorithms, feedback, operators, signatures, _ = _patch_batch(2)
    with pytest.raises(ValueError):
        model.embed_patches(algorithms * 0, feedback, operators, signatures)
    with pytest.raises(ValueError):
        model.embed_patches(algorithms, feedback, operators, signatures[:1])
