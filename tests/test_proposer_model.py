import pytest
import torch

from dexfrag.algorithms import topology_for
from dexfrag.patch import blank_patch
from dexfrag.proposer_metrics import attach_training_targets, proposer_loss
from dexfrag.proposer_model import (
    MODEL_VERSION,
    ProposerModel,
    candidate_diversity,
    deduplicate_candidates,
    generate_candidates,
)


def _batch(size=3):
    algorithm = torch.tensor([(index % 32) + 1 for index in range(size)], dtype=torch.long)
    feedback = torch.tensor([index % 8 for index in range(size)], dtype=torch.long)
    operators = torch.zeros(size, 6, 5, dtype=torch.long)
    for batch_index in range(size):
        for op_index in range(6):
            operators[batch_index, op_index] = torch.tensor(
                [(batch_index + op_index) % 32, (batch_index * 7 + op_index) % 100,
                 (batch_index + op_index) % 15, (batch_index + op_index) % 2,
                 (batch_index * 13 + op_index) % 100], dtype=torch.long
            )
    waveform = torch.randn(size, 3, 2048) * 0.1
    return waveform, algorithm, feedback, operators


def test_model_version_and_distribution_shapes():
    waveform, algorithm, feedback, operators = _batch()
    model = ProposerModel(hidden_dim=16, harmonic_bands=8, conv_channels=4, algorithm_dim=4)
    outputs = model(waveform, algorithm)
    assert MODEL_VERSION == "dexfrag-inverse-proposer-v2"
    assert outputs["algorithm_logits"].shape == (3, 32)
    assert outputs["parameter_logits"]["feedback"].shape == (3, 8)
    assert outputs["parameter_logits"]["op_0_coarse"].shape == (3, 32)
    assert outputs["parameter_logits"]["op_5_level"].shape == (3, 100)
    labeled = attach_training_targets(outputs, algorithm=algorithm, feedback=feedback, operators=operators)
    losses = proposer_loss(labeled)
    assert losses["loss"].item() > 0
    assert all(torch.isfinite(value) for value in losses.values())
    unconditioned = model(waveform)
    assert unconditioned["parameter_logits"]["feedback"].shape == (3, 32, 8)
    unconditioned_labeled = attach_training_targets(
        unconditioned, algorithm=algorithm, feedback=feedback, operators=operators
    )
    unconditioned_losses = proposer_loss(unconditioned_labeled)
    assert torch.isfinite(unconditioned_losses["loss"])
    losses["loss"].backward()
    assert any(parameter.grad is not None for parameter in model.parameters())
    boundary = model(torch.randn(1, 3, 2048), torch.tensor([32], dtype=torch.long))
    boundary_labeled = attach_training_targets(
        boundary, algorithm=torch.tensor([32], dtype=torch.long),
        feedback=torch.tensor([7], dtype=torch.long),
        operators=operators[:1],
    )
    assert torch.isfinite(proposer_loss(boundary_labeled)["loss"])


def test_candidate_generation_is_legal_diverse_and_seeded():
    model = ProposerModel(hidden_dim=16, harmonic_bands=8, conv_channels=4, algorithm_dim=4)
    waveform, _, _, _ = _batch(1)
    first = generate_candidates(model, waveform[0], count=16, seed=11)
    second = generate_candidates(model, waveform[0], count=16, seed=11)
    assert first == second
    assert len(first) == 16
    assert all(candidate.algorithm in range(1, 33) for candidate in first)
    assert all(candidate.feedback in range(0, 8) for candidate in first)
    metrics = candidate_diversity(first)
    assert metrics["legal_rate"] == 1.0
    assert metrics["unique_rate"] > 0.0
    assert len(deduplicate_candidates(first)) == metrics["unique_count"]
    assert all(topology_for(candidate.algorithm).number == candidate.algorithm for candidate in first)


def test_model_rejects_bad_shapes_and_ranges():
    model = ProposerModel(hidden_dim=16, harmonic_bands=8, conv_channels=4, algorithm_dim=4)
    with pytest.raises(ValueError):
        model(torch.randn(2048), torch.tensor([1], dtype=torch.long))
    waveform, algorithm, _, _ = _batch(1)
    with pytest.raises(ValueError):
        model(waveform, torch.tensor([0], dtype=torch.long))
    with pytest.raises(ValueError):
        model(waveform[:1], torch.tensor([1, 2], dtype=torch.long))


def test_proposer_loss_rejects_non_smoothing():
    _, algorithm, feedback, operators = _batch(2)
    model = ProposerModel(hidden_dim=16, harmonic_bands=8, conv_channels=4, algorithm_dim=4)
    outputs = model(torch.randn(2, 3, 2048), algorithm)
    labeled = attach_training_targets(outputs, algorithm=algorithm, feedback=feedback, operators=operators)
    with pytest.raises(ValueError):
        proposer_loss(labeled, label_smoothing=1.0)


def test_smoothed_conditional_loss_is_bounded_below():
    """Label smoothing must penalise over-confidence, never reward it.

    The v2 smoothing term entered the negated expression already negated, so
    the objective went to -inf as logits grew: training diverged (loss reached
    -1.98e17) and candidates collapsed onto a handful of near-identical patches.
    """
    from dexfrag.proposer_metrics import _conditional_cross_entropy

    batch, algorithms, classes = 4, 32, 8
    # Maximally confident about the correct answer: p(target) ~ 1.
    confident_algorithm = torch.full((batch, algorithms), -40.0)
    confident_parameters = torch.full((batch, algorithms, classes), -40.0)
    for row in range(batch):
        confident_algorithm[row, row] = 40.0
        confident_parameters[row, row, 0] = 40.0
    # No information at all: every class equally likely.
    flat_algorithm = torch.zeros(batch, algorithms)
    flat_parameters = torch.zeros(batch, algorithms, classes)
    target = torch.zeros(batch, dtype=torch.long)

    for smoothing in (0.05, 0.1, 0.5):
        confident = _conditional_cross_entropy(
            confident_parameters, confident_algorithm, target, smoothing
        )
        uninformative = _conditional_cross_entropy(
            flat_parameters, flat_algorithm, target, smoothing
        )
        assert confident.item() >= 0.0
        assert uninformative.item() >= 0.0
        # Over-confidence is punished: the flat model must not look worse.
        assert confident.item() > uninformative.item()

    # Weights far beyond anything a healthy run reaches must stay finite and
    # positive, i.e. the objective has a floor instead of an escape hatch.
    extreme = _conditional_cross_entropy(
        torch.full((batch, algorithms, classes), -500.0).index_fill(2, torch.tensor([0]), 500.0),
        torch.full((batch, algorithms), -500.0).fill_diagonal_(500.0),
        target, 0.05,
    )
    assert torch.isfinite(extreme) and extreme.item() >= 0.0


def test_unconditioned_training_path_reports_nonnegative_loss():
    _, algorithm, feedback, operators = _batch(3)
    model = ProposerModel(hidden_dim=16, harmonic_bands=8, conv_channels=4, algorithm_dim=4)
    outputs = model(torch.randn(3, 3, 2048))
    assert outputs["parameter_logits"]["feedback"].ndim == 3
    labeled = attach_training_targets(
        outputs, algorithm=algorithm, feedback=feedback, operators=operators
    )
    for smoothing in (0.0, 0.05):
        losses = proposer_loss(labeled, label_smoothing=smoothing)
        assert losses["loss"].item() >= 0.0, smoothing
        assert all(torch.isfinite(value) for value in losses.values())
