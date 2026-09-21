import pytest
import torch

from dexfrag.forward_metrics import forward_loss, ranking_metrics


def waves(values):
    return torch.tensor(values, dtype=torch.float32)[:, None, None].expand(-1, 3, 2048).clone()


def test_perfect_and_reversed_rankings():
    target, candidates = waves([0]), waves([1, 2, 3])
    perfect = ranking_metrics(target, candidates, candidates)
    assert perfect["pairwise_accuracy"] == 1
    assert perfect["top1_regret"] == 0
    assert perfect["random_expected_regret"] == pytest.approx(11 / 3)
    reversed_result = ranking_metrics(target, candidates, candidates.flip(0))
    assert reversed_result["pairwise_accuracy"] == 0
    assert reversed_result["top1_regret"] == 8


def test_ranking_ties_and_single_candidate():
    result = ranking_metrics(waves([0]), waves([1, 2]), waves([1, 1]))
    assert result["pairwise_accuracy"] == 0.5
    assert result["top1_regret"] == 0
    for candidates in (waves([1]), waves([1, 1])):
        result = ranking_metrics(waves([0]), candidates, candidates)
        assert result["comparable_pairs"] == 0
        assert result["pairwise_accuracy"] is None
        assert result["random_expected_regret"] == 0


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_constant_loss_and_gradients(value):
    prediction = waves([value]).requires_grad_()
    result = forward_loss(prediction, waves([value]))
    assert all(v.item() == 0 for v in result.values())
    result["loss"].backward()
    assert torch.isfinite(prediction.grad).all()


def test_phase_amplitude_and_pitch_balance():
    x = torch.arange(2048) * (2 * torch.pi / 2048)
    target = x.sin()[None, None, :].expand(1, 3, -1)
    prediction = (-target).clone().requires_grad_()
    result = forward_loss(prediction, target)
    assert result["waveform_mse"].item() == pytest.approx(2)
    assert result["complex_harmonic_mse"].item() == pytest.approx(2)
    assert result["correlation_loss"].item() == pytest.approx(2)
    result["loss"].backward()
    assert torch.isfinite(prediction.grad).all()
    one_pitch = waves([0])
    one_pitch[:, 0] = 1
    assert forward_loss(one_pitch, waves([0]))["waveform_mse"].item() == pytest.approx(1 / 3)
    assert forward_loss(2 * target, target)["waveform_mse"] > 0


@pytest.mark.parametrize("bad", [torch.zeros(0, 3, 2048), torch.zeros(1, 2048),
                                torch.zeros(1, 3, 2048, dtype=torch.long),
                                torch.full((1, 3, 2048), float("nan"))])
def test_invalid_inputs(bad):
    with pytest.raises(ValueError):
        forward_loss(bad, waves([0]))
    with pytest.raises(ValueError):
        ranking_metrics(bad, waves([0]), waves([0]))


def test_mismatched_shapes():
    with pytest.raises(ValueError):
        forward_loss(waves([0, 1]), waves([0]))
    with pytest.raises(ValueError):
        ranking_metrics(waves([0]), waves([1, 2]), waves([1]))
