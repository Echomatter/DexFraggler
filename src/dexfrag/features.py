"""Canonical waveform/feature extraction and the black-box target boundary.

Two representations exist and must not be confused:

- The **native capture**: 4096 samples per note (A2/A3/A4), exactly as the
  vendored Dexed Mark I renderer returns it. This is permanent ground truth.
- The **canonical periodic frame**: exactly 2048 phase-bearing samples,
  representing one period of the note's fundamental. This is what forward/
  inverse/compatibility models consume, and what a generated wavetable frame
  or 256x2048 wavetable is expected to look like.

Canonicalization contract (Phase 1, this module's authoritative version):

1. Estimate the nominal fundamental from the rendered MIDI note using equal
   temperament (``440 * 2**((note-69)/12)``). DX7 coarse/fine/detune act on
   each *operator*, not on the note pitch directly, so this nominal value is
   the correct period reference for a harmonic/near-harmonic voice.
2. Project the full 4096-sample capture onto sine/cosine bases at every
   harmonic of that nominal fundamental, up to the smaller of
   ``max_harmonics`` and one bin below Nyquist -- this is a direct-summation
   Fourier projection, not an FFT-bin readout, so the analysis frequency does
   not need to be an exact FFT bin of the 4096-sample window.
3. Synthesize a canonical ``frame_length``-sample (default 2048) single-cycle
   waveform by evaluating the truncated Fourier series at ``frame_length``
   equally spaced phase points. This is phase-bearing (both sin and cos
   coefficients are retained) and deterministic given (waveform, note,
   sample_rate, frame_length, max_harmonics, feature_version).
4. A ``periodicity_ratio`` diagnostic (energy explained by the harmonic model
   / total capture energy) flags non-periodic-at-this-fundamental captures
   (e.g. fixed-frequency operators producing inharmonic beating, or
   near-silent patches) as degenerate rather than silently discarding them.

This canonicalization is lossy above the harmonic cutoff and is therefore
*not* used as a substitute for native verification -- it is a modeling input
only. The raw 4096-sample native captures remain the permanent observation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

FEATURE_VERSION = "dexfrag-canonical-frame-v1"
DEFAULT_FRAME_LENGTH = 2048
CANONICAL_WAVETABLE_FRAMES = 256

# Forbidden keys that must never appear as model-facing target features.
# Enforces the black-box target rule (Master Overview principle #5).
FORBIDDEN_TARGET_KEYS = frozenset({
    "seed", "recipe", "generator", "generator_name", "family", "waveform_class",
    "difficulty", "multiplex", "multiplex_count", "source_family", "creation_order",
    "generation_order", "label", "shape", "shape_name",
})
ALLOWED_TARGET_BOOKKEEPING_KEYS = frozenset({
    "target_hash", "source_file_hash", "frame_index", "experiment_id", "table_hash",
})


class FeatureError(ValueError):
    pass


def _note_frequency(note_midi: int) -> float:
    return 440.0 * 2.0 ** ((note_midi - 69) / 12.0)


@dataclass(frozen=True)
class CanonicalFrame:
    version: str
    note_midi: int
    sample_rate: int
    base_frequency_hz: float
    bands: int
    frame_length: int
    samples: tuple[float, ...]  # length == frame_length, phase-bearing periodic waveform
    sin_coefficients: tuple[float, ...]  # length == bands
    cos_coefficients: tuple[float, ...]  # length == bands
    magnitude: tuple[float, ...]  # length == bands
    rms: float
    peak: float
    periodicity_ratio: float  # in [0, 1]; 1.0 = fully explained by harmonic model

    def to_dict(self, include_samples: bool = True) -> dict:
        result = {
            "version": self.version,
            "note_midi": self.note_midi,
            "sample_rate": self.sample_rate,
            "base_frequency_hz": self.base_frequency_hz,
            "bands": self.bands,
            "frame_length": self.frame_length,
            "rms": self.rms,
            "peak": self.peak,
            "periodicity_ratio": self.periodicity_ratio,
        }
        if include_samples:
            result["samples"] = list(self.samples)
            result["sin_coefficients"] = list(self.sin_coefficients)
            result["cos_coefficients"] = list(self.cos_coefficients)
            result["magnitude"] = list(self.magnitude)
        return result


def canonical_frame(
    waveform: Sequence[float],
    note_midi: int,
    *,
    sample_rate: int = 48000,
    frame_length: int = DEFAULT_FRAME_LENGTH,
    max_harmonics: int | None = None,
) -> CanonicalFrame:
    """Derive one canonical phase-bearing periodic frame from a native capture.

    Pure function of (waveform samples, note, sample_rate, frame_length,
    max_harmonics, FEATURE_VERSION) -- no other hidden state.
    """
    if not waveform or len(waveform) < 8:
        raise FeatureError("A native capture needs at least 8 finite samples.")
    if not all(math.isfinite(x) for x in waveform):
        raise FeatureError("A native capture must be entirely finite.")
    if not isinstance(note_midi, int) or not (0 <= note_midi <= 127):
        raise FeatureError("note_midi must be an integer MIDI note 0..127.")
    if frame_length < 8:
        raise FeatureError("frame_length must be at least 8 samples.")

    base = _note_frequency(note_midi)
    nyquist_bands = max(1, math.floor(sample_rate / (2.0 * base)) - 1)
    frame_bands = max(1, frame_length // 2 - 1)
    bands = min(max_harmonics or frame_bands, nyquist_bands, frame_bands)

    n = len(waveform)
    audio = np.asarray(waveform, dtype=np.float64)
    centered = audio - audio.mean()
    total_energy = float(np.dot(centered, centered))

    # Direct-summation (non-FFT-bin) Fourier projection: analysis frequency is
    # k * base, which need not land on an exact 4096-point FFT bin.
    sample_index = np.arange(n, dtype=np.float64)
    harmonic_index = np.arange(1, bands + 1, dtype=np.float64)
    angular_step_base = 2.0 * math.pi * base / sample_rate
    # theta[k, i] = angular_step_base * k * i  -- shape (bands, n)
    theta = np.outer(harmonic_index, sample_index) * angular_step_base
    sin_basis = np.sin(theta)
    cos_basis = np.cos(theta)
    sin_coeffs_arr = (2.0 / n) * (sin_basis @ centered)
    cos_coeffs_arr = (2.0 / n) * (cos_basis @ centered)
    explained_energy = float((n / 2.0) * np.sum(sin_coeffs_arr ** 2 + cos_coeffs_arr ** 2))

    magnitude_arr = np.hypot(sin_coeffs_arr, cos_coeffs_arr)
    periodicity_ratio = 0.0 if total_energy <= 1e-20 else min(1.0, explained_energy / total_energy)

    frame_index = np.arange(frame_length, dtype=np.float64)
    theta0 = 2.0 * math.pi * frame_index / frame_length
    # synth_theta[k, t] = k * theta0[t] -- shape (bands, frame_length)
    synth_theta = np.outer(harmonic_index, theta0)
    samples_arr = (sin_coeffs_arr @ np.sin(synth_theta)) + (cos_coeffs_arr @ np.cos(synth_theta))

    sin_coeffs = sin_coeffs_arr.tolist()
    cos_coeffs = cos_coeffs_arr.tolist()
    magnitude = magnitude_arr.tolist()
    samples = samples_arr.tolist()

    rms = float(math.sqrt(np.dot(samples_arr, samples_arr) / frame_length)) if frame_length else 0.0
    peak = float(np.max(np.abs(samples_arr))) if frame_length else 0.0

    return CanonicalFrame(
        version=FEATURE_VERSION,
        note_midi=note_midi,
        sample_rate=sample_rate,
        base_frequency_hz=base,
        bands=bands,
        frame_length=frame_length,
        samples=tuple(samples),
        sin_coefficients=tuple(sin_coeffs),
        cos_coefficients=tuple(cos_coeffs),
        magnitude=tuple(magnitude),
        rms=rms,
        peak=peak,
        periodicity_ratio=periodicity_ratio,
    )


def validate_wavetable(frames: Sequence[Sequence[float]], *,
                        expected_frame_count: int = CANONICAL_WAVETABLE_FRAMES,
                        expected_frame_length: int = DEFAULT_FRAME_LENGTH) -> None:
    """Validate a [256, 2048] black-box target wavetable ingests without any
    frame reduction. Raises FeatureError on any shape/finiteness violation.
    """
    if len(frames) != expected_frame_count:
        raise FeatureError(
            f"A canonical wavetable must contain exactly {expected_frame_count} frames; "
            f"got {len(frames)}. No 32-frame reduction is permitted."
        )
    for index, frame in enumerate(frames):
        if len(frame) != expected_frame_length:
            raise FeatureError(f"Frame {index} must contain exactly {expected_frame_length} samples.")
        if not all(math.isfinite(x) for x in frame):
            raise FeatureError(f"Frame {index} contains non-finite samples.")


def black_box_target_features(waveform: Sequence[float], *, bookkeeping: dict | None = None,
                               max_harmonics: int | None = None) -> dict:
    """Build the model-facing feature record for an arbitrary black-box target
    frame (already exactly ``frame_length`` samples; no note/pitch is assumed).

    Only waveform-derived features plus allow-listed bookkeeping fields are
    included. Raises FeatureError if forbidden generator-provenance keys are
    supplied, proving the pipeline is a pure function of samples only.
    """
    bookkeeping = bookkeeping or {}
    forbidden_present = FORBIDDEN_TARGET_KEYS & set(bookkeeping.keys())
    if forbidden_present:
        raise FeatureError(
            f"Black-box target records must not contain generator provenance: {sorted(forbidden_present)}"
        )
    unknown = set(bookkeeping.keys()) - ALLOWED_TARGET_BOOKKEEPING_KEYS
    if unknown:
        raise FeatureError(f"Unrecognized bookkeeping keys are not allowed as target features: {sorted(unknown)}")

    n = len(waveform)
    audio = np.asarray(waveform, dtype=np.float64)
    if not np.all(np.isfinite(audio)):
        raise FeatureError("Target waveform must be entirely finite.")
    centered = audio - audio.mean()
    energy = float(np.dot(centered, centered))
    bands = max(1, min(max_harmonics or (n // 2 - 1), n // 2 - 1))
    sample_index = np.arange(n, dtype=np.float64)
    harmonic_index = np.arange(1, bands + 1, dtype=np.float64)
    theta = np.outer(harmonic_index, sample_index) * (2.0 * math.pi / n)
    sin_coeffs = ((2.0 / n) * (np.sin(theta) @ centered)).tolist()
    cos_coeffs = ((2.0 / n) * (np.cos(theta) @ centered)).tolist()

    return {
        "version": FEATURE_VERSION,
        "frame_length": n,
        "rms": math.sqrt(energy / n) if n else 0.0,
        "peak": float(np.max(np.abs(audio))) if n else 0.0,
        "sin_coefficients": sin_coeffs,
        "cos_coefficients": cos_coeffs,
        **bookkeeping,
    }
