"""Bounded, resumable Phase 4 proposer training."""
from __future__ import annotations

import math
import os
import random
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from .features import FEATURE_VERSION
from .forward_training import resolve_device, seed_everything
from .proposer_data import ProposerDataset
from .proposer_metrics import LOSS_VERSION, attach_training_targets, proposer_loss
from .proposer_model import MODEL_VERSION, ProposerModel, candidate_diversity, generate_candidates


BEST_FILENAME = "best.pt"
LAST_FILENAME = "last.pt"


@dataclass
class ProposerTrainConfig:
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
    max_seconds: float | None = None
    candidate_count: int = 16
    label_smoothing: float = 0.05

    def __post_init__(self) -> None:
        self.corpus = Path(self.corpus)
        self.checkpoint_dir = Path(self.checkpoint_dir)
        if type(self.seed) is not int:
            raise ValueError("seed must be an int")
        if not isinstance(self.device, str) or not self.device:
            raise ValueError("device must be a nonempty string")
        if type(self.epochs) is not int or self.epochs < 1:
            raise ValueError("epochs must be a positive integer")
        if self.max_steps is not None and (type(self.max_steps) is not int or self.max_steps < 1):
            raise ValueError("max_steps must be a positive integer or None")
        if self.max_rows is not None and (type(self.max_rows) is not int or self.max_rows < 2):
            raise ValueError("max_rows must be an integer of at least 2 or None")
        if type(self.batch_size) is not int or self.batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if not isinstance(self.learning_rate, (int, float)) or not math.isfinite(float(self.learning_rate)) or self.learning_rate <= 0:
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
        if self.tensorboard_dir is not None and not isinstance(self.tensorboard_dir, Path):
            raise ValueError("tensorboard_dir must be a Path or None")
        if self.patience is not None and (type(self.patience) is not int or self.patience < 1):
            raise ValueError("patience must be a positive integer or None")
        if self.max_seconds is not None and (not isinstance(self.max_seconds, (int, float)) or not math.isfinite(float(self.max_seconds)) or self.max_seconds <= 0):
            raise ValueError("max_seconds must be a positive finite number or None")
        if type(self.candidate_count) is not int or not 1 <= self.candidate_count <= 256:
            raise ValueError("candidate_count must be an integer from 1 to 256")
        if not math.isfinite(self.label_smoothing) or not 0.0 <= self.label_smoothing < 1.0:
            raise ValueError("label_smoothing must be in [0, 1)")

    @property
    def best_path(self) -> Path:
        return self.checkpoint_dir / self.best_filename

    @property
    def last_path(self) -> Path:
        return self.checkpoint_dir / self.last_filename


def _split_limits(max_rows: int | None) -> tuple[int | None, int | None]:
    if max_rows is None:
        return None, None
    train_rows = max(1, int(max_rows * 0.9))
    validation_rows = max(1, max_rows - train_rows)
    if train_rows + validation_rows > max_rows:
        train_rows = max(1, max_rows - validation_rows)
    return train_rows, validation_rows


def make_loaders(config: ProposerTrainConfig, *, train_shuffle: bool = True) -> tuple[DataLoader, DataLoader]:
    train_limit, validation_limit = _split_limits(config.max_rows)
    train_data = ProposerDataset(config.corpus, "train", max_rows=train_limit)
    validation_data = ProposerDataset(config.corpus, "validation", max_rows=validation_limit)
    generator = torch.Generator().manual_seed(config.seed)
    train_loader = DataLoader(
        train_data,
        batch_size=config.batch_size,
        shuffle=train_shuffle,
        num_workers=config.num_workers,
        generator=generator if train_shuffle else None,
    )
    validation_loader = DataLoader(
        validation_data,
        batch_size=config.batch_size,
        shuffle=False,
        num_workers=config.num_workers,
    )
    return train_loader, validation_loader


def _batch_to_device(batch: dict, device: torch.device) -> dict:
    moved = dict(batch)
    for key in ("algorithm", "feedback", "operators", "waveform"):
        moved[key] = batch[key].to(device)
    if "topology_signature" in batch:
        moved["topology_signature"] = list(batch["topology_signature"])
    return moved


def _finite_losses(losses: dict[str, torch.Tensor]) -> None:
    for name, value in losses.items():
        if not isinstance(value, torch.Tensor) or not torch.isfinite(value).all():
            raise ValueError(f"nonfinite proposer loss component: {name}")


@torch.no_grad()
def evaluate(model: ProposerModel, loader: DataLoader, device: torch.device,
             *, label_smoothing: float = 0.05) -> dict:
    model.eval()
    totals: dict[str, float] = {}
    total_samples = 0
    batches = 0
    for raw in loader:
        batch = _batch_to_device(raw, device)
        outputs = model(batch["waveform"])
        labeled = attach_training_targets(
            outputs,
            algorithm=batch["algorithm"],
            feedback=batch["feedback"],
            operators=batch["operators"],
        )
        losses = proposer_loss(labeled, label_smoothing=label_smoothing)
        _finite_losses(losses)
        count = len(batch["waveform"])
        for key, value in losses.items():
            totals[key] = totals.get(key, 0.0) + float(value.detach().cpu()) * count
        total_samples += count
        batches += 1
    if not batches or not total_samples:
        raise ValueError("empty proposer evaluation loader")
    result = {key: value / total_samples for key, value in totals.items()}
    result.update({"batches": batches, "samples": total_samples})
    return result


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def _serializable_config(config: ProposerTrainConfig) -> dict:
    raw = asdict(config)
    return {key: str(value) if isinstance(value, Path) else value for key, value in raw.items()}


def checkpoint_model_config(path: str | Path) -> dict[str, int]:
    path = Path(path)
    payload = torch.load(path, map_location="cpu", weights_only=True)
    raw = payload.get("model_config", {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("proposer checkpoint model_config must be a mapping")
    allowed = {"algorithm_dim", "hidden_dim", "harmonic_bands", "conv_channels"}
    if set(raw) - allowed:
        raise ValueError("proposer checkpoint has unknown model_config fields")
    result = {}
    for key, value in raw.items():
        if type(value) is not int or value <= 0:
            raise ValueError(f"proposer checkpoint model_config {key} must be a positive integer")
        result[key] = value
    return result


def save_checkpoint(path: str | Path, model: ProposerModel, optimizer: torch.optim.Optimizer, *,
                    epoch: int, completed_epochs: int, global_step: int, best_val: float,
                    config: ProposerTrainConfig | dict | None = None,
                    corpus_path: str | Path | None = None, corpus_rows: int | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "model_config": model.architecture_config(),
        "epoch": int(epoch),
        "completed_epochs": int(completed_epochs),
        "global_step": int(global_step),
        "best_val": float(best_val),
        "model_version": MODEL_VERSION,
        "loss_version": LOSS_VERSION,
        "feature_version": FEATURE_VERSION,
        "train_config": _serializable_config(config) if isinstance(config, ProposerTrainConfig) else config,
        "git_commit": _git_commit(),
        "corpus_path": str(corpus_path) if corpus_path is not None else "",
        "corpus_rows": int(corpus_rows) if corpus_rows is not None else None,
    }
    fd, temporary_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            torch.save(payload, handle)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return path


def load_checkpoint(path: str | Path, model: ProposerModel,
                    optimizer: torch.optim.Optimizer | None = None) -> dict:
    payload = torch.load(Path(path), map_location="cpu", weights_only=True)
    for key in ("model_state", "epoch", "global_step", "best_val"):
        if key not in payload:
            raise ValueError(f"proposer checkpoint is missing required key: {key}")
    if payload.get("model_version") not in (None, MODEL_VERSION):
        raise ValueError("proposer checkpoint model version is incompatible")
    if payload.get("loss_version") not in (None, LOSS_VERSION):
        raise ValueError("proposer checkpoint loss version is incompatible")
    model.load_state_dict(payload["model_state"])
    if optimizer is not None and "optimizer_state" in payload:
        optimizer.load_state_dict(payload["optimizer_state"])
    return {
        "epoch": int(payload["epoch"]),
        "completed_epochs": int(payload.get("completed_epochs", int(payload["epoch"]) + 1)),
        "global_step": int(payload["global_step"]),
        "best_val": float(payload["best_val"]),
        "model_version": payload.get("model_version"),
        "loss_version": payload.get("loss_version"),
        "model_config": payload.get("model_config", {}),
        "feature_version": payload.get("feature_version"),
        "train_config": payload.get("train_config"),
        "git_commit": payload.get("git_commit", ""),
        "corpus_path": payload.get("corpus_path", ""),
        "corpus_rows": payload.get("corpus_rows"),
    }


def _resume_state(config: ProposerTrainConfig) -> tuple[int, int, float]:
    start_epoch = 0
    global_step = 0
    best_val = math.inf
    if config.last_path.exists():
        payload = torch.load(config.last_path, map_location="cpu", weights_only=True)
        start_epoch = int(payload.get("completed_epochs", int(payload.get("epoch", -1)) + 1))
        global_step = int(payload.get("global_step", 0))
        candidate = payload.get("best_val", math.inf)
        if isinstance(candidate, (int, float)) and math.isfinite(candidate):
            best_val = float(candidate)
    for path in (config.best_path, config.last_path):
        if path.exists():
            try:
                payload = torch.load(path, map_location="cpu", weights_only=True)
                candidate = payload.get("best_val", math.inf)
                if isinstance(candidate, (int, float)) and math.isfinite(candidate):
                    best_val = min(best_val, float(candidate))
            except (OSError, RuntimeError, ValueError):
                pass
    return start_epoch, global_step, best_val


def _notify(callback, event: dict) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        pass  # a UI reporting failure must never abort training


def train(config: ProposerTrainConfig, model: ProposerModel | None = None,
          optimizer: torch.optim.Optimizer | None = None,
          tensorboard_dir: Path | None = None,
          progress_callback=None, stop_requested=None) -> dict:
    """Train on train/validation splits with atomic resume and early stopping."""
    for name, callback in (("progress_callback", progress_callback), ("stop_requested", stop_requested)):
        if callback is not None and not callable(callback):
            raise ValueError(f"{name} must be callable or None")
    seed_everything(config.seed)
    device = resolve_device(config.device)
    train_loader, validation_loader = make_loaders(config)
    if model is None:
        if config.last_path.exists():
            model = ProposerModel(**checkpoint_model_config(config.last_path))
        else:
            model = ProposerModel()
    optimizer = optimizer or torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    model.to(device)
    corpus_rows = len(train_loader.dataset) + len(validation_loader.dataset)
    start_epoch, global_step, best_val = _resume_state(config)
    if config.last_path.exists():
        load_checkpoint(config.last_path, model, optimizer)
        model.to(device)
    completed_epochs = start_epoch
    epochs_run = 0
    epochs_without_improvement = 0
    early_stopped = False
    wall_clock_stopped = False
    stopped = False
    _notify(progress_callback, {
        "event": "ready",
        "epochs": config.epochs,
        "start_epoch": start_epoch,
        "train_batches": len(train_loader),
        "val_batches": len(validation_loader),
        "train_samples": len(train_loader.dataset),
        "val_samples": len(validation_loader.dataset),
        "global_step": global_step,
        "best_val": best_val,
    })
    history: list[dict] = []
    effective_tensorboard_dir = tensorboard_dir if tensorboard_dir is not None else config.tensorboard_dir
    if effective_tensorboard_dir is not None and not isinstance(effective_tensorboard_dir, Path):
        raise ValueError("tensorboard_dir must be a Path or None")
    writer = None
    if effective_tensorboard_dir is not None:
        from torch.utils.tensorboard import SummaryWriter

        writer = SummaryWriter(log_dir=str(effective_tensorboard_dir))
    started = time.monotonic()
    try:
        for epoch in range(start_epoch, config.epochs):
            if stop_requested is not None and stop_requested():
                stopped = True
                break
            _notify(progress_callback, {
                "event": "epoch_start", "epoch": epoch + 1, "epochs": config.epochs,
                "global_step": global_step, "best_val": best_val,
            })
            if config.max_steps is not None and global_step >= config.max_steps:
                break
            if config.max_seconds is not None and time.monotonic() - started >= config.max_seconds:
                wall_clock_stopped = True
                break
            partial_epoch = False
            train_totals: dict[str, float] = {}
            train_batches = 0
            train_samples_seen = 0
            try:
                model.train()
                for raw in train_loader:
                    if config.max_steps is not None and global_step >= config.max_steps:
                        partial_epoch = True
                        break
                    if config.max_seconds is not None and time.monotonic() - started >= config.max_seconds:
                        partial_epoch = True
                        wall_clock_stopped = True
                        break
                    if stop_requested is not None and stop_requested():
                        partial_epoch = True
                        stopped = True
                        break
                    batch = _batch_to_device(raw, device)
                    optimizer.zero_grad()
                    outputs = model(batch["waveform"])
                    labeled = attach_training_targets(
                        outputs,
                        algorithm=batch["algorithm"],
                        feedback=batch["feedback"],
                        operators=batch["operators"],
                    )
                    losses = proposer_loss(labeled, label_smoothing=config.label_smoothing)
                    _finite_losses(losses)
                    losses["loss"].backward()
                    optimizer.step()
                    global_step += 1
                    train_batches += 1
                    train_samples_seen += len(batch["waveform"])
                    for key, value in losses.items():
                        train_totals[key] = train_totals.get(key, 0.0) + float(value.detach().cpu())
                    _notify(progress_callback, {
                        "event": "step",
                        "epoch": epoch + 1,
                        "epochs": config.epochs,
                        "batch": train_batches,
                        "batches": len(train_loader),
                        "samples_seen": train_samples_seen,
                        "train_samples": len(train_loader.dataset),
                        "global_step": global_step,
                        "loss": train_totals["loss"] / train_batches,
                        "best_val": best_val,
                    })
                if partial_epoch:
                    save_checkpoint(
                        config.last_path, model, optimizer, epoch=epoch,
                        completed_epochs=completed_epochs, global_step=global_step,
                        best_val=best_val, config=config, corpus_path=config.corpus,
                        corpus_rows=corpus_rows,
                    )
                    break
                if not train_batches:
                    break
                _notify(progress_callback, {
                    "event": "validation", "epoch": epoch + 1, "epochs": config.epochs,
                    "global_step": global_step, "best_val": best_val,
                })
                validation = evaluate(
                    model, validation_loader, device,
                    label_smoothing=config.label_smoothing,
                )
                if not math.isfinite(validation["loss"]):
                    raise ValueError("nonfinite proposer validation loss")
                improved = validation["loss"] < best_val
                if improved:
                    best_val = validation["loss"]
                    epochs_without_improvement = 0
                else:
                    epochs_without_improvement += 1
                record = {
                    "epoch": epoch,
                    "global_step": global_step,
                    "train_loss": train_totals["loss"] / train_batches,
                    "val_loss": validation["loss"],
                    "val_detail": validation,
                    "best_val": best_val,
                    "improved": improved,
                }
                history.append(record)
                epochs_run += 1
                completed_epochs = epoch + 1
                _notify(progress_callback, {
                    "event": "epoch_end",
                    "epoch": epoch + 1,
                    "epochs": config.epochs,
                    "train_loss": record["train_loss"],
                    "val_loss": record["val_loss"],
                    "best_val": best_val,
                    "improved": improved,
                    "global_step": global_step,
                })
                save_checkpoint(
                    config.last_path, model, optimizer, epoch=epoch,
                    completed_epochs=completed_epochs, global_step=global_step,
                    best_val=best_val, config=config, corpus_path=config.corpus,
                    corpus_rows=corpus_rows,
                )
                if improved:
                    save_checkpoint(
                        config.best_path, model, optimizer, epoch=epoch,
                        completed_epochs=completed_epochs, global_step=global_step,
                        best_val=best_val, config=config, corpus_path=config.corpus,
                        corpus_rows=corpus_rows,
                    )
                if writer is not None:
                    for key in ("loss", "algorithm_loss", "feedback_loss", "parameter_loss",
                                "algorithm_accuracy", "feedback_accuracy", "operator_accuracy",
                                "algorithm_entropy", "mean_head_entropy"):
                        writer.add_scalar(f"train/{key}", record["train_loss"] if key == "loss" else train_totals[key] / train_batches, epoch)
                        writer.add_scalar(f"validation/{key}", validation[key], epoch)
                    writer.add_scalar("training/global_step", global_step, epoch)
                    writer.flush()
                if config.patience is not None and epochs_without_improvement >= config.patience:
                    early_stopped = True
                    break
            except KeyboardInterrupt:
                save_checkpoint(
                    config.last_path, model, optimizer, epoch=epoch,
                    completed_epochs=completed_epochs, global_step=global_step,
                    best_val=best_val, config=config, corpus_path=config.corpus,
                    corpus_rows=corpus_rows,
                )
                raise
    finally:
        if writer is not None:
            writer.close()
    smoke_target = validation_loader.dataset[0]["waveform"].to(device)
    smoke_candidates = generate_candidates(
        model, smoke_target, count=config.candidate_count, seed=config.seed
    )
    smoke_candidate_metrics = candidate_diversity(smoke_candidates)
    result = {
        "best_val": best_val,
        "stopped": stopped,
        "epochs_run": epochs_run,
        "global_step": global_step,
        "history": history,
        "last_checkpoint": str(config.last_path) if config.last_path.exists() else None,
        "best_checkpoint": str(config.best_path) if config.best_path.exists() else None,
        "model_version": MODEL_VERSION,
        "loss_version": LOSS_VERSION,
        "device": str(device),
        "train_batches": len(train_loader),
        "val_batches": len(validation_loader),
        "early_stopped": early_stopped,
        "wall_clock_stopped": wall_clock_stopped,
        "completed_epochs": completed_epochs,
        "parameter_count": model.count_parameters(),
        "model_config": model.architecture_config(),
        "candidate_count": config.candidate_count,
        "smoke_candidate_metrics": smoke_candidate_metrics,
    }
    _notify(progress_callback, {"event": "finished", "result": result})
    return result


def smoke_train(*, device: str = "cpu", steps: int = 3, batch_size: int = 2,
                tensorboard_dir: Path | None = None) -> dict:
    """Corpus-free wiring smoke for gradients, checkpoints, and legal decoding."""
    if type(steps) is not int or steps < 1:
        raise ValueError("steps must be a positive integer")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    seed_everything(0)
    resolved = resolve_device(device)
    model = ProposerModel(algorithm_dim=4, hidden_dim=16, harmonic_bands=8, conv_channels=4).to(resolved)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    before = [parameter.detach().cpu().clone() for parameter in model.parameters()]
    waveform = torch.randn(batch_size, 3, 2048, dtype=torch.float32, device=resolved) * 0.1
    algorithm = torch.tensor([(index % 32) + 1 for index in range(batch_size)], dtype=torch.long, device=resolved)
    feedback = torch.tensor([index % 8 for index in range(batch_size)], dtype=torch.long, device=resolved)
    operators = torch.zeros(batch_size, 6, 5, dtype=torch.long, device=resolved)
    for batch_index in range(batch_size):
        for op_index in range(6):
            operators[batch_index, op_index] = torch.tensor(
                [(batch_index + op_index) % 32, (batch_index * 7 + op_index) % 100,
                 (batch_index + op_index) % 15, (batch_index + op_index) % 2,
                 (batch_index * 13 + op_index) % 100], dtype=torch.long, device=resolved
            )
    last_loss = math.inf
    model.train()
    for _ in range(steps):
        optimizer.zero_grad()
        outputs = model(waveform)
        labeled = attach_training_targets(outputs, algorithm=algorithm, feedback=feedback, operators=operators)
        losses = proposer_loss(labeled)
        _finite_losses(losses)
        losses["loss"].backward()
        optimizer.step()
        last_loss = float(losses["loss"].detach().cpu())
    changed = any(
        not torch.equal(left, right.detach().cpu())
        for left, right in zip(before, model.parameters())
    )
    candidates = generate_candidates(model, waveform[0].detach().cpu(), count=8, seed=3)
    with tempfile.TemporaryDirectory(prefix="dexfrag-proposer-smoke-") as temporary:
        path = Path(temporary) / LAST_FILENAME
        save_checkpoint(path, model, optimizer, epoch=0, completed_epochs=1,
                        global_step=steps, best_val=last_loss)
        revived = ProposerModel(algorithm_dim=4, hidden_dim=16, harmonic_bands=8, conv_channels=4)
        state = load_checkpoint(path, revived)
    if tensorboard_dir is not None:
        if not isinstance(tensorboard_dir, Path):
            raise ValueError("tensorboard_dir must be a Path or None")
        from torch.utils.tensorboard import SummaryWriter

        writer = SummaryWriter(log_dir=str(tensorboard_dir))
        try:
            writer.add_scalar("smoke/proposer_loss", last_loss, steps)
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
        "candidate_count": len(candidates),
        "candidate_metrics": candidate_diversity(candidates),
    }
