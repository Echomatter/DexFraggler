"""Phase 3 forward training engine (train/validation only).

Integrates the existing :class:`dexfrag.forward_data.ForwardDataset`,
:class:`dexfrag.forward_model.ForwardModel`, and
:func:`dexfrag.forward_metrics.forward_loss` without modifying them.

Protected ``test``/``benchmark`` labels are never loaded here: loaders are
hard-wired to the ``train`` and ``validation`` splits with
``allow_protected=False``. There is no split option on the config.
"""

from __future__ import annotations

import math
import os
import random
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from .forward_data import FEATURE_VERSION, ForwardDataset
from .forward_metrics import SCORER_VERSION, forward_loss
from .forward_model import MODEL_VERSION, ForwardModel

__all__ = [
    "TRAIN_SPLITS",
    "TrainConfig",
    "seed_everything",
    "resolve_device",
    "make_loaders",
    "evaluate",
    "save_checkpoint",
    "load_checkpoint",
    "train",
    "smoke_train",
]

TRAIN_SPLITS = ("train", "validation")
BEST_FILENAME = "best.pt"
LAST_FILENAME = "last.pt"


@dataclass
class TrainConfig:
    """Bounded training configuration (CLI-friendly plain fields)."""

    corpus: Path
    checkpoint_dir: Path
    seed: int = 0
    device: str = "cpu"
    epochs: int = 1
    max_steps: int | None = None
    max_rows: int | None = None
    batch_size: int = 4
    learning_rate: float = 1e-3
    num_workers: int = 0
    best_filename: str = BEST_FILENAME
    last_filename: str = LAST_FILENAME
    tensorboard_dir: Path | None = None
    patience: int | None = None

    def __post_init__(self) -> None:
        self.corpus = Path(self.corpus)
        self.checkpoint_dir = Path(self.checkpoint_dir)
        if type(self.seed) is not int:
            raise ValueError("seed must be an int")
        if not isinstance(self.device, str) or not self.device:
            raise ValueError("device must be a nonempty string")
        if type(self.epochs) is not int or self.epochs < 1:
            raise ValueError("epochs must be a positive integer")
        if self.max_steps is not None and (
            type(self.max_steps) is not int or self.max_steps < 1
        ):
            raise ValueError("max_steps must be a positive integer or None")
        if self.max_rows is not None and (
            type(self.max_rows) is not int or self.max_rows < 1
        ):
            raise ValueError("max_rows must be a positive integer or None")
        if type(self.batch_size) is not int or self.batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if (
            not isinstance(self.learning_rate, (int, float))
            or not math.isfinite(float(self.learning_rate))
            or float(self.learning_rate) <= 0
        ):
            raise ValueError("learning_rate must be a positive finite number")
        self.learning_rate = float(self.learning_rate)
        if type(self.num_workers) is not int or self.num_workers < 0:
            raise ValueError("num_workers must be a nonnegative integer")
        for name in ("best_filename", "last_filename"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or "/" in value or "\\" in value:
                raise ValueError(f"{name} must be a plain filename")
        if self.best_filename == self.last_filename:
            raise ValueError("best_filename and last_filename must differ")
        if self.tensorboard_dir is not None and not isinstance(
            self.tensorboard_dir, Path
        ):
            raise ValueError("tensorboard_dir must be a Path or None")
        if self.patience is not None and (
            type(self.patience) is not int or self.patience < 1
        ):
            raise ValueError("patience must be a positive integer or None")

    @property
    def best_path(self) -> Path:
        return self.checkpoint_dir / self.best_filename

    @property
    def last_path(self) -> Path:
        return self.checkpoint_dir / self.last_filename


def seed_everything(seed: int) -> None:
    """Deterministically seed Python, torch (CPU/CUDA) and numpy when present."""
    if type(seed) is not int:
        raise ValueError("seed must be an int")
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    try:
        import numpy as np

        np.random.seed(seed % (2**32))
    except ImportError:
        pass
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def resolve_device(spec: str) -> torch.device:
    """Resolve a device spec string (supports ``"auto"`` -> cuda if available)."""
    if not isinstance(spec, str) or not spec:
        raise ValueError("device must be a nonempty string")
    if spec == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    try:
        device = torch.device(spec)
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"invalid device spec: {spec!r}") from exc
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("device 'cuda' requested but CUDA is not available")
    return device


def make_loaders(
    config: TrainConfig, *, train_shuffle: bool = True
) -> tuple[DataLoader, DataLoader]:
    """Build deterministic train/validation loaders (never protected splits)."""
    train_data = ForwardDataset(
        config.corpus, "train", allow_protected=False, max_rows=config.max_rows
    )
    val_data = ForwardDataset(
        config.corpus, "validation", allow_protected=False, max_rows=config.max_rows
    )
    generator = torch.Generator().manual_seed(config.seed)
    train_loader = DataLoader(
        train_data,
        batch_size=config.batch_size,
        shuffle=train_shuffle,
        num_workers=config.num_workers,
        generator=generator if train_shuffle else None,
    )
    val_loader = DataLoader(
        val_data,
        batch_size=config.batch_size,
        shuffle=False,
        num_workers=config.num_workers,
    )
    return train_loader, val_loader


def _check_finite_losses(losses: dict[str, torch.Tensor]) -> None:
    for name, value in losses.items():
        if not isinstance(value, torch.Tensor) or not torch.isfinite(value).all():
            raise ValueError(f"nonfinite training loss component: {name}")


def _batch_to_device(batch: dict, device: torch.device) -> dict:
    moved = dict(batch)
    for key in ("algorithm", "feedback", "operators", "waveform"):
        moved[key] = batch[key].to(device)
    sigs = batch["topology_signature"]
    moved["topology_signature"] = list(sigs)
    return moved


@torch.no_grad()
def evaluate(model: ForwardModel, loader: DataLoader, device: torch.device) -> dict:
    """Sample-weighted mean validation losses over a loader (eval mode)."""
    model.eval()
    totals = {"loss": 0.0, "waveform_mse": 0.0, "complex_harmonic_mse": 0.0,
              "correlation_loss": 0.0}
    batches = 0
    total_samples = 0
    for raw in loader:
        batch = _batch_to_device(raw, device)
        pred = model.forward_batch(batch)
        losses = forward_loss(pred, batch["waveform"])
        _check_finite_losses(losses)
        count = int(batch["waveform"].shape[0])
        for key in totals:
            totals[key] += float(losses[key].detach().cpu()) * count
        batches += 1
        total_samples += count
    if not batches:
        raise ValueError("empty evaluation loader")
    return (
        {key: value / total_samples for key, value in totals.items()}
        | {"batches": batches, "samples": total_samples}
    )


def _git_commit() -> str:
    """Best-effort git commit hash; empty string when git is unavailable."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def _serializable_train_config(train_config) -> dict | None:
    if train_config is None:
        return None
    if isinstance(train_config, dict):
        out = {}
        for key, value in train_config.items():
            out[str(key)] = str(value) if isinstance(value, Path) else value
        return out
    try:
        raw = asdict(train_config)
    except (TypeError, ValueError):
        return {"repr": str(train_config)}
    out = {}
    for key, value in raw.items():
        out[str(key)] = str(value) if isinstance(value, Path) else value
    return out


def save_checkpoint(
    path: str | Path,
    model: ForwardModel,
    optimizer: torch.optim.Optimizer,
    *,
    epoch: int,
    global_step: int,
    best_val: float,
    completed_epochs: int | None = None,
    train_config: TrainConfig | dict | None = None,
    corpus_path: str | Path | None = None,
    corpus_rows: int | None = None,
) -> Path:
    """Persist a training checkpoint atomically (creates parent directories).

    ``epoch`` is the last epoch index at least partially processed (kept for
    backward compatibility); ``completed_epochs`` counts fully completed
    epochs (defaults to ``epoch + 1`` for end-of-epoch saves). Interrupt
    handlers pass the unchanged pre-epoch count so resume re-runs the
    interrupted epoch.
    """
    path = Path(path)
    if not math.isfinite(best_val):
        # best_val=inf is allowed only for pre-validation interrupt saves;
        # the normal schema requires a finite best. Keep the permissive path
        # so an interrupt before the first validation still checkpoints.
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    epoch = int(epoch)
    if completed_epochs is None:
        completed_epochs = epoch + 1
    payload = {
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "epoch": epoch,
        "completed_epochs": int(completed_epochs),
        "global_step": int(global_step),
        "best_val": float(best_val),
        "model_version": MODEL_VERSION,
        "train_config": _serializable_train_config(train_config),
        "git_commit": _git_commit(),
        "corpus_path": str(corpus_path) if corpus_path is not None else "",
        "corpus_rows": int(corpus_rows) if corpus_rows is not None else None,
        "feature_version": FEATURE_VERSION,
        "scorer_version": SCORER_VERSION,
    }
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
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


def load_checkpoint(
    path: str | Path,
    model: ForwardModel,
    optimizer: torch.optim.Optimizer | None = None,
) -> dict:
    """Load a checkpoint into a model (and optionally its optimizer)."""
    payload = torch.load(Path(path), map_location="cpu", weights_only=True)
    for key in ("model_state", "epoch", "global_step", "best_val"):
        if key not in payload:
            raise ValueError(f"checkpoint is missing required key: {key}")
    saved_version = payload.get("model_version")
    if saved_version is not None and saved_version != MODEL_VERSION:
        raise ValueError(
            f"checkpoint model_version {saved_version!r} does not match "
            f"current {MODEL_VERSION!r}; retrain into a new checkpoint "
            "directory instead of reusing v1 checkpoints (v1 files stay "
            "valid for the v1 model only)"
        )
    model.load_state_dict(payload["model_state"])
    if optimizer is not None and "optimizer_state" in payload:
        optimizer.load_state_dict(payload["optimizer_state"])
    epoch = int(payload["epoch"])
    if "completed_epochs" in payload and isinstance(
        payload["completed_epochs"], (int, float)
    ):
        completed_epochs = int(payload["completed_epochs"])
    else:
        # Legacy checkpoints predate completed_epochs; assume the saved epoch
        # fully completed (matches the historical start_epoch = epoch + 1).
        completed_epochs = epoch + 1
    return {
        "epoch": epoch,
        "completed_epochs": completed_epochs,
        "global_step": int(payload["global_step"]),
        "best_val": float(payload["best_val"]),
        "model_version": payload.get("model_version"),
        "train_config": payload.get("train_config"),
        "git_commit": payload.get("git_commit", ""),
        "corpus_path": payload.get("corpus_path", ""),
        "corpus_rows": payload.get("corpus_rows"),
        "feature_version": payload.get("feature_version"),
        "scorer_version": payload.get("scorer_version"),
    }


def _resume_state(config: TrainConfig) -> tuple[int, int, float]:
    """Recover (start_epoch, global_step, best_val) without touching best.pt."""
    start_epoch = 0
    global_step = 0
    best_val = math.inf

    def _completed(payload: dict) -> int | None:
        if isinstance(payload.get("completed_epochs"), (int, float)):
            return int(payload["completed_epochs"])
        if isinstance(payload.get("epoch"), (int, float)):
            return int(payload["epoch"]) + 1
        return None

    if config.best_path.exists() and not config.last_path.exists():
        try:
            payload = torch.load(config.best_path, map_location="cpu", weights_only=True)
            if isinstance(payload.get("best_val"), (int, float)) and math.isfinite(
                payload["best_val"]
            ):
                best_val = float(payload["best_val"])
        except (OSError, RuntimeError, ValueError):
            pass
    if config.last_path.exists():
        payload = torch.load(config.last_path, map_location="cpu", weights_only=True)
        done = _completed(payload)
        start_epoch = done if done is not None else 0
        global_step = int(payload.get("global_step", 0))
        candidate = payload.get("best_val", math.inf)
        if isinstance(candidate, (int, float)) and math.isfinite(candidate):
            best_val = float(candidate)
        if config.best_path.exists():
            try:
                best_payload = torch.load(
                    config.best_path, map_location="cpu", weights_only=True
                )
                best_candidate = best_payload.get("best_val", math.inf)
                if isinstance(best_candidate, (int, float)) and math.isfinite(
                    best_candidate
                ):
                    best_val = min(best_val, float(best_candidate))
            except (OSError, RuntimeError, ValueError):
                pass
    return start_epoch, global_step, best_val


def train(
    config: TrainConfig,
    model: ForwardModel | None = None,
    optimizer: torch.optim.Optimizer | None = None,
    tensorboard_dir: Path | None = None,
) -> dict:
    """Run bounded train/validation training; returns a JSON-friendly summary.

    Saves ``last.pt`` every epoch (and on early ``max_steps`` stop) and writes
    ``best.pt`` only when validation improves, so resume never overwrites the
    best checkpoint with a worse one. Resumes from ``last.pt`` when present,
    restarting the interrupted epoch from scratch via ``completed_epochs``.

    When ``tensorboard_dir`` (or ``config.tensorboard_dir``) is provided,
    per-epoch scalars are logged with TensorBoard. A ``KeyboardInterrupt``
    anywhere inside a per-epoch block (training or validation) still saves
    the current ``last.pt`` with the pre-epoch ``completed_epochs`` count
    before re-raising.

    When ``config.patience`` is set, training stops early after ``patience``
    consecutive epochs without validation improvement; ``last.pt`` is saved
    before stopping.
    """
    seed_everything(config.seed)
    device = resolve_device(config.device)
    train_loader, val_loader = make_loaders(config)
    if model is None:
        model = ForwardModel()
    if optimizer is None:
        optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    model.to(device)
    try:
        corpus_rows = len(train_loader.dataset) + len(val_loader.dataset)
    except (TypeError, AttributeError):
        corpus_rows = None

    def _provenance() -> dict:
        return {
            "train_config": config,
            "corpus_path": config.corpus,
            "corpus_rows": corpus_rows,
        }

    start_epoch, global_step, best_val = 0, 0, math.inf
    if config.last_path.exists():
        restored = load_checkpoint(config.last_path, model, optimizer)
        model.to(device)
        start_epoch, global_step = restored["completed_epochs"], restored["global_step"]
        best_val = restored["best_val"]
        if config.best_path.exists():
            try:
                best_payload = torch.load(
                    config.best_path, map_location="cpu", weights_only=True
                )
                candidate = best_payload.get("best_val", math.inf)
                if isinstance(candidate, (int, float)) and math.isfinite(candidate):
                    best_val = min(best_val, float(candidate))
            except (OSError, RuntimeError, ValueError):
                pass
    elif config.best_path.exists():
        # Prior best is preserved as the threshold even without a last resume.
        _, _, best_val = _resume_state(config)
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
                    pred = model.forward_batch(batch)
                    losses = forward_loss(pred, batch["waveform"])
                    _check_finite_losses(losses)
                    losses["loss"].backward()
                    optimizer.step()
                    global_step += 1
                    train_total += float(losses["loss"].detach().cpu())
                    train_batches += 1
                if train_batches == 0:
                    break
                val = evaluate(model, val_loader, device)
                if not math.isfinite(val["loss"]):
                    raise ValueError("nonfinite validation loss")
                improved = val["loss"] < best_val
                if improved:
                    best_val = val["loss"]
                    epochs_no_improve = 0
                else:
                    epochs_no_improve += 1
                record = {
                    "epoch": epoch,
                    "global_step": global_step,
                    "train_loss": train_total / train_batches,
                    "val_loss": val["loss"],
                    "val_detail": val,
                    "best_val": best_val,
                    "improved": improved,
                }
                history.append(record)
                epochs_run += 1
                completed_epochs = epoch + 1
                save_checkpoint(
                    config.last_path, model, optimizer,
                    epoch=epoch, completed_epochs=completed_epochs,
                    global_step=global_step, best_val=best_val,
                    **_provenance(),
                )
                if improved:
                    # Best is written only on strict improvement; never clobbered.
                    save_checkpoint(
                        config.best_path, model, optimizer,
                        epoch=epoch, completed_epochs=completed_epochs,
                        global_step=global_step, best_val=best_val,
                        **_provenance(),
                    )
                if writer is not None:
                    writer.add_scalar("train_loss", record["train_loss"], epoch)
                    writer.add_scalar("val_loss", record["val_loss"], epoch)
                    writer.add_scalar("best_val", record["best_val"], epoch)
                    writer.add_scalar(
                        "learning_rate", float(optimizer.param_groups[0]["lr"]), epoch
                    )
                    writer.add_scalar("global_step", global_step, epoch)
                    writer.flush()
                if stopped_early:
                    break
                if config.patience is not None and epochs_no_improve >= config.patience:
                    early_stopped = True
                    break
            except KeyboardInterrupt:
                # Interrupt-safe checkpoint (atomic write): persist the
                # current epoch's weights with the pre-epoch completed
                # count so resume re-runs the interrupted epoch.
                save_checkpoint(
                    config.last_path, model, optimizer,
                    epoch=epoch, completed_epochs=completed_epochs,
                    global_step=global_step, best_val=best_val,
                    **_provenance(),
                )
                raise
    finally:
        if writer is not None:
            writer.close()

    return {
        "best_val": best_val,
        "epochs_run": epochs_run,
        "global_step": global_step,
        "history": history,
        "last_checkpoint": str(config.last_path) if config.last_path.exists() else None,
        "best_checkpoint": str(config.best_path) if config.best_path.exists() else None,
        "model_version": MODEL_VERSION,
        "device": str(device),
        "train_batches": len(train_loader),
        "val_batches": len(val_loader),
        "early_stopped": early_stopped,
        "completed_epochs": completed_epochs,
    }


def smoke_train(
    *,
    device: str = "cpu",
    steps: int = 3,
    batch_size: int = 2,
    tensorboard_dir: Path | None = None,
) -> dict:
    """Tiny corpus-free wiring smoke: synthetic batches, grad steps, checkpoint.

    Suitable as a later CLI smoke hook; proves finite losses, parameter updates,
    and checkpoint save/resume without touching protected labels or disk corpora.
    When ``tensorboard_dir`` is provided, the final smoke loss is logged there.
    """
    if type(steps) is not int or steps < 1:
        raise ValueError("steps must be a positive integer")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    from .algorithms import topology_for

    seed_everything(0)
    resolved = resolve_device(device)
    model = ForwardModel(hidden_dims=(32, 32), algorithm_dim=4).to(resolved)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    before = [p.detach().cpu().clone() for p in model.parameters()]
    last_loss = math.inf
    model.train()
    for step in range(steps):
        algorithms = torch.tensor(
            [(step + i) % 32 + 1 for i in range(batch_size)], dtype=torch.long
        )
        feedback = torch.tensor(
            [(step + i) % 8 for i in range(batch_size)], dtype=torch.long
        )
        operators = torch.zeros(batch_size, 6, 5, dtype=torch.long)
        for b in range(batch_size):
            for op in range(6):
                operators[b, op] = torch.tensor(
                    [(b + op + step) % 32, (b * 7 + op) % 100,
                     (b + op) % 15, (b + op) % 2, (b * 13 + op) % 100],
                    dtype=torch.long,
                )
        signatures = [
            topology_for(int(a)).topology_signature for a in algorithms.tolist()
        ]
        target = (torch.randn(batch_size, 3, 2048, dtype=torch.float32) * 0.1).to(
            resolved
        )
        batch = {
            "algorithm": algorithms.to(resolved),
            "feedback": feedback.to(resolved),
            "operators": operators.to(resolved),
            "topology_signature": signatures,
            "waveform": target,
        }
        optimizer.zero_grad()
        pred = model.forward_batch(batch)
        losses = forward_loss(pred, batch["waveform"])
        _check_finite_losses(losses)
        assert pred.shape == (batch_size, 3, 2048)
        losses["loss"].backward()
        optimizer.step()
        last_loss = float(losses["loss"].detach().cpu())
    changed = any(
        not torch.equal(a, b.cpu())
        for a, b in zip(before, [p.detach().cpu() for p in model.parameters()])
    )
    with tempfile.TemporaryDirectory(prefix="dexfrag-smoke-") as tmp:
        last = Path(tmp) / LAST_FILENAME
        save_checkpoint(
            last, model, optimizer, epoch=0, global_step=steps, best_val=last_loss
        )
        revived = ForwardModel(hidden_dims=(32, 32), algorithm_dim=4)
        state = load_checkpoint(last, revived)
    if tensorboard_dir is not None:
        if not isinstance(tensorboard_dir, Path):
            raise ValueError("tensorboard_dir must be a Path or None")
        from torch.utils.tensorboard import SummaryWriter

        writer = SummaryWriter(log_dir=str(tensorboard_dir))
        try:
            writer.add_scalar("smoke_loss", last_loss, steps)
            writer.flush()
        finally:
            writer.close()
    return {
        "ok": True,
        "steps": steps,
        "loss": last_loss,
        "finite": math.isfinite(last_loss),
        "params_updated": changed,
        "restored_step": state["global_step"],
    }
