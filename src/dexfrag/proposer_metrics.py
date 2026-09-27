"""One-to-many distribution losses and diagnostics for the inverse proposer."""
from __future__ import annotations

import math

import torch
import torch.nn.functional as F

from .patch import LIMITS
from .proposer_model import ALGORITHM_COUNT, FEEDBACK_COUNT, OPERATOR_FIELDS


LOSS_VERSION = "dexfrag-proposer-distribution-ce-v3"
_FIELD_KEYS = tuple(f"op_{op_index}_{field}" for op_index in range(6) for field in OPERATOR_FIELDS)


def _cross_entropy(logits: torch.Tensor, target: torch.Tensor, smoothing: float) -> torch.Tensor:
    if logits.ndim < 2 or target.shape != logits.shape[:-1] or target.dtype != torch.long:
        raise ValueError("logits and long target shapes do not agree")
    return F.cross_entropy(
        logits.reshape(-1, logits.shape[-1]),
        target.reshape(-1),
        label_smoothing=smoothing,
    )


def _conditional_cross_entropy(logits: torch.Tensor, algorithm_logits: torch.Tensor,
                               target: torch.Tensor, smoothing: float) -> torch.Tensor:
    if (logits.ndim != 3 or algorithm_logits.ndim != 2
            or logits.shape[:2] != algorithm_logits.shape
            or target.shape != algorithm_logits.shape[:1]):
        raise ValueError("conditional logits and targets have incompatible shapes")
    if target.dtype != torch.long or bool((target < 0).any()) or bool((target >= logits.shape[-1]).any()):
        raise ValueError("conditional targets are outside the legal category range")
    algorithm_log_probs = F.log_softmax(algorithm_logits, dim=-1)
    parameter_log_probs = F.log_softmax(logits, dim=-1)
    log_marginal = torch.logsumexp(
        algorithm_log_probs.unsqueeze(-1) + parameter_log_probs, dim=1
    )
    target_log_prob = log_marginal.gather(1, target.unsqueeze(1)).squeeze(1)
    if smoothing == 0:
        return -target_log_prob.mean()
    # Label smoothing: -( (1-s) log p(target) + s * mean_c log p(c) ).
    # The mean of log-probabilities is <= 0, so it must enter the negated
    # expression directly; negating it here would make the objective unbounded
    # below and reward ever-more-extreme logits.
    return -((1.0 - smoothing) * target_log_prob
             + smoothing * log_marginal.mean(dim=1)).mean()


def _accuracy(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    return (logits.argmax(dim=-1) == target).float().mean()


def _conditional_accuracy(logits: torch.Tensor, algorithm_logits: torch.Tensor,
                          target: torch.Tensor) -> torch.Tensor:
    probabilities = torch.softmax(algorithm_logits, dim=-1).unsqueeze(-1) * torch.softmax(logits, dim=-1)
    return (probabilities.sum(dim=1).argmax(dim=-1) == target).float().mean()


def _entropy(logits: torch.Tensor) -> torch.Tensor:
    probabilities = torch.softmax(logits.detach(), dim=-1)
    return -(probabilities * torch.log(probabilities.clamp_min(1e-9))).sum(dim=-1).mean()


def proposer_loss(outputs: dict, *, label_smoothing: float = 0.05) -> dict[str, torch.Tensor]:
    """Compute smoothed categorical objectives rather than pointwise MSE."""
    if not isinstance(outputs, dict) or "algorithm_logits" not in outputs or "parameter_logits" not in outputs:
        raise ValueError("model outputs are missing required distribution heads")
    if not math.isfinite(label_smoothing) or not 0.0 <= label_smoothing < 1.0:
        raise ValueError("label_smoothing must be in [0, 1)")
    algorithm_logits = outputs["algorithm_logits"]
    parameter_logits = outputs["parameter_logits"]
    if algorithm_logits.ndim != 2 or algorithm_logits.shape[1] != ALGORITHM_COUNT:
        raise ValueError("algorithm logits must have shape [B, 32]")
    algorithm_target = outputs["algorithm_target"].to(device=algorithm_logits.device)
    if (algorithm_target.dtype != torch.long or algorithm_target.ndim != 1
            or bool((algorithm_target < 1).any()) or bool((algorithm_target > 32).any())):
        raise ValueError("algorithm targets must contain integers from 1 to 32")
    algorithm_class_target = algorithm_target - 1
    feedback_logits = parameter_logits["feedback"]
    if feedback_logits.ndim not in (2, 3) or feedback_logits.shape[-1] != FEEDBACK_COUNT:
        raise ValueError("feedback logits must have shape [B, 8] or [B, 32, 8]")
    feedback_target = outputs["feedback_target"].to(device=feedback_logits.device)
    if (feedback_target.dtype != torch.long or feedback_target.shape != (algorithm_logits.shape[0],)
            or bool((feedback_target < 0).any()) or bool((feedback_target > 7).any())):
        raise ValueError("feedback targets must contain integers from 0 to 7")
    operator_target = outputs["operators"].to(device=algorithm_logits.device)
    if operator_target.dtype != torch.long or operator_target.ndim != 3 or tuple(operator_target.shape[1:]) != (6, 5):
        raise ValueError("operator targets must have shape [B, 6, 5]")
    maxima = torch.tensor([LIMITS[field] for field in OPERATOR_FIELDS], dtype=torch.long,
                          device=algorithm_logits.device)
    if bool((operator_target < 0).any()) or bool((operator_target > maxima).any()):
        raise ValueError("operator targets hold values outside legal DX7 ranges")
    algorithm_loss = _cross_entropy(algorithm_logits, algorithm_class_target, label_smoothing)
    if feedback_logits.ndim == 3:
        feedback_loss = _conditional_cross_entropy(
            feedback_logits, algorithm_logits, feedback_target, label_smoothing
        )
        feedback_accuracy = _conditional_accuracy(
            feedback_logits, algorithm_logits, feedback_target
        )
    else:
        feedback_loss = _cross_entropy(feedback_logits, feedback_target, label_smoothing)
        feedback_accuracy = _accuracy(feedback_logits, feedback_target)
    field_losses = []
    field_accuracies = []
    entropies = [_entropy(algorithm_logits), _entropy(feedback_logits)]
    field_keys = []
    for op_index in range(6):
        for field_index, field in enumerate(OPERATOR_FIELDS):
            key = f"op_{op_index}_{field}"
            logits = parameter_logits[key]
            target = operator_target[:, op_index, field_index]
            if logits.ndim == 3:
                field_losses.append(_conditional_cross_entropy(
                    logits, algorithm_logits, target, label_smoothing
                ))
                field_accuracies.append(_conditional_accuracy(
                    logits, algorithm_logits, target
                ))
            else:
                field_losses.append(_cross_entropy(logits, target, label_smoothing))
                field_accuracies.append(_accuracy(logits, target))
            entropies.append(_entropy(logits))
            field_keys.append(key)
    parameter_loss = torch.stack(field_losses).mean()
    total = algorithm_loss + feedback_loss + parameter_loss
    result = {
        "loss": total,
        "algorithm_loss": algorithm_loss,
        "feedback_loss": feedback_loss,
        "parameter_loss": parameter_loss,
        "algorithm_accuracy": _accuracy(algorithm_logits, algorithm_class_target),
        "feedback_accuracy": feedback_accuracy,
        "operator_accuracy": torch.stack(field_accuracies).mean(),
        "algorithm_entropy": entropies[0],
        "mean_head_entropy": torch.stack(entropies[1:]).mean(),
    }
    for key, value in zip(field_keys, field_losses):
        result[f"{key}_loss"] = value
    return result


def attach_training_targets(outputs: dict, *, algorithm: torch.Tensor,
                             feedback: torch.Tensor, operators: torch.Tensor) -> dict:
    """Return model outputs with labels separated from model-facing inputs."""
    result = dict(outputs)
    result["algorithm_target"] = algorithm
    result["feedback_target"] = feedback
    result["operators"] = operators
    return result
