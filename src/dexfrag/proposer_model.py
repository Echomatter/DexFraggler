"""Compact Phase 4 waveform-to-distribution inverse proposer."""
from __future__ import annotations

import math

import torch
from torch import nn

from .algorithms import topology_for
from .patch import LIMITS, Operator, Patch, validate_patch

MODEL_VERSION = "dexfrag-inverse-proposer-v2"
FRAME_LENGTH = 2048
ALGORITHM_COUNT = 32
FEEDBACK_COUNT = 8
OPERATOR_FIELDS = ("coarse", "fine", "detune", "mode", "level")
OPERATOR_COUNTS = {
    "coarse": LIMITS["coarse"] + 1,
    "fine": LIMITS["fine"] + 1,
    "detune": LIMITS["detune"] + 1,
    "mode": LIMITS["mode"] + 1,
    "level": LIMITS["level"] + 1,
}


def _check_waveform(waveform: torch.Tensor) -> torch.Tensor:
    if not isinstance(waveform, torch.Tensor) or not waveform.is_floating_point():
        raise ValueError("waveform must be a floating-point tensor")
    if waveform.ndim not in (2, 3) or tuple(waveform.shape[-1:]) != (FRAME_LENGTH,):
        raise ValueError("waveform must have shape [N, 2048] or [B, N, 2048]")
    if not len(waveform) or not torch.isfinite(waveform).all():
        raise ValueError("waveform must be nonempty and finite")
    return waveform.float()


def _check_algorithm(algorithm: torch.Tensor) -> torch.Tensor:
    if not isinstance(algorithm, torch.Tensor) or algorithm.dtype != torch.long:
        raise ValueError("algorithm must be a torch.long tensor")
    if algorithm.ndim != 1 or not len(algorithm):
        raise ValueError("algorithm must have nonempty shape [B]")
    if bool((algorithm < 1).any() or (algorithm > ALGORITHM_COUNT).any()):
        raise ValueError("algorithm must contain integers from 1 to 32")
    return algorithm


class ProposerModel(nn.Module):
    """Waveform, harmonic, and statistics branches with distribution heads."""

    def __init__(self, *, algorithm_dim: int = 16, hidden_dim: int = 128,
                 harmonic_bands: int = 64, conv_channels: int = 32):
        super().__init__()
        if type(algorithm_dim) is not int or algorithm_dim <= 0:
            raise ValueError("algorithm_dim must be a positive integer")
        if type(hidden_dim) is not int or hidden_dim <= 0:
            raise ValueError("hidden_dim must be a positive integer")
        if type(harmonic_bands) is not int or not 1 <= harmonic_bands <= FRAME_LENGTH // 2 - 1:
            raise ValueError("harmonic_bands must be between 1 and 1023")
        if type(conv_channels) is not int or conv_channels <= 0:
            raise ValueError("conv_channels must be a positive integer")
        self.algorithm_dim = algorithm_dim
        self.hidden_dim = hidden_dim
        self.harmonic_bands = harmonic_bands
        self.conv_channels = conv_channels
        self.algorithm_embedding = nn.Embedding(ALGORITHM_COUNT + 1, algorithm_dim, padding_idx=0)
        self.waveform_encoder = nn.Sequential(
            nn.Conv1d(1, conv_channels, kernel_size=15, stride=4, padding=7),
            nn.ReLU(),
            nn.Conv1d(conv_channels, conv_channels * 2, kernel_size=9, stride=4, padding=4),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.frame_projection = nn.Sequential(
            nn.Linear(conv_channels * 2 + harmonic_bands * 2 + 6, hidden_dim),
            nn.ReLU(),
        )
        self.latent_projection = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
        )
        self.algorithm_head = nn.Linear(hidden_dim, ALGORITHM_COUNT)
        self.feedback_head = nn.Linear(hidden_dim, FEEDBACK_COUNT)
        self.parameter_trunk = nn.Sequential(
            nn.Linear(hidden_dim + algorithm_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )
        self.parameter_heads = nn.ModuleDict({
            f"op_{op_index}_{field}": nn.Linear(hidden_dim, OPERATOR_COUNTS[field])
            for op_index in range(6)
            for field in OPERATOR_FIELDS
        })

    def _frame_inputs(self, waveform: torch.Tensor) -> torch.Tensor:
        centered = waveform - waveform.mean(dim=-1, keepdim=True)
        scale = centered.square().mean(dim=-1, keepdim=True).sqrt().clamp_min(1e-6)
        spectrum = torch.fft.rfft(centered, dim=-1, norm="ortho")[..., 1:self.harmonic_bands + 1]
        normalized_spectrum = spectrum / scale
        harmonic = torch.view_as_real(normalized_spectrum).flatten(start_dim=-2)
        mean = centered.mean(dim=-1, keepdim=True)
        std = centered.std(dim=-1, unbiased=False, keepdim=True)
        rms = centered.square().mean(dim=-1, keepdim=True).sqrt()
        peak = centered.abs().amax(dim=-1, keepdim=True)
        abs_mean = centered.abs().mean(dim=-1, keepdim=True)
        sign = torch.sign(centered)
        crossings = (sign[..., 1:] != sign[..., :-1]).to(centered.dtype).mean(
            dim=-1, keepdim=True
        )
        statistics = torch.cat([mean, std, rms, peak, abs_mean, crossings], dim=-1)
        flat = waveform.reshape(-1, 1, FRAME_LENGTH)
        encoded = self.waveform_encoder(flat).flatten(start_dim=1)
        batch_frames = waveform.shape[0]
        frame_width = waveform.shape[1]
        encoded = encoded.reshape(batch_frames, frame_width, -1)
        return torch.cat([encoded, harmonic, statistics], dim=-1)

    def encode(self, waveform: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        waveform = _check_waveform(waveform)
        if waveform.ndim == 2:
            waveform = waveform.unsqueeze(0)
        frame_features = self._frame_inputs(waveform)
        frame_features = self.frame_projection(frame_features)
        pooled = torch.cat([frame_features.mean(dim=1), frame_features.amax(dim=1)], dim=-1)
        latent = self.latent_projection(pooled)
        return latent, self.algorithm_head(latent)

    def parameter_logits(self, latent: torch.Tensor,
                         algorithm: torch.Tensor | None = None) -> dict[str, torch.Tensor]:
        if latent.ndim != 2:
            raise ValueError("latent must have shape [B, hidden_dim]")
        if algorithm is None:
            algorithm_batch = torch.arange(
                1, ALGORITHM_COUNT + 1, dtype=torch.long, device=latent.device
            ).expand(latent.shape[0], -1)
            conditional = True
        else:
            algorithm = _check_algorithm(algorithm)
            if latent.shape[0] != len(algorithm):
                raise ValueError("latent and algorithm batch sizes must match")
            algorithm_batch = algorithm.unsqueeze(1)
            conditional = False
        context = torch.cat([
            latent.unsqueeze(1).expand(-1, algorithm_batch.shape[1], -1),
            self.algorithm_embedding(algorithm_batch),
        ], dim=-1)
        shared = self.parameter_trunk(context.reshape(-1, context.shape[-1]))
        shared = shared.reshape(latent.shape[0], algorithm_batch.shape[1], -1)
        result = {
            "feedback": self.feedback_head(shared),
            **{
                f"op_{op_index}_{field}": self.parameter_heads[f"op_{op_index}_{field}"](shared)
                for op_index in range(6)
                for field in OPERATOR_FIELDS
            },
        }
        if conditional:
            return result
        return {key: value.squeeze(1) for key, value in result.items()}

    def forward(self, waveform: torch.Tensor,
                algorithm: torch.Tensor | None = None) -> dict[str, torch.Tensor | dict[str, torch.Tensor]]:
        latent, algorithm_logits = self.encode(waveform)
        return {
            "latent": latent,
            "algorithm_logits": algorithm_logits,
            "parameter_logits": self.parameter_logits(latent, algorithm),
        }

    def count_parameters(self) -> int:
        return sum(parameter.numel() for parameter in self.parameters())

    def architecture_config(self) -> dict[str, int]:
        return {
            "algorithm_dim": self.algorithm_dim,
            "hidden_dim": self.hidden_dim,
            "harmonic_bands": self.harmonic_bands,
            "conv_channels": self.conv_channels,
        }


def _sample_from_logits(logits: torch.Tensor, *, temperature: float,
                        generator: torch.Generator) -> torch.Tensor:
    if not math.isfinite(temperature) or temperature < 0:
        raise ValueError("temperature must be a finite nonnegative number")
    if temperature == 0:
        return logits.argmax(dim=-1)
    probabilities = torch.softmax(logits.detach().float().cpu() / temperature, dim=-1)
    return torch.multinomial(probabilities, 1, generator=generator).squeeze(-1)


def generate_candidates(model: ProposerModel, waveform: torch.Tensor, *, count: int = 16,
                        seed: int = 0, temperature: float = 1.0) -> list[Patch]:
    """Generate a bounded, legal candidate set from waveform distributions."""
    if type(count) is not int or not 1 <= count <= 256:
        raise ValueError("count must be an integer from 1 to 256")
    if type(seed) is not int:
        raise ValueError("seed must be an int")
    if not math.isfinite(temperature) or temperature < 0:
        raise ValueError("temperature must be a finite nonnegative number")
    if not isinstance(model, ProposerModel):
        raise ValueError("model must be a ProposerModel")
    model.eval()
    try:
        model_device = next(model.parameters()).device
    except StopIteration as exc:
        raise ValueError("model must contain parameters") from exc
    waveform = waveform.to(model_device)
    with torch.no_grad():
        latent, algorithm_logits = model.encode(waveform)
    if latent.shape[0] != 1:
        raise ValueError("candidate generation accepts one target at a time")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    algorithm_probs = torch.softmax(algorithm_logits[0].detach().float().cpu() / max(temperature, 1e-6), dim=-1)
    top_algorithms = (torch.topk(algorithm_probs, k=min(8, ALGORITHM_COUNT)).indices + 1).tolist()
    algorithms = []
    for index in range(count):
        if index < len(top_algorithms):
            algorithms.append(int(top_algorithms[index]))
        else:
            algorithms.append(int(torch.multinomial(algorithm_probs, 1, generator=generator).item()) + 1)
    algorithm_tensor = torch.tensor(algorithms, dtype=torch.long, device=latent.device)
    latent_batch = latent.expand(count, -1)
    with torch.no_grad():
        logits = model.parameter_logits(latent_batch, algorithm_tensor)
    parameter_values: dict[str, torch.Tensor] = {}
    parameter_values["feedback"] = _sample_from_logits(
        logits["feedback"], temperature=temperature, generator=generator
    )
    for op_index in range(6):
        for field in OPERATOR_FIELDS:
            parameter_values[f"op_{op_index}_{field}"] = _sample_from_logits(
                logits[f"op_{op_index}_{field}"], temperature=temperature, generator=generator
            )
    candidates = []
    for index in range(count):
        operators = tuple(
            Operator(
                op=op_index + 1,
                coarse=int(parameter_values[f"op_{op_index}_coarse"][index]),
                fine=int(parameter_values[f"op_{op_index}_fine"][index]),
                detune=int(parameter_values[f"op_{op_index}_detune"][index]),
                mode=int(parameter_values[f"op_{op_index}_mode"][index]),
                level=int(parameter_values[f"op_{op_index}_level"][index]),
            )
            for op_index in range(6)
        )
        candidates.append(validate_patch(Patch(
            algorithm=algorithms[index],
            feedback=int(parameter_values["feedback"][index]),
            operators=operators,
        )))
    return candidates


def patch_distance(first: Patch, second: Patch) -> float:
    first_checked = validate_patch(first)
    second_checked = validate_patch(second)
    values = [abs(first_checked.algorithm - second_checked.algorithm) / 31.0,
              abs(first_checked.feedback - second_checked.feedback) / 7.0]
    for left, right in zip(first_checked.operators, second_checked.operators):
        for field, maximum in (("coarse", 31), ("fine", 99), ("detune", 14), ("mode", 1), ("level", 99)):
            values.append(abs(getattr(left, field) - getattr(right, field)) / float(maximum))
    return sum(values) / len(values)


def deduplicate_candidates(candidates: list[Patch]) -> list[Patch]:
    result = []
    seen = set()
    for candidate in candidates:
        checked = validate_patch(candidate)
        key = (checked.algorithm, checked.feedback, tuple(
            (getattr(operator, field) for field in OPERATOR_FIELDS)
            for operator in checked.operators
        ))
        if key not in seen:
            seen.add(key)
            result.append(checked)
    return result


def candidate_diversity(candidates: list[Patch]) -> dict[str, float | int]:
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("candidates must be a nonempty list")
    checked = [validate_patch(candidate) for candidate in candidates]
    keys = {
        (candidate.algorithm, candidate.feedback, tuple(
            (getattr(operator, field) for field in OPERATOR_FIELDS)
            for operator in candidate.operators
        ))
        for candidate in checked
    }
    algorithms = {candidate.algorithm for candidate in checked}
    topologies = {topology_for(candidate.algorithm).topology_signature for candidate in checked}
    pairwise = [patch_distance(first, second) for index, first in enumerate(checked)
                for second in checked[index + 1:]]
    parameter_values = set()
    for candidate in checked:
        for op_index, operator in enumerate(candidate.operators):
            parameter_values.update(
                (op_index, field, getattr(operator, field)) for field in OPERATOR_FIELDS
            )
    domain_size = 6 * sum(OPERATOR_COUNTS[field] for field in OPERATOR_FIELDS)
    return {
        "count": len(checked),
        "legal_count": len(checked),
        "legal_rate": 1.0,
        "unique_count": len(keys),
        "unique_rate": len(keys) / len(checked),
        "duplicate_collapse": 1.0 - len(keys) / len(checked),
        "algorithm_diversity": len(algorithms),
        "topology_diversity": len(topologies),
        "parameter_diversity": len(parameter_values) / float(domain_size),
        "mean_pairwise_distance": sum(pairwise) / len(pairwise) if pairwise else 0.0,
    }
