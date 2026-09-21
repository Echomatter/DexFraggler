"""Phase-bearing forward losses and deterministic candidate-ranking diagnostics.

Waveforms use note order 45, 57, 69 and retain native amplitude and phase.
Ranking callers must supply held-out targets, protect test/benchmark splits,
and exclude self-matches. These metrics alone do not establish generalization.
"""
from __future__ import annotations

import torch

SCORER_VERSION = "dexfrag-forward-waveform-mse-v1"


def _validate(value: torch.Tensor, name: str) -> None:
    if not isinstance(value, torch.Tensor) or not value.is_floating_point():
        raise ValueError(f"{name} must be a floating-point tensor")
    if value.ndim != 3 or tuple(value.shape[1:]) != (3, 2048) or not len(value):
        raise ValueError(f"{name} must have nonempty shape [B, 3, 2048]")
    if not torch.isfinite(value).all():
        raise ValueError(f"{name} contains nonfinite values")


def forward_loss(prediction: torch.Tensor, target: torch.Tensor) -> dict[str, torch.Tensor]:
    """Equal-pitch mean losses; total = waveform + complex FFT + correlation.

    FFT uses orthonormal normalization and both signed-frequency halves.
    Its MSE equals waveform MSE by Parseval; it is reported separately for
    transparency, not claimed as an independent source of information.
    Correlation is centered cosine similarity. Constant pairs have zero
    correlation penalty; amplitude/DC errors remain covered by the MSEs.
    """
    _validate(prediction, "prediction")
    _validate(target, "target")
    if prediction.shape != target.shape or prediction.device != target.device:
        raise ValueError("prediction and target must have matching shape and device")
    # FFT and tiny denominators are more reliable in float32 than half precision.
    dtype = torch.promote_types(prediction.dtype, target.dtype)
    if dtype in (torch.float16, torch.bfloat16):
        dtype = torch.float32
    prediction, target = prediction.to(dtype), target.to(dtype)
    residual = prediction - target
    waveform = residual.square().mean()
    harmonic = torch.fft.fft(residual, dim=-1, norm="ortho").abs().square().mean()
    p = prediction - prediction.mean(dim=-1, keepdim=True)
    t = target - target.mean(dim=-1, keepdim=True)
    eps = torch.finfo(dtype).eps
    pe, te = p.square().mean(-1), t.square().mean(-1)
    denominator = (pe.clamp_min(eps) * te.clamp_min(eps)).sqrt()
    similarity = ((p * t).mean(-1) / denominator).clamp(-1, 1)
    both_constant = (pe <= eps) & (te <= eps)
    correlation = torch.where(both_constant, torch.zeros_like(similarity), 1 - similarity).mean()
    return {"loss": waveform + harmonic + correlation,
            "waveform_mse": waveform, "complex_harmonic_mse": harmonic,
            "correlation_loss": correlation}


@torch.no_grad()
def ranking_metrics(targets: torch.Tensor, native_candidates: torch.Tensor,
                    predicted_candidates: torch.Tensor) -> dict[str, float | int | str | None]:
    """Compare predicted and native MSE orderings for a shared candidate pool.

    Native exact ties are excluded from pairwise accuracy; predicted ties earn
    half credit. Top-1 ties choose the first candidate deterministically.
    Random regret is the exact expected regret of a uniform random choice,
    not a noisy Monte Carlo baseline. No comparable pairs yields None.
    Memory is bounded per target; pair comparisons cost O(targets*candidates²).
    """
    for name, value in (("targets", targets), ("native_candidates", native_candidates),
                        ("predicted_candidates", predicted_candidates)):
        _validate(value, name)
    if native_candidates.shape != predicted_candidates.shape:
        raise ValueError("native and predicted candidate shapes must match")
    if len({x.device for x in (targets, native_candidates, predicted_candidates)}) != 1:
        raise ValueError("all inputs must share a device")
    native, predicted = native_candidates.double(), predicted_candidates.double()
    credit = 0.0
    pairs = 0
    regret = random_regret = 0.0
    for target in targets.double():
        actual = (native - target).square().mean(dim=(1, 2))
        estimated = (predicted - target).square().mean(dim=(1, 2))
        best = actual.min()
        regret += (actual[estimated.argmin()] - best).item()
        random_regret += (actual.mean() - best).item()
        for i in range(len(actual) - 1):
            a = torch.sign(actual[i] - actual[i + 1:])
            p = torch.sign(estimated[i] - estimated[i + 1:])
            comparable = a != 0
            pairs += comparable.sum().item()
            credit += ((a == p) & comparable).sum().item()
            credit += 0.5 * ((p == 0) & comparable).sum().item()
    return {"scorer_version": SCORER_VERSION, "target_count": len(targets),
            "candidate_count": len(native), "comparable_pairs": pairs,
            "pairwise_accuracy": credit / pairs if pairs else None,
            "top1_regret": regret / len(targets),
            "random_expected_regret": random_regret / len(targets)}
