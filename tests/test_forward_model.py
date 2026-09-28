"""Focused Phase 3 forward-model core tests: encoding, shape/finiteness, loss smoke."""
import pytest
import torch

from dexfrag.algorithms import topology_for
from dexfrag.features import canonical_frame
from dexfrag.forward_metrics import forward_loss
from dexfrag.forward_model import (
    FRAME_LENGTH,
    MAX_BANDS,
    NOTE_BANDS,
    NOTE_MIDIS,
    ForwardModel,
    MODEL_VERSION,
    encode_conditioning,
    normalize_feedback,
    normalize_operators,
    note_bands,
    synthesize_frames,
    topology_features,
)


def make_batch(size=4):
    algorithms = torch.tensor([(i % 32) + 1 for i in range(size)], dtype=torch.long)
    feedback = torch.tensor([i % 8 for i in range(size)], dtype=torch.long)
    operators = torch.zeros(size, 6, 5, dtype=torch.long)
    for b in range(size):
        for op in range(6):
            operators[b, op] = torch.tensor(
                [(b + op) % 32, (b * 7 + op) % 100, (b + op) % 15, (b + op) % 2, (b * 13 + op) % 100],
                dtype=torch.long,
            )
    signatures = [topology_for(int(a)).topology_signature for a in algorithms.tolist()]
    waveform = torch.randn(size, 3, 2048, dtype=torch.float32) * 0.1
    return {
        "algorithm": algorithms, "feedback": feedback, "operators": operators,
        "topology_signature": signatures, "waveform": waveform,
    }


def test_model_version_pinned():
    assert MODEL_VERSION == "dexfrag-forward-mlp-v2"


def test_normalization_ranges_and_determinism():
    batch = make_batch(4)
    fb = normalize_feedback(batch["feedback"])
    assert fb.shape == (4, 1) and fb.dtype == torch.float32
    assert bool(((fb >= 0) & (fb <= 1)).all())
    assert fb[0].item() == pytest.approx(0.0)  # feedback 0 -> 0
    assert normalize_feedback(torch.tensor([7], dtype=torch.long)).item() == pytest.approx(1.0)
    ops = normalize_operators(batch["operators"])
    assert ops.shape == (4, 6, 5) and bool(((ops >= 0) & (ops <= 1)).all())
    cond_a = encode_conditioning(batch["feedback"], batch["operators"], batch["topology_signature"])
    cond_b = encode_conditioning(batch["feedback"], batch["operators"], list(batch["topology_signature"]))
    assert cond_a.shape == (4, 39)
    assert torch.equal(cond_a, cond_b)  # deterministic input encoding
    assert torch.isfinite(cond_a).all()


def test_topology_features_deterministic():
    sigs = [topology_for(1).topology_signature, topology_for(2).topology_signature]
    first = topology_features(sigs)
    second = topology_features(list(sigs))
    assert first.shape == (2, 8)
    assert torch.equal(first, second)
    assert bool(((first >= 0) & (first <= 1)).all())
    assert not torch.equal(first[0], first[1])
    with pytest.raises(ValueError):
        topology_features([])
    with pytest.raises(ValueError):
        topology_features([""])


def test_forward_shape_finite_and_eval_deterministic():
    batch = make_batch(3)
    model = ForwardModel()
    model.eval()
    with torch.no_grad():
        out_a = model(batch["algorithm"], batch["feedback"], batch["operators"],
                      batch["topology_signature"])
        out_b = model.forward_batch(batch)
    assert out_a.shape == (3, 3, 2048)
    assert torch.isfinite(out_a).all()
    assert torch.equal(out_a, out_b)
    # Single-row batch also yields [1, 3, 2048].
    single = {k: (v[:1] if isinstance(v, torch.Tensor) else v[:1]) for k, v in make_batch(2).items()}
    assert model.forward_batch(single).shape == (1, 3, 2048)


def test_forward_loss_smoke_and_gradients():
    torch.manual_seed(0)
    batch = make_batch(2)
    model = ForwardModel(hidden_dims=(64, 64), algorithm_dim=8)
    pred = model.forward_batch(batch)
    result = forward_loss(pred, batch["waveform"])
    assert set(result) == {"loss", "waveform_mse", "complex_harmonic_mse", "correlation_loss"}
    assert all(torch.isfinite(v).all() for v in result.values())
    assert result["loss"].item() >= 0
    result["loss"].backward()
    grads = [p.grad for p in model.parameters() if p.grad is not None]
    assert grads and all(torch.isfinite(g).all() for g in grads)
    assert model.count_parameters() > 0


def test_algorithm_categorical_not_scalar():
    batch = make_batch(2)
    model = ForwardModel()
    # Boundary IDs are accepted; embedding separates them (not a scalar scale).
    model.forward_batch(batch)
    assert model.algorithm_embedding.weight.shape == (33, model.algorithm_dim)
    with pytest.raises(ValueError):
        model(batch["algorithm"] * 0, batch["feedback"], batch["operators"],
              batch["topology_signature"])  # id 0 illegal
    with pytest.raises(ValueError):
        model(batch["algorithm"], batch["feedback"], batch["operators"],
              batch["topology_signature"][:1])  # batch-size mismatch


@pytest.mark.parametrize("field", ["algorithm", "feedback", "operators", "topology_signature"])
def test_forward_batch_rejects_missing_fields(field):
    batch = make_batch(2)
    del batch[field]
    with pytest.raises(ValueError):
        ForwardModel().forward_batch(batch)


def test_illegal_numeric_ranges_rejected():
    batch = make_batch(1)
    bad_ops = batch["operators"].clone()
    bad_ops[0, 0, 0] = 32  # coarse max is 31
    with pytest.raises(ValueError):
        normalize_operators(bad_ops)
    with pytest.raises(ValueError):
        normalize_feedback(torch.tensor([8], dtype=torch.long))


def test_forward_output_device_matches_input():
    batch = make_batch(2)
    assert batch["algorithm"].device == torch.device("cpu")
    model = ForwardModel(hidden_dims=(32, 32), algorithm_dim=4)
    out = model.forward_batch(batch)
    assert out.device == batch["algorithm"].device
    # Encoding helpers preserve the input device.
    assert normalize_operators(batch["operators"]).device == batch["operators"].device
    assert normalize_feedback(batch["feedback"]).device == batch["feedback"].device


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA unavailable")
def test_forward_cuda_device_consistency():
    batch = make_batch(2)
    device = torch.device("cuda")
    model = ForwardModel(hidden_dims=(32, 32), algorithm_dim=4).to(device)
    cuda_batch = {
        key: (value.to(device) if isinstance(value, torch.Tensor) else value)
        for key, value in batch.items()
    }
    out = model.forward_batch(cuda_batch)
    assert out.device == device
    assert out.shape == (2, 3, 2048)
    assert torch.isfinite(out).all()


def test_note_bands_match_canonical_frame_contract():
    assert NOTE_MIDIS == (45, 57, 69)
    assert NOTE_BANDS == (217, 108, 53)
    assert MAX_BANDS == 217
    for note in NOTE_MIDIS:
        frame = canonical_frame([0.0] * 4096, note)
        assert frame.frame_length == FRAME_LENGTH
        assert frame.bands == note_bands(note)
    with pytest.raises(ValueError):
        note_bands(-1)
    with pytest.raises(ValueError):
        note_bands(128)


def test_synthesize_frames_inverts_canonical_frame():
    import math

    note = 69
    base = 440.0 * 2.0 ** ((note - 69) / 12.0)
    capture = [0.0] * 4096
    true_sin = [0.02 * ((k % 5) + 1) for k in range(1, 11)]
    true_cos = [0.015 * ((k % 3) + 1) for k in range(1, 11)]
    for i in range(4096):
        capture[i] = sum(
            true_sin[k] * math.sin(2.0 * math.pi * (k + 1) * base * i / 48000.0)
            + true_cos[k] * math.cos(2.0 * math.pi * (k + 1) * base * i / 48000.0)
            for k in range(10)
        )
    frame = canonical_frame(capture, note)
    assert frame.bands == NOTE_BANDS[2]
    sin_padded = torch.zeros(1, 3, MAX_BANDS, dtype=torch.float32)
    cos_padded = torch.zeros(1, 3, MAX_BANDS, dtype=torch.float32)
    sin_padded[0, 2, :frame.bands] = torch.tensor(frame.sin_coefficients, dtype=torch.float32)
    cos_padded[0, 2, :frame.bands] = torch.tensor(frame.cos_coefficients, dtype=torch.float32)
    rendered = synthesize_frames(sin_padded, cos_padded)
    assert rendered.shape == (1, 3, FRAME_LENGTH)
    expected = torch.tensor(frame.samples, dtype=torch.float32)
    assert torch.allclose(rendered[0, 2], expected, atol=1e-4, rtol=1e-3)
    # Zero coefficients synthesize exact silence on every note.
    silent = synthesize_frames(torch.zeros(2, 3, MAX_BANDS), torch.zeros(2, 3, MAX_BANDS))
    assert silent.shape == (2, 3, FRAME_LENGTH)
    assert bool((silent == 0).all())


def test_synthesize_frames_rejects_bad_inputs():
    good = torch.zeros(1, 3, MAX_BANDS)
    with pytest.raises(ValueError):
        synthesize_frames(torch.zeros(1, 3, MAX_BANDS - 1), good)
    with pytest.raises(ValueError):
        synthesize_frames(good, torch.zeros(1, 3, MAX_BANDS, dtype=torch.long))
    bad = torch.zeros(1, 3, MAX_BANDS)
    bad[0, 0, 0] = float("inf")
    with pytest.raises(ValueError):
        synthesize_frames(bad, good)
    with pytest.raises(ValueError):
        synthesize_frames(good, torch.zeros(2, 3, MAX_BANDS))


def test_harmonic_head_exactly_sized_and_smaller():
    model = ForwardModel()
    assert [head.out_features for head in model.coeff_heads] == [2 * b for b in NOTE_BANDS]
    assert model.count_parameters() == 679684
    assert model.count_parameters() < 1659664  # v1 raw-sample head size
