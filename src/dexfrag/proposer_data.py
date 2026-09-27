"""Waveform-only dataset adapters for the Phase 4 inverse proposer."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from .features import FEATURE_VERSION, FORBIDDEN_TARGET_KEYS
from .forward_data import ForwardDataset
from .storage import TARGET_RECORD_SCHEMA_VERSION, read_target_records


FRAME_LENGTH = 2048


def _target_waveform_from_features(features: dict) -> torch.Tensor:
    if not isinstance(features, dict) or features.get("version") != FEATURE_VERSION:
        raise ValueError("target features have an unsupported feature version")
    forbidden = FORBIDDEN_TARGET_KEYS & set(features)
    if forbidden:
        raise ValueError(f"target features contain forbidden provenance: {sorted(forbidden)}")
    frame_length = features.get("frame_length")
    if type(frame_length) is not int or frame_length != FRAME_LENGTH:
        raise ValueError("target features must describe a 2048-sample frame")
    samples = features.get("samples")
    if samples is not None:
        if not isinstance(samples, list) or len(samples) != FRAME_LENGTH:
            raise ValueError("target samples must contain 2048 values")
        if any(type(value) not in (int, float) or not math.isfinite(float(value)) for value in samples):
            raise ValueError("target samples must be finite numbers")
        return torch.tensor(samples, dtype=torch.float32).unsqueeze(0)
    sin_values = features.get("sin_coefficients")
    cos_values = features.get("cos_coefficients")
    if not isinstance(sin_values, list) or not isinstance(cos_values, list) or not sin_values:
        raise ValueError("target features need samples or harmonic coefficients")
    if len(sin_values) != len(cos_values):
        raise ValueError("target harmonic coefficient lengths must match")
    sin_array = np.asarray(sin_values, dtype=np.float64)
    cos_array = np.asarray(cos_values, dtype=np.float64)
    if not np.isfinite(sin_array).all() or not np.isfinite(cos_array).all():
        raise ValueError("target harmonic coefficients must be finite")
    indices = np.arange(FRAME_LENGTH, dtype=np.float64)
    harmonics = np.arange(1, len(sin_array) + 1, dtype=np.float64)
    theta = np.outer(harmonics, indices) * (2.0 * math.pi / FRAME_LENGTH)
    waveform = sin_array @ np.sin(theta) + cos_array @ np.cos(theta)
    return torch.tensor(waveform, dtype=torch.float32).unsqueeze(0)


class ProposerDataset(Dataset):
    """Native observations exposed as waveform inputs and patch labels.

    Protected splits remain gated by :class:`ForwardDataset`; only explicitly
    authorized evaluation code should pass ``allow_protected=True``.
    """

    def __init__(self, path: str | Path, split: str = "train", *,
                 allow_protected: bool = False, max_rows: int | None = None):
        self.source = ForwardDataset(path, split, allow_protected=allow_protected, max_rows=max_rows)
        self.split = split
        self.items = []
        for item in self.source.items:
            copied = dict(item)
            copied["target_hash"] = item["key"]
            self.items.append(copied)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> dict:
        item = self.items[index]
        return {key: value.clone() if isinstance(value, torch.Tensor) else value
                for key, value in item.items()}


class ProposerTargetDataset(Dataset):
    """Black-box target records containing waveform-derived inputs only."""

    def __init__(self, path: str | Path, *, max_rows: int | None = None):
        if max_rows is not None and (type(max_rows) is not int or max_rows <= 0):
            raise ValueError("max_rows must be a positive integer or None")
        table = read_target_records(path)
        if table.num_rows == 0:
            raise ValueError("target store contains no records")
        self.items = []
        for row in table.to_pylist():
            if row.get("schema_version") != TARGET_RECORD_SCHEMA_VERSION:
                raise ValueError("target store has an unsupported schema version")
            try:
                features = json.loads(row["features_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("target features must be valid JSON") from exc
            waveform = _target_waveform_from_features(features)
            target_hash = row.get("target_hash")
            if not isinstance(target_hash, str) or not target_hash:
                raise ValueError("target record has no target_hash")
            self.items.append({"target_hash": target_hash, "waveform": waveform})
            if max_rows is not None and len(self.items) >= max_rows:
                break

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> dict:
        item = self.items[index]
        return {"target_hash": item["target_hash"], "waveform": item["waveform"].clone()}
