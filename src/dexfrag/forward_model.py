"""Phase 3 forward-model core: shared-MLP patch-to-harmonics surrogate.

Maps legal DX7 patch state to phase-bearing canonical waveforms
``[B, 3, 2048]`` (notes 45/57/69, native amplitude, phase preserved).

The trunk predicts per-note sine/cosine harmonic coefficients; a fixed,
deterministic Fourier synthesis stage (the exact inverse of the
:func:`dexfrag.features.canonical_frame` label-generating process) renders
the waveform. The model therefore never has to rediscover periodic
structure from data -- it learns only the patch-to-harmonic mapping, which
is what FM synthesis actually parameterizes.

Inputs mirror :class:`dexfrag.forward_data.ForwardDataset` item fields:

- ``algorithm``: 1-based categorical ID (1..32) via embedding, never a
  normalized scalar or row index. One shared trunk covers all algorithms.
- ``feedback``: legal 0..7, normalized to ``[0, 1]`` by ``/ 7``.
- ``operators``: ``[B, 6, 5]`` canonical OP1..OP6 ordering, columns
  ``(coarse, fine, detune, mode, level)``, each normalized by its legal
  maximum (31, 99, 14, 1, 99).
- ``topology_signature``: stable per-algorithm descriptor string, encoded
  deterministically (SHA-256 digest bytes scaled to ``[0, 1]``). It is a
  pure function of the algorithm; the hash encoding keeps the model input
  fixed-width without learning 32 separate paths.
- ``waveform``: training target only, never consumed by the model.

Determinism: encoding functions are pure (no RNG, no hidden state). The
module itself uses a feed-forward MLP with ReLU activations and a linear
head so phase and amplitude pass through unnormalized. Dropout / sampling
layers are deliberately absent.
"""
from __future__ import annotations

import hashlib
import math

import torch
from torch import nn

MODEL_VERSION = "dexfrag-forward-mlp-v2"
FRAME_LENGTH = 2048
NOTE_COUNT = 3
# Notes and sample rate of the canonical label contract (ForwardDataset
# rejects frames that disagree). Band counts derive from these, so any
# contract change must update both here and the pinning test.
NOTE_MIDIS = (45, 57, 69)
LABEL_SAMPLE_RATE = 48000
ALGORITHM_COUNT = 32
FEEDBACK_MAX = 7
# Canonical column order used by ForwardDataset item["operators"].
OPERATOR_FIELDS = ("coarse", "fine", "detune", "mode", "level")
OPERATOR_MAX = {"coarse": 31, "fine": 99, "detune": 14, "mode": 1, "level": 99}
TOPO_DIM = 8


def _check_long(value: torch.Tensor, name: str) -> None:
    if not isinstance(value, torch.Tensor) or value.dtype != torch.long:
        raise ValueError(f"{name} must be a torch.long tensor")


def normalize_feedback(feedback: torch.Tensor) -> torch.Tensor:
    """Normalize legal feedback values 0..7 to ``[0, 1]`` float32 ``[B, 1]`."""
    _check_long(feedback, "feedback")
    if feedback.ndim != 1 or not len(feedback):
        raise ValueError("feedback must have nonempty shape [B]")
    if bool((feedback < 0).any() or (feedback > FEEDBACK_MAX).any()):
        raise ValueError("feedback must hold integers 0..7")
    return (feedback.to(torch.float32) / float(FEEDBACK_MAX)).unsqueeze(-1)


def normalize_operators(operators: torch.Tensor) -> torch.Tensor:
    """Normalize raw legal operator parameters to ``[0, 1]``.

    Expects ``[B, 6, 5]`` long tensor with columns
    ``(coarse, fine, detune, mode, level)`` in canonical OP1..OP6 row order.
    Returns float32 ``[B, 6, 5]`` with each column divided by its legal max.
    """
    _check_long(operators, "operators")
    if operators.ndim != 3 or tuple(operators.shape[1:]) != (6, 5) or not len(operators):
        raise ValueError("operators must have nonempty shape [B, 6, 5]")
    maxima = torch.tensor([OPERATOR_MAX[f] for f in OPERATOR_FIELDS],
                          dtype=torch.float32, device=operators.device)
    minima_ok = bool((operators >= 0).all())
    maxima_ok = bool((operators.to(torch.float32) <= maxima).all())
    if not (minima_ok and maxima_ok):
        raise ValueError("operators hold values outside legal DX7 ranges")
    return operators.to(torch.float32) / maxima


def topology_features(signatures: list[str] | tuple[str, ...]) -> torch.Tensor:
    """Deterministically encode topology signature strings to ``[B, 8]``.

    Uses the first 8 bytes of SHA-256 scaled to ``[0, 1]``. Pure function:
    equal strings give equal rows on any device/run.
    """
    if not isinstance(signatures, (list, tuple)) or not signatures:
        raise ValueError("topology_signature batch must be a nonempty list/tuple of str")
    if any(not isinstance(s, str) or not s for s in signatures):
        raise ValueError("every topology_signature must be a nonempty string")
    rows = []
    for sig in signatures:
        digest = hashlib.sha256(sig.encode("utf-8")).digest()
        rows.append([b / 255.0 for b in digest[:TOPO_DIM]])
    # Returned on CPU by construction; callers move to the batch device.
    return torch.tensor(rows, dtype=torch.float32, device="cpu")


def encode_conditioning(feedback: torch.Tensor, operators: torch.Tensor,
                        signatures: list[str] | tuple[str, ...]) -> torch.Tensor:
    """Deterministic numeric/topology conditioning vector ``[B, 39]``.

    Concatenates normalized feedback (1) + flattened normalized operators
    (30) + topology hash features (8). Algorithm is excluded here: it enters
    the model through a categorical embedding, not as a scalar.
    """
    fb = normalize_feedback(feedback)
    ops = normalize_operators(operators).flatten(start_dim=1)
    topo = topology_features(signatures).to(dtype=fb.dtype, device=fb.device)
    if not (len(fb) == len(ops) == len(topo)):
        raise ValueError("feedback/operators/topology_signature batch sizes must match")
    return torch.cat([fb, ops, topo], dim=1)


def note_bands(note_midi: int) -> int:
    """Harmonic band count for one canonical label frame.

    Mirrors the ``features.canonical_frame`` band rule under the collection
    contract (48 kHz, 2048-sample frames, no ``max_harmonics`` cap): the
    Nyquist limit at the note's nominal equal-temperament fundamental sets
    the count. Pinned by test against ``canonical_frame(...).bands``.
    """
    if type(note_midi) is not int or not 0 <= note_midi <= 127:
        raise ValueError("note_midi must be an integer MIDI note 0..127")
    base = 440.0 * 2.0 ** ((note_midi - 69) / 12.0)
    nyquist_bands = max(1, math.floor(LABEL_SAMPLE_RATE / (2.0 * base)) - 1)
    return min(FRAME_LENGTH // 2 - 1, nyquist_bands)


NOTE_BANDS = tuple(note_bands(note) for note in NOTE_MIDIS)
MAX_BANDS = max(NOTE_BANDS)

# Fixed synthesis bases per note: (sin_basis, cos_basis), each
# ``[bands, 2048]`` float32 on CPU. Content is a pure function of the note;
# callers move it to the batch device/dtype. Cached because it never changes.
_synthesis_cache: dict[int, tuple[torch.Tensor, torch.Tensor]] = {}


def _synthesis_bases(note_midi: int) -> tuple[torch.Tensor, torch.Tensor]:
    cached = _synthesis_cache.get(note_midi)
    if cached is None:
        bands = note_bands(note_midi)
        phase = torch.arange(FRAME_LENGTH, dtype=torch.float32) * (2.0 * math.pi / FRAME_LENGTH)
        harmonic = torch.arange(1, bands + 1, dtype=torch.float32).unsqueeze(1)
        theta = harmonic * phase.unsqueeze(0)
        cached = (torch.sin(theta), torch.cos(theta))
        _synthesis_cache[note_midi] = cached
    return cached


def synthesize_frames(sin_coeffs: torch.Tensor, cos_coeffs: torch.Tensor) -> torch.Tensor:
    """Render ``[B, 3, MAX_BANDS]`` harmonic coefficients to ``[B, 3, 2048]``.

    Exact inverse of the label-generating synthesis: frame[t] equals the sum
    over harmonics of ``s_k * sin(2*pi*k*t/2048) + c_k * cos(...)``, sliced
    to each note's true band count. Bands above a note's Nyquist limit are
    structurally absent (sliced away), never predicted-then-masked.
    Differentiable; holds no learnable state.
    """
    for name, value in (("sin_coeffs", sin_coeffs), ("cos_coeffs", cos_coeffs)):
        if (not isinstance(value, torch.Tensor) or not value.is_floating_point()
                or value.ndim != 3 or tuple(value.shape[1:]) != (NOTE_COUNT, MAX_BANDS)
                or not len(value)):
            raise ValueError(f"{name} must have nonempty shape [B, 3, {MAX_BANDS}]")
        if not torch.isfinite(value).all():
            raise ValueError(f"{name} contains nonfinite values")
    if sin_coeffs.shape != cos_coeffs.shape or sin_coeffs.device != cos_coeffs.device:
        raise ValueError("sin_coeffs and cos_coeffs must have matching shape and device")
    frames = []
    for index, note in enumerate(NOTE_MIDIS):
        bands = NOTE_BANDS[index]
        sin_basis, cos_basis = _synthesis_bases(note)
        sin_basis = sin_basis.to(dtype=sin_coeffs.dtype, device=sin_coeffs.device)
        cos_basis = cos_basis.to(dtype=cos_coeffs.dtype, device=cos_coeffs.device)
        frames.append(sin_coeffs[:, index, :bands] @ sin_basis
                      + cos_coeffs[:, index, :bands] @ cos_basis)
    return torch.stack(frames, dim=1)


class ForwardModel(nn.Module):
    """Shared-MLP forward surrogate: patch state -> harmonic coeffs -> ``[B, 3, 2048]``."""

    def __init__(self, algorithm_dim: int = 16,
                 hidden_dims: tuple[int, ...] = (512, 512),
                 topo_dim: int = TOPO_DIM) -> None:
        super().__init__()
        if not isinstance(algorithm_dim, int) or algorithm_dim <= 0:
            raise ValueError("algorithm_dim must be a positive integer")
        if (not isinstance(hidden_dims, tuple) or not hidden_dims
                or any(type(h) is not int or h <= 0 for h in hidden_dims)):
            raise ValueError("hidden_dims must be a nonempty tuple of positive ints")
        if topo_dim != TOPO_DIM:
            raise ValueError(f"topo_dim must equal {TOPO_DIM}")
        self.algorithm_dim = algorithm_dim
        self.hidden_dims = tuple(hidden_dims)
        self.topo_dim = topo_dim
        self.algorithm_embedding = nn.Embedding(ALGORITHM_COUNT + 1, algorithm_dim, padding_idx=0)
        trunk_in = algorithm_dim + 1 + 6 * 5 + topo_dim
        layers: list[nn.Module] = []
        prev = trunk_in
        for width in self.hidden_dims:
            layers.append(nn.Linear(prev, width))
            layers.append(nn.ReLU())
            prev = width
        self.trunk = nn.Sequential(*layers)
        # One exact-sized coefficient head per note (sin+cos): no dead
        # outputs, no above-Nyquist predictions. Synthesis itself is fixed.
        self.coeff_heads = nn.ModuleList(
            nn.Linear(prev, 2 * bands) for bands in NOTE_BANDS
        )

    def _check_algorithm(self, algorithm: torch.Tensor) -> None:
        _check_long(algorithm, "algorithm")
        if algorithm.ndim != 1 or not len(algorithm):
            raise ValueError("algorithm must have nonempty shape [B]")
        if bool((algorithm < 1).any() or (algorithm > ALGORITHM_COUNT).any()):
            raise ValueError("algorithm must hold integers 1..32")

    def forward(self, algorithm: torch.Tensor, feedback: torch.Tensor,
                operators: torch.Tensor,
                topology_signature: list[str] | tuple[str, ...]) -> torch.Tensor:
        """Predict phase-bearing waveforms ``[B, 3, 2048]`` at native amplitude."""
        self._check_algorithm(algorithm)
        conditioning = encode_conditioning(feedback, operators, topology_signature)
        # Re-validate shared batch size against the categorical IDs.
        if len(conditioning) != len(algorithm):
            raise ValueError("algorithm batch size must match other inputs")
        embedded = self.algorithm_embedding(algorithm)
        conditioning = conditioning.to(device=embedded.device)
        hidden = self.trunk(torch.cat([embedded, conditioning], dim=1))
        sin_list, cos_list = [], []
        for head, bands in zip(self.coeff_heads, NOTE_BANDS):
            coeffs = head(hidden)
            sin_list.append(coeffs[:, :bands])
            cos_list.append(coeffs[:, bands:])
        batch_size = len(algorithm)
        device = hidden.device
        dtype = hidden.dtype
        sin_padded = torch.zeros(batch_size, NOTE_COUNT, MAX_BANDS, dtype=dtype, device=device)
        cos_padded = torch.zeros(batch_size, NOTE_COUNT, MAX_BANDS, dtype=dtype, device=device)
        for index, bands in enumerate(NOTE_BANDS):
            sin_padded[:, index, :bands] = sin_list[index]
            cos_padded[:, index, :bands] = cos_list[index]
        return synthesize_frames(sin_padded, cos_padded)

    def forward_batch(self, batch: dict) -> torch.Tensor:
        """Convenience forward over a ``ForwardDataset`` collated batch dict."""
        try:
            algorithm = batch["algorithm"]
            feedback = batch["feedback"]
            operators = batch["operators"]
            signatures = batch.get("topology_signature")
        except (TypeError, KeyError) as exc:
            raise ValueError(f"batch is missing required ForwardDataset fields: {exc}") from exc
        if signatures is None:
            raise ValueError("batch is missing required field 'topology_signature'")
        if isinstance(signatures, torch.Tensor):
            raise ValueError("topology_signature must be a list/tuple of str, not a tensor")
        return self.forward(algorithm, feedback, operators, list(signatures))

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())
