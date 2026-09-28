"""Phase 3b compatibility ranker: two-tower embedding trained on native distances.

The forward model regresses waveforms directly (v1/v2/v3 -- all plateau at
ranking accuracy ~0.53-0.56 because the patch->waveform mapping is too
sensitive to regress from sparse rows). This module instead learns an
embedding space where patch-to-target distances match NATIVE canonical-frame
distances:

- ``PatchTower``: legal patch state -> unit embedding (same trunk inputs as
  the forward model: algorithm, feedback, operators, topology_signature).
- ``WaveTower``: canonical frame coefficients -> unit embedding. Ingesting
  coefficients (not raw samples) keeps the tower input compact and exactly
  invertible against the canonical synthesis basis.
- Training supervision is the native pairwise distance matrix between corpus
  frames, optimized with a ListNet cross-entropy over distance orderings
  plus a small cross-tower alignment term. The ranking metric the project
  gates on (pairwise accuracy) is therefore the training objective.

Serving: embed the target waveform and each candidate patch independently,
rank by embedding distance. Works for native and black-box targets alike
(the wave tower ingests any canonical frame). Bounded: no unbounded loops,
no protected splits, explicit caps on every entry point.
"""
from __future__ import annotations

import math
import os
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader

from .forward_data import FEATURE_VERSION, ForwardDataset
from .forward_eval import (
    DEFAULT_MAX_CANDIDATES_PER_TARGET,
    DEFAULT_MAX_TARGETS,
    EVAL_SPLITS,
    MAX_CANDIDATES_PER_TARGET,
)
from .forward_model import NOTE_BANDS, NOTE_MIDIS, _synthesis_bases, encode_conditioning
from .forward_training import (
    _batch_to_device,
    _check_finite_losses,
    _git_commit,
    make_loaders,
    resolve_device,
    seed_everything,
)

RANKER_VERSION = "dexfrag-ranker-v1"
RANKER_SCORER_VERSION = "dexfrag-ranker-distance-v1"
EMBED_DIM = 64
ALIGNMENT_WEIGHT = 0.1
VAL_PAIRWISE_ROWS = 128
BEST_FILENAME = "best.pt"
LAST_FILENAME = "last.pt"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class PatchTower(nn.Module):
    """Legal patch state -> unit embedding ``[B, EMBED_DIM]``."""

    def __init__(self, embedding_dim: int = EMBED_DIM) -> None:
        super().__init__()
        self.algorithm_embedding = nn.Embedding(33, 16, padding_idx=0)
        self.body = nn.Sequential(
            nn.Linear(16 + 39, 256), nn.ReLU(), nn.Linear(256, 256), nn.ReLU()
        )
        self.out = nn.Linear(256, embedding_dim)

    def forward(self, algorithm: torch.Tensor, feedback: torch.Tensor,
                operators: torch.Tensor, topology_signature: list[str]) -> torch.Tensor:
        _check_patch_ids(algorithm)
        conditioning = encode_conditioning(feedback, operators, topology_signature)
        if len(conditioning) != len(algorithm):
            raise ValueError("algorithm batch size must match other inputs")
        embedded = self.algorithm_embedding(algorithm)
        hidden = self.body(torch.cat([embedded, conditioning.to(embedded.device)], dim=1))
        return self.out(hidden)


class WaveTower(nn.Module):
    """Canonical frame coefficients -> unit embedding ``[B, EMBED_DIM]``."""

    INPUT_DIM = 2 * sum(NOTE_BANDS)

    def __init__(self, embedding_dim: int = EMBED_DIM) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(self.INPUT_DIM, 256), nn.ReLU(), nn.Linear(256, 256), nn.ReLU()
        )
        self.out = nn.Linear(256, embedding_dim)

    def forward(self, coefficients: torch.Tensor) -> torch.Tensor:
        if (not isinstance(coefficients, torch.Tensor) or not coefficients.is_floating_point()
                or coefficients.ndim != 2 or coefficients.shape[1] != self.INPUT_DIM
                or not len(coefficients)):
            raise ValueError(f"coefficients must have nonempty shape [B, {self.INPUT_DIM}]")
        if not torch.isfinite(coefficients).all():
            raise ValueError("coefficients contain nonfinite values")
        return self.out(self.body(coefficients))


class RankerModel(nn.Module):
    """Two-tower compatibility ranker: patches and frames share one space."""

    def __init__(self, embedding_dim: int = EMBED_DIM) -> None:
        super().__init__()
        if type(embedding_dim) is not int or embedding_dim <= 0:
            raise ValueError("embedding_dim must be a positive integer")
        self.embedding_dim = embedding_dim
        self.patch_tower = PatchTower(embedding_dim)
        self.wave_tower = WaveTower(embedding_dim)

    def embed_patches(self, algorithm: torch.Tensor, feedback: torch.Tensor,
                      operators: torch.Tensor,
                      topology_signature: list[str]) -> torch.Tensor:
        return nn.functional.normalize(
            self.patch_tower(algorithm, feedback, operators, topology_signature), dim=1
        )

    def embed_frames(self, coefficients: torch.Tensor) -> torch.Tensor:
        return nn.functional.normalize(self.wave_tower(coefficients), dim=1)

    def forward(self, algorithm: torch.Tensor, feedback: torch.Tensor,
                operators: torch.Tensor, topology_signature: list[str],
                coefficients: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        return self.embed_patches(algorithm, feedback, operators, topology_signature), \
            self.embed_frames(coefficients)

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())


def _check_patch_ids(algorithm: torch.Tensor) -> None:
    if not isinstance(algorithm, torch.Tensor) or algorithm.dtype != torch.long:
        raise ValueError("algorithm must be a torch.long tensor")
    if algorithm.ndim != 1 or not len(algorithm):
        raise ValueError("algorithm must have nonempty shape [B]")
    if bool((algorithm < 1).any() or (algorithm > 32).any()):
        raise ValueError("algorithm ids must be 1..32")


# ---------------------------------------------------------------------------
# Distances and loss
# ---------------------------------------------------------------------------
def frame_coefficients(waveform: torch.Tensor) -> torch.Tensor:
    """``[B, 3, 2048]`` canonical frame samples -> ``[B, 756]`` coefficients.

    Layout: per note in order 45/57/69, ``sin`` bands then ``cos`` bands.
    Exact inverse of the canonical synthesis basis (``theta = 2*pi*k*t/2048``):
    the frame is synthesized from these very basis functions, so the direct
    projection recovers the generating coefficients.
    """
    if (not isinstance(waveform, torch.Tensor) or not waveform.is_floating_point()
            or waveform.ndim != 3 or tuple(waveform.shape[1:]) != (3, 2048)
            or not len(waveform)):
        raise ValueError("waveform must have nonempty shape [B, 3, 2048]")
    if not torch.isfinite(waveform).all():
        raise ValueError("waveform contains nonfinite values")
    columns = []
    for index, note in enumerate(NOTE_MIDIS):
        bands = NOTE_BANDS[index]
        sin_basis, cos_basis = _synthesis_bases(note)
        sin_basis = sin_basis.to(device=waveform.device, dtype=waveform.dtype)
        cos_basis = cos_basis.to(device=waveform.device, dtype=waveform.dtype)
        samples = waveform[:, index]
        scale = 2.0 / samples.shape[1]
        columns.append(scale * (samples @ sin_basis.T))
        columns.append(scale * (samples @ cos_basis.T))
    return torch.cat(columns, dim=1)


def native_distances(waveform: torch.Tensor) -> torch.Tensor:
    """``[B, 3, 2048]`` -> ``[B, B]`` pairwise frame MSE (the eval's native scorer)."""
    if (not isinstance(waveform, torch.Tensor) or not waveform.is_floating_point()
            or waveform.ndim != 3 or tuple(waveform.shape[1:]) != (3, 2048)
            or not len(waveform)):
        raise ValueError("waveform must have nonempty shape [B, 3, 2048]")
    flat = waveform.double().flatten(start_dim=1)
    squared = flat.square().sum(dim=1)
    d2 = squared[:, None] + squared[None, :] - 2.0 * (flat @ flat.T)
    return (d2 / flat.shape[1]).clamp_min(0.0)


def ranker_loss(embeddings_p: torch.Tensor, embeddings_w: torch.Tensor,
                native_dists: torch.Tensor) -> dict[str, torch.Tensor]:
    """ListNet cross-entropy on native distance orderings + tower alignment.

    ``embeddings_p``/``embeddings_w`` are ``[B, D]`` unit embeddings;
    ``native_dists`` is the ``[B, B]`` native frame-MSE matrix. The soft
    target distribution per anchor is the native-distance softmax; the
    model distribution uses cross-tower embedding distances. Temperature
    is the batch median off-diagonal native distance (detached), so the
    loss adapts to the corpus's distance scale without a tuned constant.
    """
    for name, value in (("embeddings_p", embeddings_p), ("embeddings_w", embeddings_w),
                        ("native_dists", native_dists)):
        if not isinstance(value, torch.Tensor) or not torch.isfinite(value).all():
            raise ValueError(f"{name} must be a finite tensor")
    if embeddings_p.shape != embeddings_w.shape or embeddings_p.ndim != 2 or not len(embeddings_p):
        raise ValueError("embeddings must share nonempty shape [B, D]")
    if (native_dists.shape != (len(embeddings_p), len(embeddings_p))
            or bool((native_dists < 0).any())):
        raise ValueError("native_dists must be a nonneg [B, B] matrix")
    size = len(embeddings_p)
    eye = torch.eye(size, dtype=torch.bool, device=native_dists.device)
    off_diag = native_dists[~eye]
    tau = off_diag.median().clamp_min(1e-8) if off_diag.numel() else 1.0
    estimated = torch.cdist(embeddings_p, embeddings_w)
    targets = torch.softmax(-native_dists / tau, dim=1)
    predicted = torch.softmax(-estimated / tau, dim=1)
    listnet = -(targets * predicted.clamp_min(1e-12).log()).sum(dim=1).mean()
    alignment = (1.0 - (embeddings_p * embeddings_w).sum(dim=1)).mean()
    total = listnet + ALIGNMENT_WEIGHT * alignment
    return {"loss": total, "listnet_loss": listnet, "alignment_loss": alignment,
            "temperature": tau.detach()}


def pairwise_accuracy(native_dists: torch.Tensor,
                      estimated_dists: torch.Tensor) -> float | None:
    """Pairwise ordering accuracy with the eval's exact tie rules.

    Native exact ties are excluded; predicted ties earn half credit. Every
    anchor ranks all other items, so each unordered item pair is compared
    from both sides (consistent with the per-target pools in
    ``forward_metrics.ranking_metrics``).
    """
    for name, value in (("native_dists", native_dists), ("estimated_dists", estimated_dists)):
        if (not isinstance(value, torch.Tensor) or value.ndim != 2
                or value.shape[0] != value.shape[1] or not len(value)):
            raise ValueError(f"{name} must be a nonempty square matrix")
    if native_dists.shape != estimated_dists.shape:
        raise ValueError("distance matrices must share shape")
    if not torch.isfinite(native_dists).all() or not torch.isfinite(estimated_dists).all():
        raise ValueError("distance matrices must be finite")
    size = len(native_dists)
    credit = 0.0
    pairs = 0
    for anchor in range(size):
        keep = torch.ones(size, dtype=torch.bool, device=native_dists.device)
        keep[anchor] = False
        actual = native_dists[anchor][keep]
        estimated = estimated_dists[anchor][keep]
        a = torch.sign(actual[:-1, None] - actual[None, -1:])
        p = torch.sign(estimated[:-1, None] - estimated[None, -1:])
        comparable = a != 0
        pairs += int(comparable.sum())
        credit += float(((a == p) & comparable).sum())
        credit += 0.5 * float(((p == 0) & comparable).sum())
    return credit / pairs if pairs else None


def ranking_metrics_from_distances(native_targets: torch.Tensor,
                                   native_candidates: torch.Tensor,
                                   predicted_distances: torch.Tensor) -> dict[str, float | int | str | None]:
    """``forward_metrics.ranking_metrics`` semantics on per-target distance vectors.

    ``predicted_distances`` is ``[T, C]`` (lower = closer), e.g. cross-tower
    embedding distances. Native exact ties are excluded from pairwise
    accuracy; predicted ties earn half credit; top-1 ties choose the first
    candidate deterministically; random regret is the exact expectation of a
    uniform random choice.
    """
    for name, value in (("native_targets", native_targets), ("native_candidates", native_candidates),
                        ("predicted_distances", predicted_distances)):
        if not isinstance(value, torch.Tensor) or not value.is_floating_point():
            raise ValueError(f"{name} must be a floating-point tensor")
    if (native_targets.ndim != 3 or tuple(native_targets.shape[1:]) != (3, 2048)
            or not len(native_targets)):
        raise ValueError("native_targets must have nonempty shape [T, 3, 2048]")
    if (native_candidates.ndim != 3 or tuple(native_candidates.shape[1:]) != (3, 2048)
            or not len(native_candidates)):
        raise ValueError("native_candidates must have nonempty shape [C, 3, 2048]")
    if (predicted_distances.ndim != 2 or predicted_distances.shape != (len(native_targets), len(native_candidates))
            or not torch.isfinite(predicted_distances).all()):
        raise ValueError("predicted_distances must be finite with shape [T, C]")
    actual = (native_candidates.double() - native_targets[:, None].double()).square().mean(dim=(2, 3))
    estimated = predicted_distances.double()
    credit = 0.0
    pairs = 0
    regret = random_regret = 0.0
    for row in range(len(actual)):
        act = actual[row]
        est = estimated[row]
        best = act.min()
        regret += (act[est.argmin()] - best).item()
        random_regret += (act.mean() - best).item()
        for i in range(len(act) - 1):
            a = torch.sign(act[i] - act[i + 1:])
            p = torch.sign(est[i] - est[i + 1:])
            comparable = a != 0
            pairs += int(comparable.sum())
            credit += float(((a == p) & comparable).sum())
            credit += 0.5 * float(((p == 0) & comparable).sum())
    return {"scorer_version": RANKER_SCORER_VERSION, "target_count": len(native_targets),
            "candidate_count": len(native_candidates), "comparable_pairs": pairs,
            "pairwise_accuracy": credit / pairs if pairs else None,
            "top1_regret": regret / len(native_targets),
            "random_expected_regret": random_regret / len(native_targets)}


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------
@dataclass
class RankerTrainConfig:
    """Bounded ranker training configuration (train/validation splits only)."""

    corpus: Path
    checkpoint_dir: Path
    seed: int = 0
    device: str = "cpu"
    epochs: int = 20
    max_steps: int | None = None
    max_rows: int | None = None
    batch_size: int = 32
    learning_rate: float = 1e-3
    patience: int | None = 6
    num_workers: int = 0
    tensorboard_dir: Path | None = None
    best_filename: str = BEST_FILENAME
    last_filename: str = LAST_FILENAME

    def __post_init__(self) -> None:
        if self.epochs is None or type(self.epochs) is not int or self.epochs < 1:
            raise ValueError("epochs must be a positive integer")
        if self.max_steps is not None and (type(self.max_steps) is not int or self.max_steps < 1):
            raise ValueError("max_steps must be a positive integer or None")
        if self.max_rows is not None and (type(self.max_rows) is not int or self.max_rows < 1):
            raise ValueError("max_rows must be a positive integer or None")
        if type(self.batch_size) is not int or self.batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if type(self.learning_rate) is not float or not 0.0 < self.learning_rate < 1.0:
            raise ValueError("learning_rate must be a float in (0, 1)")
        if self.patience is not None and (type(self.patience) is not int or self.patience < 1):
            raise ValueError("patience must be a positive integer or None")
        if type(self.seed) is not int:
            raise ValueError("seed must be an int")
        if type(self.device) is not str or not self.device:
            raise ValueError("device must be a nonempty string")
        if self.num_workers is None or type(self.num_workers) is not int or self.num_workers < 0:
            raise ValueError("num_workers must be a nonneg integer")
        if self.tensorboard_dir is not None and not isinstance(self.tensorboard_dir, Path):
            raise ValueError("tensorboard_dir must be a Path or None")
        if self.best_filename == self.last_filename:
            raise ValueError("best and last filenames must differ")

    @property
    def best_path(self) -> Path:
        return self.checkpoint_dir / self.best_filename

    @property
    def last_path(self) -> Path:
        return self.checkpoint_dir / self.last_filename


def _serializable(config: RankerTrainConfig) -> dict:
    return {
        "corpus": str(config.corpus), "checkpoint_dir": str(config.checkpoint_dir),
        "seed": config.seed, "device": config.device, "epochs": config.epochs,
        "max_steps": config.max_steps, "max_rows": config.max_rows,
        "batch_size": config.batch_size, "learning_rate": config.learning_rate,
        "patience": config.patience, "num_workers": config.num_workers,
        "tensorboard_dir": str(config.tensorboard_dir) if config.tensorboard_dir else None,
    }


def save_checkpoint(path: str | Path, model: RankerModel,
                    optimizer: torch.optim.Optimizer | None, *, epoch: int,
                    completed_epochs: int, global_step: int, best_val: float,
                    train_config: RankerTrainConfig | dict | None = None,
                    corpus_path: str | Path | None = None,
                    corpus_rows: int | None = None) -> Path:
    """Persist a ranker checkpoint atomically (creates parent directories)."""
    path = Path(path)
    if not math.isfinite(best_val):
        pass  # pre-validation interrupt saves may carry a sentinel best
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict() if optimizer is not None else None,
        "epoch": int(epoch),
        "completed_epochs": int(completed_epochs),
        "global_step": int(global_step),
        "best_val": float(best_val),
        "model_version": RANKER_VERSION,
        "train_config": _serializable(train_config) if isinstance(train_config, RankerTrainConfig) else train_config,
        "git_commit": _git_commit(),
        "corpus_path": str(corpus_path) if corpus_path is not None else "",
        "corpus_rows": int(corpus_rows) if corpus_rows is not None else None,
        "feature_version": FEATURE_VERSION,
        "scorer_version": RANKER_SCORER_VERSION,
    }
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "wb") as handle:
            torch.save(payload, handle)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def load_checkpoint(path: str | Path, model: RankerModel,
                    optimizer: torch.optim.Optimizer | None = None) -> dict:
    """Load a ranker checkpoint into a model (and optionally its optimizer)."""
    payload = torch.load(Path(path), map_location="cpu", weights_only=True)
    for key in ("model_state", "epoch", "global_step", "best_val"):
        if key not in payload:
            raise ValueError(f"checkpoint is missing required key: {key}")
    saved_version = payload.get("model_version")
    if saved_version is not None and saved_version != RANKER_VERSION:
        raise ValueError(
            f"checkpoint model_version {saved_version!r} does not match current "
            f"{RANKER_VERSION!r}; ranker and forward checkpoints are not interchangeable"
        )
    model.load_state_dict(payload["model_state"])
    if optimizer is not None and payload.get("optimizer_state") is not None:
        optimizer.load_state_dict(payload["optimizer_state"])
    epoch = int(payload["epoch"])
    completed_epochs = int(payload["completed_epochs"]) if "completed_epochs" in payload else epoch + 1
    return {
        "epoch": epoch, "completed_epochs": completed_epochs,
        "global_step": int(payload["global_step"]), "best_val": float(payload["best_val"]),
        "model_version": payload.get("model_version"),
        "train_config": payload.get("train_config"),
        "git_commit": payload.get("git_commit", ""),
        "corpus_path": payload.get("corpus_path", ""),
        "corpus_rows": payload.get("corpus_rows"),
        "feature_version": payload.get("feature_version"),
        "scorer_version": payload.get("scorer_version"),
    }


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
@torch.no_grad()
def _validation_pairwise(model: RankerModel, val_loader: DataLoader,
                         device: torch.device, seed: int = 0) -> float | None:
    """Pairwise ordering accuracy under the exact evaluation protocol.

    Disjoint anchor/pool halves of a seeded random validation subsample --
    the same structure as ``evaluate_ranker`` (and ``forward_eval``'s ranking
    protocol). An anchor=pool design would let every item rank its own
    nearest neighbors and inflates accuracy by ~0.2, so it is deliberately
    not used for model selection.
    """
    items: list[dict] = []
    fields = ("algorithm", "feedback", "operators", "topology_signature", "waveform")
    for raw in val_loader:
        items.extend(
            {key: raw[key][i] for key in fields}
            for i in range(len(raw["waveform"]))
        )
        if len(items) >= VAL_PAIRWISE_ROWS:
            break
    if len(items) < 4:
        return None
    import random

    rng = random.Random(seed)
    indices = list(range(len(items)))
    rng.shuffle(indices)
    n_anchor = len(indices) // 2
    anchor_items = [items[i] for i in indices[:n_anchor]]
    pool_items = [items[i] for i in indices[n_anchor:]]
    if not pool_items:
        return None

    def _stack(group: list[dict], field: str) -> torch.Tensor:
        return torch.stack([item[field] for item in group]).to(device)

    native_targets = _stack(anchor_items, "waveform")
    native_candidates = _stack(pool_items, "waveform")
    anchor_embeddings = model.embed_patches(
        _stack(anchor_items, "algorithm"), _stack(anchor_items, "feedback"),
        _stack(anchor_items, "operators"),
        [item["topology_signature"] for item in anchor_items],
    )
    anchor_wave_embeddings = model.embed_frames(frame_coefficients(native_targets))
    pool_embeddings = model.embed_patches(
        _stack(pool_items, "algorithm"), _stack(pool_items, "feedback"),
        _stack(pool_items, "operators"),
        [item["topology_signature"] for item in pool_items],
    )
    predicted_distances = torch.cdist(anchor_wave_embeddings, pool_embeddings)
    model.eval()
    metrics = ranking_metrics_from_distances(
        native_targets.float(), native_candidates.float(), predicted_distances.float()
    )
    return metrics.get("pairwise_accuracy")


def train(config: RankerTrainConfig, model: RankerModel | None = None,
          optimizer: torch.optim.Optimizer | None = None,
          tensorboard_dir: Path | None = None) -> dict:
    """Run bounded ranker training; returns a JSON-friendly summary.

    Validation metric is the pairwise ordering accuracy on a fixed
    validation subsample -- the same quantity the evaluation gate uses.
    ``best.pt`` is written only when validation improves, so resume never
    overwrites the best checkpoint with a worse one. Resumes from
    ``last.pt`` when present.
    """
    seed_everything(config.seed)
    device = resolve_device(config.device)
    train_loader, val_loader = make_loaders(config)
    if model is None:
        model = RankerModel()
    if optimizer is None:
        optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    model.to(device)
    try:
        corpus_rows = len(train_loader.dataset) + len(val_loader.dataset)
    except (TypeError, AttributeError):
        corpus_rows = None

    def _provenance() -> dict:
        return {"train_config": config, "corpus_path": config.corpus,
                "corpus_rows": corpus_rows}

    start_epoch, global_step, best_val = 0, 0, -math.inf
    if config.last_path.exists():
        restored = load_checkpoint(config.last_path, model, optimizer)
        model.to(device)
        start_epoch, global_step = restored["completed_epochs"], restored["global_step"]
        best_val = restored["best_val"]
        if config.best_path.exists():
            try:
                best_payload = torch.load(config.best_path, map_location="cpu", weights_only=True)
                candidate = best_payload.get("best_val", -math.inf)
                if isinstance(candidate, (int, float)) and math.isfinite(candidate):
                    best_val = max(best_val, float(candidate))
            except (OSError, RuntimeError, ValueError):
                pass
    elif config.best_path.exists():
        try:
            payload = torch.load(config.best_path, map_location="cpu", weights_only=True)
            candidate = payload.get("best_val", -math.inf)
            if isinstance(candidate, (int, float)) and math.isfinite(candidate):
                best_val = float(candidate)
        except (OSError, RuntimeError, ValueError):
            pass
    completed_epochs = start_epoch

    history: list[dict] = []
    epochs_run = 0
    stopped_early = False
    early_stopped = False
    epochs_no_improve = 0
    effective_tb_dir = tensorboard_dir if tensorboard_dir is not None else config.tensorboard_dir
    if effective_tb_dir is not None and not isinstance(effective_tb_dir, Path):
        raise ValueError("tensorboard_dir must be a Path or None")
    writer = None
    if effective_tb_dir is not None:
        from torch.utils.tensorboard import SummaryWriter

        writer = SummaryWriter(log_dir=str(effective_tb_dir))
    try:
        for epoch in range(start_epoch, config.epochs):
            if config.max_steps is not None and global_step >= config.max_steps:
                break
            try:
                model.train()
                train_total = 0.0
                train_batches = 0
                for raw in train_loader:
                    if config.max_steps is not None and global_step >= config.max_steps:
                        stopped_early = True
                        break
                    batch = _batch_to_device(raw, device)
                    optimizer.zero_grad()
                    embeddings_p = model.embed_patches(
                        batch["algorithm"], batch["feedback"], batch["operators"],
                        batch["topology_signature"],
                    )
                    embeddings_w = model.embed_frames(frame_coefficients(batch["waveform"]))
                    losses = ranker_loss(embeddings_p, embeddings_w,
                                        native_distances(batch["waveform"]))
                    _check_finite_losses(losses)
                    losses["loss"].backward()
                    optimizer.step()
                    global_step += 1
                    train_total += float(losses["loss"].detach().cpu())
                    train_batches += 1
                if train_batches == 0:
                    break
                val_pairwise = _validation_pairwise(model, val_loader, device, seed=config.seed)
                if val_pairwise is None:
                    raise ValueError("validation split too small for pairwise metric")
                if not math.isfinite(val_pairwise):
                    raise ValueError("nonfinite validation pairwise accuracy")
                improved = val_pairwise > best_val + 1e-9
                if improved:
                    best_val = val_pairwise
                    epochs_no_improve = 0
                else:
                    epochs_no_improve += 1
                record = {
                    "epoch": epoch, "global_step": global_step,
                    "train_loss": train_total / train_batches,
                    "val_pairwise": val_pairwise, "best_val": best_val,
                    "improved": improved,
                }
                history.append(record)
                epochs_run += 1
                completed_epochs = epoch + 1
                save_checkpoint(
                    config.last_path, model, optimizer,
                    epoch=epoch, completed_epochs=completed_epochs,
                    global_step=global_step, best_val=best_val, **_provenance(),
                )
                if improved:
                    save_checkpoint(
                        config.best_path, model, optimizer,
                        epoch=epoch, completed_epochs=completed_epochs,
                        global_step=global_step, best_val=best_val, **_provenance(),
                    )
                if writer is not None:
                    writer.add_scalar("train_loss", record["train_loss"], epoch)
                    writer.add_scalar("val_pairwise", val_pairwise, epoch)
                    writer.add_scalar("best_val", best_val, epoch)
                    writer.add_scalar("learning_rate", float(optimizer.param_groups[0]["lr"]), epoch)
                    writer.add_scalar("global_step", global_step, epoch)
                    writer.flush()
                if stopped_early:
                    break
                if config.patience is not None and epochs_no_improve >= config.patience:
                    early_stopped = True
                    break
            except KeyboardInterrupt:
                save_checkpoint(
                    config.last_path, model, optimizer,
                    epoch=epoch, completed_epochs=completed_epochs,
                    global_step=global_step, best_val=best_val, **_provenance(),
                )
                raise
    finally:
        if writer is not None:
            writer.close()

    return {
        "best_val": best_val, "epochs_run": epochs_run, "global_step": global_step,
        "history": history,
        "last_checkpoint": str(config.last_path) if config.last_path.exists() else None,
        "best_checkpoint": str(config.best_path) if config.best_path.exists() else None,
        "model_version": RANKER_VERSION, "device": str(device),
        "train_batches": len(train_loader), "val_batches": len(val_loader),
        "early_stopped": early_stopped, "completed_epochs": completed_epochs,
        "stopped_early": stopped_early,
    }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
@torch.no_grad()
def evaluate_ranker(corpus: str | Path, checkpoint: str | Path, *,
                    device: str = "cpu",
                    max_targets: int = DEFAULT_MAX_TARGETS,
                    max_candidates: int = DEFAULT_MAX_CANDIDATES_PER_TARGET,
                    seed: int = 0) -> dict:
    """Ranking diagnostics for the ranker on disjoint target/candidate pools.

    Protocol mirrors ``forward_eval.evaluate_ranking`` exactly (seeded
    shuffle, disjoint pools, self-match exclusion, same caps); the only
    difference is the scorer: cross-tower embedding distances instead of
    predicted-waveform MSE.
    """
    if type(seed) is not int:
        raise ValueError("seed must be an int")
    if type(max_targets) is not int or max_targets < 1:
        raise ValueError("max_targets must be a positive integer")
    if type(max_candidates) is not int or max_candidates < 1:
        raise ValueError("max_candidates must be a positive integer")
    max_candidates = min(max_candidates, MAX_CANDIDATES_PER_TARGET)
    resolved = resolve_device(device) if isinstance(device, str) else device
    model = RankerModel()
    load_checkpoint(checkpoint, model)
    model.to(resolved)
    model.eval()

    dataset = ForwardDataset(corpus, "test", allow_protected=True)
    if dataset.split not in EVAL_SPLITS:
        raise ValueError(f"evaluation accepts only splits {list(EVAL_SPLITS)}")
    if len(dataset) < 2:
        raise ValueError("ranking evaluation needs at least 2 observations")

    import random

    rng = random.Random(seed)
    indices = list(range(len(dataset)))
    rng.shuffle(indices)
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

    def _stack(idxs: list[int], field: str) -> torch.Tensor:
        return torch.stack([dataset.items[i][field] for i in idxs]).to(resolved)

    native_targets = _stack(target_idx, "waveform").double()
    native_candidates = _stack(candidate_idx, "waveform").double()

    target_coeffs = frame_coefficients(native_targets.float())
    target_embeddings = model.embed_frames(target_coeffs)
    candidate_embeddings = []
    chunk = 64
    for start in range(0, len(candidate_idx), chunk):
        piece = candidate_idx[start : start + chunk]
        candidate_embeddings.append(model.embed_patches(
            _stack(piece, "algorithm"), _stack(piece, "feedback"),
            _stack(piece, "operators"),
            [dataset.items[i]["topology_signature"] for i in piece],
        ))
    candidate_embeddings = torch.cat(candidate_embeddings, dim=0)
    predicted_distances = torch.cdist(target_embeddings, candidate_embeddings)

    metrics = ranking_metrics_from_distances(
        native_targets.float(), native_candidates.float(), predicted_distances.float()
    )
    return {
        **metrics,
        "split": dataset.split,
        "max_targets_requested": max_targets,
        "max_candidates_requested": int(max_candidates),
        "candidate_pool_bound": MAX_CANDIDATES_PER_TARGET,
        "self_matches_excluded": True,
    }


def smoke_ranker(*, device: str = "cpu", steps: int = 3,
                 batch_size: int = 4) -> dict:
    """Corpus-free wiring smoke: synthetic batches, grad step, checkpoint."""
    if type(steps) is not int or steps < 1:
        raise ValueError("steps must be a positive integer")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    from .algorithms import topology_for

    seed_everything(0)
    resolved = resolve_device(device)
    model = RankerModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    before = [p.detach().cpu().clone() for p in model.parameters()]
    last_loss = math.inf
    model.train()
    for step in range(steps):
        algorithms = torch.tensor(
            [(step + i) % 32 + 1 for i in range(batch_size)], dtype=torch.long
        )
        feedback = torch.tensor([(step + i) % 8 for i in range(batch_size)], dtype=torch.long)
        operators = torch.zeros(batch_size, 6, 5, dtype=torch.long)
        for b in range(batch_size):
            for op in range(6):
                operators[b, op] = torch.tensor(
                    [(b + op + step) % 32, (b * 7 + op) % 100,
                     (b + op) % 15, (b + op) % 2, (b * 13 + op) % 100],
                    dtype=torch.long,
                )
        signatures = [topology_for(int(a)).topology_signature for a in algorithms.tolist()]
        waveform = (torch.randn(batch_size, 3, 2048, dtype=torch.float32) * 0.1).to(resolved)
        optimizer.zero_grad()
        embeddings_p = model.embed_patches(
            algorithms.to(resolved), feedback.to(resolved), operators.to(resolved), signatures
        )
        embeddings_w = model.embed_frames(frame_coefficients(waveform))
        losses = ranker_loss(embeddings_p, embeddings_w, native_distances(waveform))
        _check_finite_losses(losses)
        losses["loss"].backward()
        optimizer.step()
        last_loss = float(losses["loss"].detach().cpu())
    changed = any(
        not torch.equal(a, b.cpu())
        for a, b in zip(before, [p.detach().cpu() for p in model.parameters()])
    )
    with tempfile.TemporaryDirectory(prefix="dexfrag-ranker-smoke-") as tmp:
        last = Path(tmp) / LAST_FILENAME
        save_checkpoint(last, model, optimizer, epoch=0, completed_epochs=1,
                        global_step=steps, best_val=last_loss)
        revived = RankerModel()
        state = load_checkpoint(last, revived)
    return {"ok": True, "finite": math.isfinite(last_loss), "params_updated": changed,
            "restored_step": state["global_step"], "loss": last_loss}
