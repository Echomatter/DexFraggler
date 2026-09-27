"""Candidate diversity, surrogate ranking, baselines, and bounded native checks."""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import torch

from .acquisition import broad_structured_exploration, random_legal_exploration
from .algorithms import topology_for
from .features import canonical_frame
from .forward_model import ForwardModel
from .forward_training import load_checkpoint as load_forward_checkpoint
from .forward_training import resolve_device
from .native import NativeRenderer, NativeRendererError
from .patch import Operator, Patch, validate_patch
from .proposer_data import ProposerDataset
from .proposer_model import (
    OPERATOR_FIELDS,
    ProposerModel,
    candidate_diversity,
    deduplicate_candidates,
    generate_candidates,
)
from .proposer_training import checkpoint_model_config
from .proposer_training import load_checkpoint as load_proposer_checkpoint


DEFAULT_NATIVE_BUDGETS = (1, 4, 8, 16, 32, 64)


def _patch_from_item(item: dict) -> Patch:
    operators = tuple(
        Operator(
            op=index + 1,
            coarse=int(item["operators"][index, 0]),
            fine=int(item["operators"][index, 1]),
            detune=int(item["operators"][index, 2]),
            mode=int(item["operators"][index, 3]),
            level=int(item["operators"][index, 4]),
        )
        for index in range(6)
    )
    return validate_patch(Patch(
        algorithm=int(item["algorithm"]), feedback=int(item["feedback"]), operators=operators
    ))


def patch_model_inputs(candidates: list[Patch], device: torch.device) -> dict:
    checked = [validate_patch(candidate) for candidate in candidates]
    if not checked:
        raise ValueError("candidate list cannot be empty")
    return {
        "algorithm": torch.tensor([candidate.algorithm for candidate in checked], dtype=torch.long, device=device),
        "feedback": torch.tensor([candidate.feedback for candidate in checked], dtype=torch.long, device=device),
        "operators": torch.tensor([
            [[getattr(operator, field) for field in OPERATOR_FIELDS] for operator in candidate.operators]
            for candidate in checked
        ], dtype=torch.long, device=device),
        "topology_signature": [topology_for(candidate.algorithm).topology_signature for candidate in checked],
    }


def native_similarity(prediction: torch.Tensor, target: torch.Tensor) -> dict[str, float]:
    """Return bounded phase-bearing waveform quality and transparent errors."""
    if prediction.shape != target.shape or prediction.ndim != 2 or prediction.shape[-1] != 2048:
        raise ValueError("prediction and target must have matching [N, 2048] shapes")
    if not torch.isfinite(prediction).all() or not torch.isfinite(target).all():
        raise ValueError("prediction and target must be finite")
    prediction = prediction.detach().cpu().double()
    target = target.detach().cpu().double()
    residual = prediction - target
    mse = float(residual.square().mean())
    target_energy = float(target.double().square().mean())
    relative_rmse = math.sqrt(mse / max(target_energy, 1e-12))
    prediction_centered = prediction.double() - prediction.double().mean(dim=-1, keepdim=True)
    target_centered = target.double() - target.double().mean(dim=-1, keepdim=True)
    denominator = (prediction_centered.square().mean(-1) * target_centered.square().mean(-1)).sqrt().clamp_min(1e-12)
    correlation = ((prediction_centered * target_centered).mean(-1) / denominator).clamp(-1, 1)
    constant = (prediction_centered.square().mean(-1) <= 1e-12) & (target_centered.square().mean(-1) <= 1e-12)
    correlation = torch.where(constant, torch.ones_like(correlation), correlation)
    correlation_value = float(correlation.mean())
    quality = math.exp(-relative_rmse) * (0.5 + 0.5 * correlation_value)
    return {
        "native_similarity": quality,
        "native_mse": mse,
        "relative_rmse": relative_rmse,
        "native_correlation": correlation_value,
    }


@torch.no_grad()
def rank_with_forward(model: ForwardModel, candidates: list[Patch], target_waveform: torch.Tensor,
                      device: torch.device, *, batch_size: int = 32) -> tuple[list[Patch], list[float]]:
    if not isinstance(model, ForwardModel):
        raise ValueError("model must be a ForwardModel")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("candidates must be a nonempty list")
    if target_waveform.ndim != 2 or target_waveform.shape[1] != 2048:
        raise ValueError("target_waveform must have shape [N, 2048]")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    model.eval()
    model.to(device)
    target = target_waveform.to(device).float()
    scores: list[float] = []
    for start in range(0, len(candidates), batch_size):
        piece = candidates[start:start + batch_size]
        batch = patch_model_inputs(piece, device)
        prediction = model.forward_batch(batch)
        if target.shape[0] == prediction.shape[1]:
            comparison_target = target
        elif target.shape[0] == 1:
            comparison_target = target.expand(prediction.shape[1], -1)
        else:
            raise ValueError("target frame count must be one or three")
        scores.extend((prediction - comparison_target.unsqueeze(0)).square().mean(dim=(1, 2)).cpu().tolist())
    order = sorted(range(len(candidates)), key=lambda index: (scores[index], index))
    return [candidates[index] for index in order], [scores[index] for index in order]


def _random_candidates(kind: str, count: int, seed: int) -> list[Patch]:
    generator = random.Random(seed)
    if kind == "random_legal":
        return [candidate.patch for candidate in random_legal_exploration(generator, count)]
    if kind == "broad_structured":
        return [candidate.patch for candidate in broad_structured_exploration(generator, count)]
    raise ValueError(f"unknown baseline candidate source: {kind}")


def _nearest_candidates(target_waveform: torch.Tensor, retrieval_items: list[dict], count: int, seed: int) -> list[Patch]:
    if not retrieval_items:
        return _random_candidates("random_legal", count, seed)
    target = target_waveform.detach().cpu().float()
    ranked = sorted(
        retrieval_items,
        key=lambda item: float((item["waveform"].float() - target).square().mean()),
    )
    result = [_patch_from_item(item) for item in ranked[:count]]
    if len(result) < count:
        result.extend(_random_candidates("random_legal", count - len(result), seed + 7919))
    return result


def _capture_waveform(capture) -> torch.Tensor:
    frames = [
        canonical_frame(waveform, note, max_harmonics=64).samples
        for waveform, note in zip(capture.waveforms, capture.notes)
    ]
    return torch.tensor(frames, dtype=torch.float32)


def _mean_metrics(entries: list[dict]) -> dict:
    if not entries:
        return {}
    keys = entries[0].keys()
    return {key: sum(float(entry[key]) for entry in entries) / len(entries) for key in keys}


def _native_curve(scored: list[tuple[float, float]], budget: int) -> dict[str, float | int]:
    curve: dict[str, float | int] = {}
    for requested in DEFAULT_NATIVE_BUDGETS:
        if requested > budget:
            continue
        usable = scored[:requested]
        if not usable:
            continue
        curve[str(requested)] = max(quality for quality, _ in usable)
    return curve


def _render_method(renderer: NativeRenderer | None, ranked: list[Patch], target: torch.Tensor,
                   budget: int, cache: dict[str, torch.Tensor], render_counter: list[int],
                   max_total_renders: int) -> tuple[list[tuple[float, float]], int, str | None]:
    if renderer is None or budget <= 0:
        return [], 0, None
    scored: list[tuple[float, float]] = []
    rendered = 0
    for patch in ranked[:budget]:
        key = patch.to_dict()
        cache_key = repr(key)
        waveform = cache.get(cache_key)
        if waveform is None:
            if render_counter[0] >= max_total_renders:
                break
            try:
                capture = renderer.render(patch)
                waveform = _capture_waveform(capture)
            except (NativeRendererError, OSError) as exc:
                return scored, rendered, str(exc)
            cache[cache_key] = waveform
            render_counter[0] += 1
            rendered += 1
        metrics = native_similarity(waveform, target)
        scored.append((metrics["native_similarity"], metrics["native_mse"]))
    return scored, rendered, None


def evaluate_proposer(corpus: str | Path, checkpoint: str | Path, *,
                      forward_checkpoint: str | Path | None = None,
                      device: str = "cpu", max_targets: int = 8,
                      candidate_count: int = 16, native_budget: int = 0,
                      max_total_renders: int = 16, seed: int = 0,
                      temperature: float = 1.0, include_baselines: bool = True) -> dict:
    """Evaluate a proposer on protected native targets with optional native truth."""
    if type(max_targets) is not int or max_targets < 1:
        raise ValueError("max_targets must be a positive integer")
    if type(candidate_count) is not int or not 1 <= candidate_count <= 256:
        raise ValueError("candidate_count must be an integer from 1 to 256")
    if type(native_budget) is not int or not 0 <= native_budget <= 64:
        raise ValueError("native_budget must be an integer from 0 to 64")
    if type(max_total_renders) is not int or max_total_renders < 0:
        raise ValueError("max_total_renders must be a nonnegative integer")
    if type(seed) is not int:
        raise ValueError("seed must be an int")
    if not isinstance(include_baselines, bool):
        raise ValueError("include_baselines must be a bool")
    if not math.isfinite(temperature) or temperature < 0:
        raise ValueError("temperature must be a finite nonnegative number")
    resolved = resolve_device(device)
    proposer = ProposerModel(**checkpoint_model_config(checkpoint))
    proposer_info = load_proposer_checkpoint(checkpoint, proposer)
    proposer.to(resolved).eval()
    forward_model = None
    forward_info = None
    if forward_checkpoint is not None:
        forward_model = ForwardModel()
        forward_info = load_forward_checkpoint(forward_checkpoint, forward_model)
        forward_model.to(resolved).eval()
    dataset = ProposerDataset(corpus, "test", allow_protected=True)
    retrieval_items: list[dict] = []
    for split in ("train", "validation"):
        try:
            retrieval_items.extend(ProposerDataset(corpus, split).items)
        except ValueError:
            pass
    renderer = None
    native_error = None
    native_disabled = False
    if native_budget > 0 and max_total_renders > 0:
        try:
            renderer = NativeRenderer()
        except (NativeRendererError, OSError) as exc:
            native_error = str(exc)
    render_cache: dict[str, torch.Tensor] = {}
    render_counter = [0]
    method_records: dict[str, dict[str, list]] = {
        "proposer": {"diversity": [], "native": [], "forward": []},
    }
    if include_baselines:
        for name in ("random_legal", "broad_structured", "nearest_native"):
            method_records[name] = {"diversity": [], "native": [], "forward": []}
    failures = []
    try:
        for target_index, item in enumerate(dataset.items[:max_targets]):
            target = item["waveform"].to(resolved).float()
            proposer_candidates = generate_candidates(
                proposer, target, count=candidate_count, seed=seed + target_index,
                temperature=temperature,
            )
            candidates_by_method = {"proposer": proposer_candidates}
            if include_baselines:
                candidates_by_method["random_legal"] = _random_candidates(
                    "random_legal", candidate_count, seed + 1009 * (target_index + 1)
                )
                candidates_by_method["broad_structured"] = _random_candidates(
                    "broad_structured", candidate_count, seed + 2003 * (target_index + 1)
                )
                candidates_by_method["nearest_native"] = _nearest_candidates(
                    target, retrieval_items, candidate_count, seed + 3001 * (target_index + 1)
                )
            target_failures = []
            for method, raw_candidates in candidates_by_method.items():
                diversity = candidate_diversity(raw_candidates)
                unique_candidates = deduplicate_candidates(raw_candidates)
                if forward_model is not None:
                    ranked, forward_scores = rank_with_forward(
                        forward_model, unique_candidates, target, resolved
                    )
                else:
                    ranked, forward_scores = unique_candidates, list(range(len(unique_candidates)))
                method_records[method]["diversity"].append(diversity)
                method_records[method]["forward"].append({
                    "candidate_count": len(ranked),
                    "mean_score": sum(forward_scores) / len(forward_scores) if forward_scores else 0.0,
                })
                scored, rendered, render_error = _render_method(
                    None if native_disabled else renderer, ranked, target, native_budget, render_cache,
                    render_counter, max_total_renders,
                )
                if render_error is not None:
                    native_error = native_error or render_error
                    native_disabled = True
                native_record = {
                    "target_count": 1,
                    "rendered": rendered,
                    "budget_curve": _native_curve(scored, native_budget),
                    "best_similarity": max((quality for quality, _ in scored), default=None),
                    "best_mse": min((mse for _, mse in scored), default=None),
                    "error": render_error,
                }
                method_records[method]["native"].append(native_record)
                if diversity["unique_rate"] < 0.25:
                    target_failures.append({"reason": "low_candidate_diversity", "method": method})
                if native_record["best_similarity"] is not None and native_record["best_similarity"] < 0.5:
                    target_failures.append({"reason": "low_native_similarity", "method": method})
            if len(failures) < 20:
                failures.extend({
                    "target_hash": item.get("target_hash", item.get("key")),
                    **failure,
                } for failure in target_failures)
    finally:
        if renderer is not None:
            renderer.close()
    method_summary = {}
    for method, records in method_records.items():
        native_records = records["native"]
        method_summary[method] = {
            "candidate": _mean_metrics(records["diversity"]),
            "forward": _mean_metrics(records["forward"]),
            "native": {
                "target_count": len(native_records),
                "targets_scored": sum(
                    record["best_similarity"] is not None for record in native_records
                ),
                "rendered_total": sum(record["rendered"] for record in native_records),
                "render_errors": sum(record["error"] is not None for record in native_records),
                "mean_best_similarity": _mean_metrics([
                    {"value": record["best_similarity"]} for record in native_records
                    if record["best_similarity"] is not None
                ]).get("value"),
                "budget_curve": {
                    str(budget): sum(
                        record["budget_curve"].get(str(budget), 0.0) for record in native_records
                    ) / max(1, sum(str(budget) in record["budget_curve"] for record in native_records))
                    for budget in DEFAULT_NATIVE_BUDGETS
                    if any(str(budget) in record["budget_curve"] for record in native_records)
                },
            },
        }
    return {
        "corpus": str(corpus),
        "checkpoint": str(checkpoint),
        "forward_checkpoint": str(forward_checkpoint) if forward_checkpoint is not None else None,
        "device": str(resolved),
        "model_version": proposer_info.get("model_version"),
        "loss_version": proposer_info.get("loss_version"),
        "parameter_count": proposer.count_parameters(),
        "model_config": proposer.architecture_config(),
        "protected_split": "test",
        "dataset_count": min(max_targets, len(dataset)),
        "candidate_count": candidate_count,
        "native_budget": native_budget,
        "max_total_renders": max_total_renders,
        "actual_native_renders": render_counter[0],
        "native_error": native_error,
        "forward_ranking_enabled": forward_model is not None,
        "forward_checkpoint_info": forward_info,
        "methods": method_summary,
        "failure_examples": failures,
    }


def write_evaluation_report(report: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path
