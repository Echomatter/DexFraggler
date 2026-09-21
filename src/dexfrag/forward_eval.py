"""Phase 3 evaluate-forward system (test/benchmark only).

Protected ``test``/``benchmark`` labels are loaded here with
``allow_protected=True``. ``train``/``validation`` splits are never loaded
by this module: any request for them raises ``ValueError``.

Provides grouped ``forward_loss`` means (overall, per algorithm, per
topology signature) and bounded ranking diagnostics via
:func:`dexfrag.forward_metrics.ranking_metrics` with self-matches excluded.
"""

from __future__ import annotations

import random
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from .forward_data import ForwardDataset
from .forward_metrics import SCORER_VERSION, forward_loss, ranking_metrics
from .forward_model import MODEL_VERSION, ForwardModel
from .forward_training import load_checkpoint, resolve_device

__all__ = [
    "EVAL_SPLITS",
    "DEFAULT_MAX_TARGETS",
    "DEFAULT_MAX_CANDIDATES_PER_TARGET",
    "MAX_CANDIDATES_PER_TARGET",
    "load_eval_dataset",
    "evaluate_grouped",
    "evaluate_ranking",
    "evaluate_forward",
]

EVAL_SPLITS = ("test", "benchmark")
DEFAULT_MAX_TARGETS = 32
DEFAULT_MAX_CANDIDATES_PER_TARGET = 500
# Hard bound keeping the O(targets * candidates^2) pairwise cost manageable.
MAX_CANDIDATES_PER_TARGET = 500


def _require_eval_split(split: str) -> str:
    if split not in EVAL_SPLITS:
        raise ValueError(
            f"Refusing non-evaluation split {split!r}: evaluate-forward loads only {list(EVAL_SPLITS)}"
        )
    return split


def _check_positive_int(name: str, value: int | None) -> None:
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError(f"{name} must be a positive integer or None")


def load_eval_dataset(
    corpus: str | Path, split: str = "test", *, max_rows: int | None = None
) -> ForwardDataset:
    """Load a protected evaluation split (``test`` or ``benchmark``).

    Train/validation are never loaded here and raise ``ValueError``.
    """
    _require_eval_split(split)
    if max_rows is not None and (type(max_rows) is not int or max_rows <= 0):
        raise ValueError("max_rows must be a positive integer or None")
    return ForwardDataset(corpus, split, allow_protected=True, max_rows=max_rows)


def _batch_to_device(batch: dict, device: torch.device) -> dict:
    moved = dict(batch)
    for key in ("algorithm", "feedback", "operators", "waveform"):
        moved[key] = batch[key].to(device)
    moved["topology_signature"] = list(batch["topology_signature"])
    return moved


@torch.no_grad()
def evaluate_grouped(
    model: ForwardModel,
    dataset: ForwardDataset,
    device: torch.device | str = "cpu",
    *,
    batch_size: int = 4,
) -> dict:
    """Mean forward losses overall, per algorithm, and per topology signature.

    Per-item losses come from :func:`forward_loss` on single-item batches so
    group means are exact item means (not batch-size-weighted batch means).
    """
    if not isinstance(model, ForwardModel):
        raise ValueError("model must be a ForwardModel")
    if not isinstance(dataset, ForwardDataset):
        raise ValueError("dataset must be a ForwardDataset")
    if dataset.split not in EVAL_SPLITS:
        raise ValueError(
            f"evaluate_grouped accepts only evaluation splits {list(EVAL_SPLITS)}"
        )
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
    device = resolve_device(device) if isinstance(device, str) else device
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)
    model.eval()
    model.to(device)

    overall = {"loss": 0.0, "waveform_mse": 0.0, "complex_harmonic_mse": 0.0,
               "correlation_loss": 0.0}
    by_algo: dict[int, dict] = {}
    by_topo: dict[str, dict] = {}
    count = 0
    for raw in loader:
        batch = _batch_to_device(raw, device)
        pred = model.forward_batch(batch)
        target = batch["waveform"]
        algos = batch["algorithm"].detach().cpu().tolist()
        sigs = list(raw["topology_signature"])
        for i in range(pred.shape[0]):
            losses = forward_loss(pred[i : i + 1], target[i : i + 1])
            for key in overall:
                value = float(losses[key].detach().cpu())
                if not torch.isfinite(torch.tensor(value)).item():
                    raise ValueError(f"nonfinite evaluation loss component: {key}")
                overall[key] += value
            algo = int(algos[i])
            entry = by_algo.setdefault(
                algo, {"count": 0, "loss": 0.0, "waveform_mse": 0.0,
                       "complex_harmonic_mse": 0.0, "correlation_loss": 0.0})
            entry["count"] += 1
            topo = str(sigs[i])
            tentry = by_topo.setdefault(
                topo, {"count": 0, "loss": 0.0, "waveform_mse": 0.0,
                       "complex_harmonic_mse": 0.0, "correlation_loss": 0.0})
            tentry["count"] += 1
            for key in overall:
                value = float(losses[key].detach().cpu())
                entry[key] += value
                tentry[key] += value
            count += 1
    if not count:
        raise ValueError("empty evaluation dataset")

    def _mean(entry: dict) -> dict:
        n = entry.pop("count")
        means = {key: entry[key] / n for key in overall}
        return {"count": n, **means}

    return {
        "split": dataset.split,
        "count": count,
        "overall": {key: overall[key] / count for key in overall},
        "by_algorithm": {str(k): _mean(v) for k, v in sorted(by_algo.items())},
        "by_topology_signature": {k: _mean(v) for k, v in sorted(by_topo.items())},
    }


@torch.no_grad()
def evaluate_ranking(
    model: ForwardModel,
    dataset: ForwardDataset,
    device: torch.device | str = "cpu",
    *,
    max_targets: int = DEFAULT_MAX_TARGETS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES_PER_TARGET,
    seed: int = 0,
) -> dict:
    """Ranking diagnostics on disjoint target/candidate pools (no self-matches).

    Targets and candidates are disjoint items by key, so no target ever ranks
    its own native waveform. The candidate pool is truncated to
    ``max_candidates`` (hard-capped at ``MAX_CANDIDATES_PER_TARGET``) to keep
    the quadratic pairwise cost manageable.
    """
    if not isinstance(model, ForwardModel):
        raise ValueError("model must be a ForwardModel")
    if not isinstance(dataset, ForwardDataset):
        raise ValueError("dataset must be a ForwardDataset")
    if dataset.split not in EVAL_SPLITS:
        raise ValueError(
            f"evaluate_ranking accepts only evaluation splits {list(EVAL_SPLITS)}"
        )
    _check_positive_int("max_targets", max_targets)
    _check_positive_int("max_candidates", max_candidates)
    if type(seed) is not int:
        raise ValueError("seed must be an int")
    if max_targets is None or max_candidates is None:  # pragma: no cover - guarded above
        raise ValueError("max_targets and max_candidates must be positive integers")
    max_candidates = min(int(max_candidates), MAX_CANDIDATES_PER_TARGET)
    max_targets = int(max_targets)
    device = resolve_device(device) if isinstance(device, str) else device
    if len(dataset) < 2:
        raise ValueError("ranking evaluation needs at least 2 observations")

    rng = random.Random(seed)
    indices = list(range(len(dataset)))
    rng.shuffle(indices)
    # Split the shuffled order into disjoint target/candidate pools so a
    # target can never match itself by key.
    n_targets = min(max_targets, max(1, len(indices) // 2))
    target_idx = indices[:n_targets]
    remaining = indices[n_targets:]
    if not remaining:
        raise ValueError("ranking evaluation needs at least 2 observations")
    candidate_idx = remaining[: min(max_candidates, len(remaining))]

    target_keys = [dataset.items[i]["key"] for i in target_idx]
    candidate_keys = [dataset.items[i]["key"] for i in candidate_idx]
    overlap = set(target_keys) & set(candidate_keys)
    if overlap:
        raise ValueError(f"self-matches not excluded: {sorted(overlap)[:3]}")

    model.eval()
    model.to(device)

    def _stack(keys_items: list[int], field: str) -> torch.Tensor:
        return torch.stack(
            [dataset.items[i][field].to(device) for i in keys_items]
        )

    native_targets = _stack(target_idx, "waveform").double()
    native_candidates = _stack(candidate_idx, "waveform").double()

    predicted_rows = []
    chunk = 8
    for start in range(0, len(candidate_idx), chunk):
        piece = candidate_idx[start : start + chunk]
        batch = {
            "algorithm": torch.stack([dataset.items[i]["algorithm"] for i in piece]).to(device),
            "feedback": torch.stack([dataset.items[i]["feedback"] for i in piece]).to(device),
            "operators": torch.stack([dataset.items[i]["operators"] for i in piece]).to(device),
            "topology_signature": [dataset.items[i]["topology_signature"] for i in piece],
        }
        predicted_rows.append(model.forward_batch(batch).to(device))
    predicted_candidates = torch.cat(predicted_rows, dim=0).double()
    # ranking_metrics validates finiteness/shapes; keep float32-compatible inputs.
    metrics = ranking_metrics(
        native_targets.float().to(device),
        native_candidates.float().to(device),
        predicted_candidates.float().to(device),
    )
    return {
        **metrics,
        "split": dataset.split,
        "max_targets_requested": max_targets,
        "max_candidates_requested": int(max_candidates),
        "candidate_pool_bound": MAX_CANDIDATES_PER_TARGET,
        "self_matches_excluded": True,
    }


@torch.no_grad()
def evaluate_forward(
    corpus: str | Path,
    checkpoint: str | Path,
    *,
    device: str = "cpu",
    max_targets: int = DEFAULT_MAX_TARGETS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES_PER_TARGET,
    seed: int = 0,
    batch_size: int = 4,
    max_rows: int | None = None,
    include_benchmark: bool = True,
) -> dict:
    """Load a checkpoint and evaluate grouped + ranking metrics on test split."""
    _check_positive_int("max_targets", max_targets)
    _check_positive_int("max_candidates", max_candidates)
    if type(seed) is not int:
        raise ValueError("seed must be an int")
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
    resolved = resolve_device(device)
    model = ForwardModel()
    info = load_checkpoint(checkpoint, model)
    model.to(resolved)
    model.eval()

    test_data = load_eval_dataset(corpus, "test", max_rows=max_rows)
    grouped = evaluate_grouped(model, test_data, resolved, batch_size=batch_size)
    ranking = evaluate_ranking(
        model, test_data, resolved,
        max_targets=max_targets, max_candidates=max_candidates, seed=seed,
    )
    summary: dict = {
        "corpus": str(corpus),
        "checkpoint": str(checkpoint),
        "device": str(resolved),
        "model_version": MODEL_VERSION,
        "scorer_version": SCORER_VERSION,
        "checkpoint_info": info,
        "split": "test",
        "count": grouped["count"],
        "overall": grouped["overall"],
        "by_algorithm": grouped["by_algorithm"],
        "by_topology_signature": grouped["by_topology_signature"],
        "ranking": ranking,
        "seed": seed,
    }
    if include_benchmark:
        try:
            bench = load_eval_dataset(corpus, "benchmark", max_rows=max_rows)
            summary["benchmark"] = evaluate_grouped(
                model, bench, resolved, batch_size=batch_size
            )
        except ValueError as exc:
            summary["benchmark"] = {"error": str(exc)}
    return summary
