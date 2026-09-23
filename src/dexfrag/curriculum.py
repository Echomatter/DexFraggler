"""Black-box target curriculum producer: deterministic wavetable generation.

Ported from the standalone Wavetable-Generator project into DexFraggler so the
hard-target curriculum ("generated wavetables") can be produced from inside
this repository.

Design contract (see docs/plan/00_MASTER_OVERVIEW.md, principle #5 and the
"Generated hard wavetable curriculum" / "Full 256x2048 wavetable solving"
sections):

- The canonical wavetable is 256 frames x 2048 samples. All 256 frames are
  real targets; no 32-frame reduction is permitted.
- Generated wavetables are black-box challenge/query targets for the inverse
  search / active-learning pipeline. This module is a producer only: it must
  never feed model-facing features directly. Target ingestion routes through
  ``features.validate_wavetable`` + ``features.black_box_target_features`` in
  ``targets.py``, which strip all generator provenance.
- Generation is exactly deterministic from ``(tables, frame_size, frame_count,
  seed)``: globally unique slice recipes, run-level unique int16 PCM slices,
  and a deterministic spectral-band deal across tables.

The GUI and argparse front ends from the original project are intentionally
not ported: DexFraggler avoids product UI this rebuild. Use the
``dexfrag generate-targets`` CLI command instead.
"""
from __future__ import annotations

from math import perm
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
from scipy.io import wavfile
from scipy.signal import chirp, gausspulse, sawtooth, square


APP_NAME = "DexFraggler Target Curriculum Generator"
SAMPLE_RATE = 44100  # WAV header metadata only; not exposed as a generation parameter.
MIN_FRAME_SIZE = 128

# Internal waveform range used by the retained waveform definitions.
phase_shift_range = (0.0, 2 * np.pi)


@dataclass(frozen=True)
class GeneratorConfig:
    tables: int = 10
    frame_size: int = 2048
    frame_count: int = 256
    seed: int = 42
    zip_and_delete: bool = False
    folder: Path = Path("wavetables")

    def validate(self) -> None:
        if self.tables < 1:
            raise ValueError("Number of tables must be at least 1.")
        if self.frame_size < MIN_FRAME_SIZE:
            raise ValueError(f"Frame size must be at least {MIN_FRAME_SIZE}.")
        if self.frame_count < 1:
            raise ValueError("Frame count must be at least 1.")
        if self.seed < 0:
            raise ValueError("Seed must be zero or greater.")
        if not str(self.folder).strip():
            raise ValueError("Folder is required.")


# Waveform Functions

def white_noise(t, rng):
    return rng.normal(0, 1, t.shape)

def pink_noise(t, rng):
    num_samples = len(t)
    num_rows = 16
    array = rng.normal(size=(num_rows, num_samples))
    pink = np.sum(array, axis=0)
    return pink / np.max(np.abs(pink))

# FM and AM Synthesis (frequency is fixed to one cycle internally)
def fm_synthesis(t, rng):
    mod_index = rng.uniform(0.1, 0.9)
    modulator = np.sin(2 * np.pi * t) * mod_index
    phase_deviation = np.cumsum(modulator) / len(t)
    carrier_phase = rng.uniform(*phase_shift_range)
    return np.sin(2 * np.pi * (t + phase_deviation) + carrier_phase)

def am_synthesis(t, rng):
    mod_index = rng.uniform(0.2, 0.8)
    modulator = (1 + mod_index * np.sin(2 * np.pi * t)) / 2
    carrier_phase = rng.uniform(*phase_shift_range)
    return modulator * np.sin(2 * np.pi * t + carrier_phase)

# Basic Waveforms
def sin_wave(t, rng):
    phase = rng.uniform(*phase_shift_range)
    return np.sin(2 * np.pi * t + phase)

def cos_wave(t, rng):
    phase = rng.uniform(*phase_shift_range)
    return np.cos(2 * np.pi * t + phase)

def square_wave(t, rng):
    phase = rng.uniform(*phase_shift_range)
    return square(2 * np.pi * t + phase)

def sawtooth_wave(t, rng):
    phase = rng.uniform(*phase_shift_range)
    return sawtooth(2 * np.pi * t + phase)

def triangle_wave(t, rng):
    phase = rng.uniform(*phase_shift_range)
    return sawtooth(2 * np.pi * t + phase, width=0.5)

# Chirp and Gaussian Pulse
def chirp_wave(t, rng):
    carrier_phase = rng.uniform(*phase_shift_range)
    chirp_part = chirp(t, f0=20, f1=1000, t1=1, method='linear')
    return chirp_part * np.cos(2 * np.pi * t + carrier_phase)

def gauss_wave(t, rng):
    carrier_phase = rng.uniform(*phase_shift_range)
    return gausspulse(t - 0.5, fc=1) * np.cos(2 * np.pi * t + carrier_phase)

def exp_chirp_wave(t, rng):
    carrier_phase = rng.uniform(*phase_shift_range)
    exp_chirp_part = chirp(t, f0=1, f1=10, t1=1, method='quadratic')
    return exp_chirp_part * np.cos(2 * np.pi * t + carrier_phase)

# Functions with optional random parameters use defaults generated from rng
def bounded_sin_wave(t, rng, lower_bound=None, upper_bound=None):
    lower_bound = lower_bound if lower_bound is not None else rng.uniform(-1, 0)
    upper_bound = upper_bound if upper_bound is not None else rng.uniform(0, 1)
    phase = rng.uniform(*phase_shift_range)
    sine_wave = np.sin(2 * np.pi * t + phase)
    bounded_wave = np.clip(sine_wave, min(lower_bound, upper_bound), max(lower_bound, upper_bound))
    max_amp = np.max(np.abs(bounded_wave))
    return bounded_wave / max_amp if max_amp > 0 else bounded_wave

def expanding_triangle_wave(t, rng):
    max_width = rng.uniform(0.1, 1)
    phase = rng.uniform(*phase_shift_range)
    width = t % max_width
    return sawtooth(2 * np.pi * t + phase, width=width)

def exponential_decay_wave(t, rng, decay_rate=5):
    phase = rng.uniform(*phase_shift_range)
    return np.exp(-decay_rate * t) * np.sin(2 * np.pi * t + phase)

def rectified_sin_wave(t, rng):
    phase = rng.uniform(*phase_shift_range)
    return np.maximum(0, np.sin(2 * np.pi * t + phase))

def random_step_wave(t, rng, num_steps=10):
    step_values = rng.uniform(-1, 1, num_steps)
    step_times = np.linspace(0, 1, num_steps, endpoint=False)
    step_wave = np.interp(t, step_times, step_values)
    phase = rng.uniform(*phase_shift_range)
    return np.sin(2 * np.pi * t + phase) + step_wave

def stochastic_resonance_wave(t, rng, noise_intensity=0.1, threshold=0.5):
    phase = rng.uniform(*phase_shift_range)
    cosine_wave = np.cos(2 * np.pi * t + phase)
    noise = rng.normal(0, noise_intensity, t.shape)
    amplified_signal = cosine_wave + noise
    return np.tanh(amplified_signal - threshold)

def bit_crushed_wave(t, rng, bit_depth=4, downsample_factor=4):
    phase = rng.uniform(*phase_shift_range)
    base_wave = sawtooth(2 * np.pi * t + phase, width=0.5)
    step_size = 1 / (2 ** bit_depth)
    quantized_wave = np.round(base_wave / step_size) * step_size
    # Use a fixed downsampling factor:
    downsampled_wave = quantized_wave[::downsample_factor]
    interpolated_wave = np.interp(t, t[::downsample_factor], downsampled_wave)
    return interpolated_wave / np.max(np.abs(interpolated_wave))

def wavefolding_synthesis(t, rng, fold_threshold=0.5):
    phase = rng.uniform(*phase_shift_range)
    saw_wave = sawtooth(2 * np.pi * t + phase)
    folded_wave = np.where(np.abs(saw_wave) > fold_threshold, fold_threshold - (saw_wave - fold_threshold), saw_wave)
    return folded_wave

def karplus_strong_wave(t, rng, decay=0.98):
    n_samples = len(t)
    period = max(1, n_samples // 10)
    noise = rng.uniform(-1, 1, period)
    buffer = np.zeros(n_samples)
    buffer[:period] = noise
    for i in range(period, n_samples):
        prev = buffer[i - period]
        nxt = buffer[i - period + 1] if i - period + 1 < n_samples else prev
        buffer[i] = decay * 0.5 * (prev + nxt)
    return buffer

def fractal_noise_wave2(t, rng):
    num_iterations = 5
    signal = np.zeros_like(t)
    phase = rng.uniform(*phase_shift_range)
    for i in range(num_iterations):
        amplitude = 1 / (2 ** i)
        signal += amplitude * np.sin(2 * np.pi * (2 ** i) * t + phase)
    max_val = np.max(np.abs(signal))
    return signal / max_val if max_val != 0 else signal

def random_amplitude_wave(t, rng, num_segments=10):
    segment_length = len(t) // num_segments
    amplitude_wave = np.ones_like(t)
    for i in range(num_segments):
        amplitude = rng.uniform(0.1, 1.0)
        amplitude_wave[i * segment_length:(i + 1) * segment_length] *= amplitude
    phase = rng.uniform(*phase_shift_range)
    return amplitude_wave * np.sin(2 * np.pi * t + phase)

def chaotic_wave(t, rng):
    r = rng.uniform(3.6, 4.0)
    x = rng.uniform(0, 1)
    chaotic_sequence = np.zeros_like(t)
    for i in range(len(t)):
        x = r * x * (1 - x)
        chaotic_sequence[i] = x
    phase = rng.uniform(*phase_shift_range)
    chaotic_interp = np.interp(t, np.linspace(0, 1, len(t)), chaotic_sequence)
    return chaotic_interp * np.sin(2 * np.pi * t + phase)

def fractal_noise_wave1(t, rng):
    persistence = 0.5
    octaves = 5
    signal = np.zeros_like(t)
    phase = rng.uniform(*phase_shift_range)
    amplitude = 1
    for i in range(octaves):
        signal += amplitude * np.sin(2 * np.pi * (2 ** i) * t + phase)
        amplitude *= persistence
    return signal

def chaotic_lorenz_wave(t, rng):
    sigma = 10
    rho = 28
    beta = 8/3
    dt = t[1] - t[0] if len(t) > 1 else 0.01
    n_steps = len(t)
    x, y, z = [0.0], [1.0], [1.05]
    for i in range(n_steps - 1):
        x_dot = sigma * (y[i] - x[i])
        y_dot = x[i] * (rho - z[i]) - y[i]
        z_dot = x[i] * y[i] - beta * z[i]
        x.append(x[i] + x_dot * dt)
        y.append(y[i] + y_dot * dt)
        z.append(z[i] + z_dot * dt)
    phase = rng.uniform(*phase_shift_range)
    chaotic_wave_array = np.array(x[:n_steps])
    return chaotic_wave_array * np.sin(2 * np.pi * t + phase)

def polygonal_wave(t, rng, num_sides=5):
    angle = np.linspace(0, 2 * np.pi, num_sides, endpoint=False)
    radius = np.ones(num_sides)
    polygon_points = radius * np.exp(1j * angle)
    phase = rng.uniform(*phase_shift_range)
    interp_points = (2 * np.pi * t + phase) % (2 * np.pi)
    polygon_wave = np.interp(interp_points, angle, np.real(polygon_points))
    max_amp = np.max(np.abs(polygon_wave))
    return polygon_wave / max_amp if max_amp > 0 else polygon_wave

def saw_spiral_wave(t, rng, turns=5):
    phase = rng.uniform(*phase_shift_range)
    spiral = (t * turns) % 1
    return spiral * sawtooth(2 * np.pi * t + phase)

def zig_zag_wave(t, rng):
    phase = rng.uniform(*phase_shift_range)
    zigzag = 2 * (t % 1) - 1
    return zigzag * np.sin(2 * np.pi * t + phase)

def synthwave_wave(t, rng, num_voices=7, detune_amount=0.02):
    detune_range = np.linspace(-detune_amount, detune_amount, num_voices)
    phase = rng.uniform(*phase_shift_range)
    waveform = np.zeros_like(t)
    for detune in detune_range:
        osc = sawtooth(2 * np.pi * (1 * (1 + detune)) * t + phase)
        waveform += osc
    combined_wave = waveform / num_voices
    max_val = np.max(np.abs(combined_wave))
    return combined_wave / max_val if max_val > 0 else combined_wave

def phase_distortion_wave(t, rng, distortion_amount=0.5):
    base_phase = 2 * np.pi * t
    distorted_phase = base_phase + distortion_amount * np.sin(base_phase)
    phase = rng.uniform(*phase_shift_range)
    waveform = np.sin(distorted_phase + phase)
    max_val = np.max(np.abs(waveform))
    return waveform / max_val if max_val > 0 else waveform

def step_sequencer_wave(t, rng, steps=8):
    step_values = rng.uniform(-1, 1, steps)
    step_length = len(t) // steps
    waveform = np.zeros_like(t)
    for i in range(steps):
        start = i * step_length
        end = start + step_length
        waveform[start:end] = step_values[i]
    phase = rng.uniform(*phase_shift_range)
    return waveform + np.sin(2 * np.pi * t + phase)

def harmonic_series_wave(t, rng, harmonics=10):
    waveform = np.zeros_like(t)
    phase = rng.uniform(*phase_shift_range)
    for n in range(1, harmonics + 1):
        amplitude = 1 / n
        waveform += amplitude * np.sin(2 * np.pi * n * t + phase)
    return waveform

def granular_synthesis_wave(t, rng, grains=50):
    grain_length = len(t) // grains
    waveform = np.zeros_like(t)
    phase = rng.uniform(*phase_shift_range)
    for i in range(grains):
        start = i * grain_length
        end = start + grain_length
        grain_freq = 1 * (1 + rng.uniform(-0.1, 0.1))
        waveform[start:end] += np.sin(2 * np.pi * grain_freq * t[start:end] + phase)
    return waveform

def pwm_wave(t, rng):
    phase = rng.uniform(*phase_shift_range)
    duty_cycle = 0.5 + 0.5 * np.sin(2 * np.pi * 0.1 * t)
    return np.sign(np.sin(2 * np.pi * t + phase) - duty_cycle)

def phased_noise_wave(t, rng, noise_intervals=100):
    noise_phases = rng.uniform(0, 2 * np.pi, noise_intervals)
    interval_length = len(t) // noise_intervals
    waveform = np.zeros_like(t)
    for i in range(noise_intervals):
        start = i * interval_length
        end = start + interval_length
        waveform[start:end] = np.sin(2 * np.pi * t[start:end] + noise_phases[i] + rng.uniform(*phase_shift_range))
    return waveform

def noise_modulated_sine_wave(t, rng):
    noise_amplitude = rng.normal(0, 0.1, len(t))
    modulated_freq = 1 + noise_amplitude
    phase = rng.uniform(*phase_shift_range)
    return np.sin(2 * np.pi * modulated_freq * t + phase)

def wave_terrain_synthesis_wave(t, rng):
    terrain = lambda x, y: np.sin(x) * np.cos(y)
    phase = rng.uniform(*phase_shift_range)
    x = t + phase
    y = t - phase
    return terrain(x, y)

def band_limited_sawtooth_wave(t, rng, num_harmonics=10):
    phase = rng.uniform(*phase_shift_range)
    waveform = np.zeros_like(t)
    for n in range(1, num_harmonics + 1):
        waveform += ((-1) ** (n + 1)) * np.sin(2 * np.pi * n * t + phase) / n
    max_val = np.max(np.abs(waveform))
    if max_val == 0:
        print("Warning: `band_limited_sawtooth_wave` produced a silent waveform. Using fallback waveform.")
        waveform = sawtooth(2 * np.pi * t + phase)
    return waveform / np.max(np.abs(waveform))

def sync_sawtooth_wave(t, rng):
    phase = rng.uniform(*phase_shift_range)
    waveform = 2 * (t % 1) - 1
    shift = int((phase / (2 * np.pi)) * len(t))
    return np.roll(waveform, shift)

def super_saw_wave(t, rng, num_voices=7, detune_amount=0.02):
    detune_range = np.linspace(-detune_amount, detune_amount, num_voices)
    phase = rng.uniform(*phase_shift_range)
    waveform = np.zeros_like(t)
    for detune in detune_range:
        osc = sawtooth(2 * np.pi * (1 * (1 + detune)) * t + phase)
        waveform += osc
    combined_wave = waveform / num_voices
    max_val = np.max(np.abs(combined_wave))
    if max_val == 0:
        print("Warning: `super_saw_wave` produced a silent waveform. Using fallback waveform.")
        combined_wave = sawtooth(2 * np.pi * t + phase)
    return combined_wave / np.max(np.abs(combined_wave))

# Dictionary of waveforms
waveforms = {
    'sin': sin_wave,
    'cos': cos_wave,
    'square': square_wave,
    'sawtooth': sawtooth_wave,
    'chirp': chirp_wave,
    'triangle': triangle_wave,
    'gauss': gauss_wave,
    'exp_chirp': exp_chirp_wave,
    'white_noise': white_noise,
    'pink_noise': pink_noise,
    'fm_synthesis': fm_synthesis,
    'am_synthesis': am_synthesis,
    'bounded_sin': bounded_sin_wave,
    'expanding_triangle': expanding_triangle_wave,
    'exponential_decay': exponential_decay_wave,
    'rectified_sin': rectified_sin_wave,
    'random_step': random_step_wave,
    'fractal_noise2': fractal_noise_wave2,
    'random_amplitude': random_amplitude_wave,
    'karplus_strong': karplus_strong_wave,
    'wavefolding_synthesis': wavefolding_synthesis,
    'bit_crushed': bit_crushed_wave,
    'stochastic_resonance': stochastic_resonance_wave,
    'fractal_noise1': fractal_noise_wave1,
    'chaotic_lorenz': chaotic_lorenz_wave,
    'polygonal': polygonal_wave,
    'saw_spiral': saw_spiral_wave,
    'zig_zag': zig_zag_wave,
    'chaotic': chaotic_wave,
    'synthwave': synthwave_wave,
    'phase_distortion': phase_distortion_wave,
    'step_sequencer': step_sequencer_wave,
    'harmonic_series': harmonic_series_wave,
    'granular_synthesis': granular_synthesis_wave,
    'phased_noise': phased_noise_wave,
    'pwm': pwm_wave,
    'noise_modulated_sine': noise_modulated_sine_wave,
    'wave_terrain_synthesis': wave_terrain_synthesis_wave,
    'band_limited_saw': band_limited_sawtooth_wave,
    'sync_sawtooth': sync_sawtooth_wave,
    'super_saw': super_saw_wave
}
# --------------------------
# Wavetable Construction
# --------------------------
MULTIPLEX_COUNTS = (0, 2, 3, 5)
MULTIPLEX_CROSSFADE_RANGE = (0.10, 0.18)
MULTIPLEX_GAIN_RANGE = (0.80, 1.00)
UINT64_MASK = (1 << 64) - 1


@dataclass(frozen=True)
class SliceRecord:
    """One accepted globally unique slice and its lightweight shape descriptors."""

    frame: np.ndarray
    multiplex_count: int
    source_names: tuple[str, ...]
    features: tuple[float, float, float, float]
    serial: int


@dataclass(frozen=True)
class ProgressUpdate:
    """One user-facing progress update for CLI front ends."""

    stage: str
    stage_current: int
    stage_total: int
    overall_percent: float
    message: str
    output_path: Path | None = None


ProgressCallback = Callable[[ProgressUpdate], None]


def report_progress(
    progress: ProgressCallback | None,
    *,
    stage: str,
    current: int,
    total: int,
    start_percent: float,
    end_percent: float,
    message: str,
    output_path: Path | None = None,
) -> None:
    """Map stage-local work onto a monotonic 0-100 overall progress scale."""
    if progress is None:
        return

    if total <= 0:
        fraction = 1.0
    else:
        fraction = min(1.0, max(0.0, current / total))

    overall = start_percent + (end_percent - start_percent) * fraction
    progress(
        ProgressUpdate(
            stage=stage,
            stage_current=current,
            stage_total=total,
            overall_percent=min(100.0, max(0.0, overall)),
            message=message,
            output_path=output_path,
        )
    )


def normalize_frame(frame: np.ndarray) -> np.ndarray:
    """Peak-normalize one frame to [-1, 1]."""
    frame = np.asarray(frame, dtype=np.float64)
    frame = np.nan_to_num(frame, nan=0.0, posinf=0.0, neginf=0.0)

    peak = np.max(np.abs(frame))
    if peak <= 1e-12:
        t = np.linspace(0, 1, len(frame), endpoint=False)
        frame = np.sin(2 * np.pi * t)
        peak = 1.0

    return frame / peak


def phase_align_frame(frame: np.ndarray) -> np.ndarray:
    """Circularly align the frame's fundamental to a consistent sine-like phase."""
    if len(frame) < 2:
        return frame

    fundamental = np.fft.rfft(frame)[1]
    if np.abs(fundamental) <= 1e-12:
        return np.roll(frame, -int(np.argmax(np.abs(frame))))

    target_phase = -np.pi / 2
    current_phase = np.angle(fundamental)
    shift = int(round((current_phase - target_phase) * len(frame) / (2 * np.pi)))
    return np.roll(frame, shift)


def splitmix64(value: int) -> int:
    """Deterministically mix an integer into a well-distributed 64-bit seed."""
    z = (value + 0x9E3779B97F4A7C15) & UINT64_MASK
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & UINT64_MASK
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & UINT64_MASK
    return (z ^ (z >> 31)) & UINT64_MASK


def seed_parts(seed: int) -> tuple[int, int]:
    """Split a 64-bit seed into SeedSequence-friendly 32-bit words."""
    return seed & 0xFFFFFFFF, (seed >> 32) & 0xFFFFFFFF


def recipe_capacity() -> dict[int, int]:
    """Return the number of unique ordered recipes available for each mode."""
    source_count = len(waveforms)
    return {
        multiplex_count: perm(source_count, 1 if multiplex_count == 0 else multiplex_count)
        for multiplex_count in MULTIPLEX_COUNTS
    }


def draw_unique_recipe(
    rng: np.random.Generator,
    used_recipes: dict[int, set[tuple[str, ...]]],
    capacities: dict[int, int],
) -> tuple[int, tuple[str, ...]]:
    """
    Draw one globally unused ordered recipe.

    Reordering the same waveform names creates a different recipe. The no-multiplex
    mode uses a one-name recipe, so a raw waveform type can occur only once in the
    entire generation run.
    """
    waveform_names = tuple(waveforms)
    source_count = len(waveform_names)

    available_counts = [
        count for count in MULTIPLEX_COUNTS
        if len(used_recipes[count]) < capacities[count]
    ]
    if not available_counts:
        raise ValueError("No unused waveform recipes remain for this generation run.")

    # Normal runs are nowhere near recipe exhaustion, so random rejection keeps
    # the selection simple while remaining exactly deterministic from the seed.
    while True:
        multiplex_count = int(rng.choice(available_counts))
        source_total = 1 if multiplex_count == 0 else multiplex_count
        indices = rng.choice(source_count, size=source_total, replace=False)
        source_names = tuple(waveform_names[int(index)] for index in indices)
        if source_names in used_recipes[multiplex_count]:
            continue
        used_recipes[multiplex_count].add(source_names)
        return multiplex_count, source_names


def multiplex_morph(sources: list[np.ndarray], rng: np.random.Generator) -> np.ndarray:
    """
    Multiplex 2, 3, or 5 aligned sources with broad cosine morph transitions.

    Segment lengths, transition widths, and relative source gains vary
    deterministically per slice. A single source is returned unchanged for the
    no-multiplex path.
    """
    source_total = len(sources)
    if source_total == 1:
        return sources[0].copy()
    if source_total not in (2, 3, 5):
        raise ValueError("Multiplex morph requires 1, 2, 3, or 5 sources.")

    n = len(sources[0])
    if any(len(source) != n for source in sources):
        raise ValueError("All multiplex sources must have the same frame size.")

    # Keep regions broadly even while allowing the multiplex structure to move.
    segment_weights = rng.uniform(0.85, 1.15, size=source_total)
    segment_weights /= np.sum(segment_weights)
    boundaries = np.rint(np.cumsum(segment_weights)[:-1] * n).astype(int)
    boundaries = np.clip(boundaries, 1, n - 1)

    gains = rng.uniform(*MULTIPLEX_GAIN_RANGE, size=source_total)
    gained_sources = [source * gain for source, gain in zip(sources, gains)]

    edges = np.concatenate(([0], boundaries, [n]))
    output = np.empty(n, dtype=np.float64)
    for index, source in enumerate(gained_sources):
        output[edges[index]:edges[index + 1]] = source[edges[index]:edges[index + 1]]

    # Use intentionally broad transition regions so multiplex boundaries behave
    # as morphs rather than abrupt splices.
    for boundary_index, boundary in enumerate(boundaries):
        left_span = boundary - edges[boundary_index]
        right_span = edges[boundary_index + 2] - boundary
        requested_width = int(round(n * rng.uniform(*MULTIPLEX_CROSSFADE_RANGE)))
        max_width = max(2, int(0.80 * min(left_span, right_span)))
        width = max(2, min(requested_width, max_width))

        start = max(edges[boundary_index], boundary - width // 2)
        end = min(edges[boundary_index + 2], boundary + (width - width // 2))
        length = end - start
        if length <= 1:
            continue

        alpha = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, length))
        left = gained_sources[boundary_index][start:end]
        right = gained_sources[boundary_index + 1][start:end]
        output[start:end] = (1.0 - alpha) * left + alpha * right

    return output


def build_slice(
    config: GeneratorConfig,
    slice_seed: int,
    multiplex_count: int,
    source_names: tuple[str, ...],
) -> np.ndarray:
    """Generate one deterministic candidate slice from a run-derived slice seed."""
    t = np.linspace(0, 1, config.frame_size, endpoint=False)
    seed_low, seed_high = seed_parts(slice_seed)
    sources: list[np.ndarray] = []

    for source_index, waveform_name in enumerate(source_names):
        source_rng = np.random.default_rng(
            np.random.SeedSequence([seed_low, seed_high, source_index, 0x53524345])
        )
        source = waveforms[waveform_name](t, source_rng)
        source = phase_align_frame(normalize_frame(source))
        sources.append(source)

    if multiplex_count == 0:
        frame = sources[0]
    else:
        morph_rng = np.random.default_rng(
            np.random.SeedSequence([seed_low, seed_high, multiplex_count, 0x4D4F5250])
        )
        frame = multiplex_morph(sources, morph_rng)

    return phase_align_frame(normalize_frame(frame))


def frame_pcm16(frame: np.ndarray) -> np.ndarray:
    """Quantize a normalized frame exactly as it will appear in the WAV output."""
    return (np.clip(frame, -1.0, 1.0) * 32767).astype(np.int16)


def frame_audio_key(frame: np.ndarray) -> bytes:
    """Return an exact output-audio key used to reject duplicate slices."""
    # bytes() is enough here: the complete int16 PCM payload is the key, so there
    # is no hash-collision caveat and typical frame sizes remain small.
    return frame_pcm16(frame).tobytes()


def describe_frame(frame: np.ndarray) -> tuple[float, float, float, float]:
    """
    Compute four cheap descriptors used only to spread the finished pool.

    Returns normalized spectral centroid, spectral flatness, RMS, and zero-crossing
    rate. These descriptors never alter the generated audio.
    """
    spectrum = np.abs(np.fft.rfft(frame))
    if len(spectrum) > 0:
        spectrum = spectrum.copy()
        spectrum[0] = 0.0

    magnitude_sum = float(np.sum(spectrum))
    if magnitude_sum <= 1e-12 or len(spectrum) <= 1:
        centroid = 0.0
    else:
        bins = np.arange(len(spectrum), dtype=np.float64)
        centroid = float(np.sum(bins * spectrum) / magnitude_sum / (len(spectrum) - 1))

    eps = 1e-12
    if len(spectrum) == 0:
        flatness = 0.0
    else:
        flatness = float(
            np.exp(np.mean(np.log(spectrum + eps))) / (np.mean(spectrum) + eps)
        )

    rms = float(np.sqrt(np.mean(np.square(frame))))
    zero_crossing_rate = float(np.mean(np.signbit(frame[:-1]) != np.signbit(frame[1:])))
    return centroid, flatness, rms, zero_crossing_rate


def build_global_slice_pool(
    config: GeneratorConfig,
    progress: ProgressCallback | None = None,
) -> list[SliceRecord]:
    """
    Generate one globally unique slice pool for the entire run.

    Recipes are unique across every requested table, and candidate frames that
    quantize to an already accepted int16 slice are rejected. This makes slice
    uniqueness a run-level property rather than a table-level probability.
    """
    target_count = config.tables * config.frame_count
    capacities = recipe_capacity()
    total_capacity = sum(capacities.values())
    if target_count > total_capacity:
        raise ValueError(
            f"This run requests {target_count} slices, but only {total_capacity} "
            "unique ordered recipes exist across multiplex counts 0, 2, 3, and 5."
        )

    main_low, main_high = seed_parts(config.seed & UINT64_MASK)
    recipe_rng = np.random.default_rng(
        np.random.SeedSequence([main_low, main_high, 0x504F4F4C])
    )

    used_recipes: dict[int, set[tuple[str, ...]]] = {
        count: set() for count in MULTIPLEX_COUNTS
    }
    used_audio: set[bytes] = set()
    pool: list[SliceRecord] = []
    candidate_serial = 0
    duplicate_count = 0

    report_progress(
        progress,
        stage="pool",
        current=0,
        total=target_count,
        start_percent=0.0,
        end_percent=80.0,
        message=f"Building unique slice pool: 0/{target_count} accepted",
    )

    while len(pool) < target_count:
        multiplex_count, source_names = draw_unique_recipe(
            recipe_rng, used_recipes, capacities
        )
        slice_seed = splitmix64((config.seed & UINT64_MASK) + candidate_serial)
        frame = build_slice(config, slice_seed, multiplex_count, source_names)
        stored_frame = frame.astype(np.float32, copy=False)
        audio_key = frame_audio_key(stored_frame)
        candidate_serial += 1

        # Different recipes can occasionally collapse to the same post-alignment
        # output. Keep only the first exact PCM result in the entire run.
        if audio_key in used_audio:
            duplicate_count += 1
            # Duplicate attempts do not advance the bar, but reporting them makes
            # it clear why the accepted-slice count may briefly pause.
            report_progress(
                progress,
                stage="pool",
                current=len(pool),
                total=target_count,
                start_percent=0.0,
                end_percent=80.0,
                message=(
                    f"Building unique slice pool: {len(pool)}/{target_count} accepted "
                    f"• {candidate_serial} candidates • {duplicate_count} duplicate(s) rejected"
                ),
            )
            continue

        used_audio.add(audio_key)
        pool.append(
            SliceRecord(
                frame=stored_frame,
                multiplex_count=multiplex_count,
                source_names=source_names,
                features=describe_frame(stored_frame),
                serial=candidate_serial - 1,
            )
        )
        report_progress(
            progress,
            stage="pool",
            current=len(pool),
            total=target_count,
            start_percent=0.0,
            end_percent=80.0,
            message=(
                f"Building unique slice pool: {len(pool)}/{target_count} accepted "
                f"• {candidate_serial} candidates • {duplicate_count} duplicate(s) rejected"
            ),
        )

    return pool

def distribute_slice_pool(
    config: GeneratorConfig,
    pool: list[SliceRecord],
    progress: ProgressCallback | None = None,
) -> list[list[np.ndarray]]:
    """
    Deterministically deal the global pool into spectrally broad tables.

    The pool is first sorted by spectral centroid. Because pool size is exactly
    tables * frame_count, every consecutive spectral band contains one slice per
    table. Inside each band, a secondary descriptor is alternated and the deal
    rotates between tables. Every table therefore receives one slice from every
    low-to-high spectral band instead of inheriting a clustered chunk of the pool.
    """
    expected = config.tables * config.frame_count
    if len(pool) != expected:
        raise ValueError(f"Expected {expected} pooled slices, received {len(pool)}.")

    report_progress(
        progress,
        stage="distribute",
        current=0,
        total=config.frame_count,
        start_percent=80.0,
        end_percent=90.0,
        message=f"Sorting {len(pool)} unique slices for broad table variety",
    )

    ordered = sorted(
        pool,
        key=lambda record: (
            record.features[0],
            record.features[1],
            record.features[3],
            record.features[2],
            record.serial,
        ),
    )
    tables: list[list[np.ndarray]] = [[] for _ in range(config.tables)]
    if config.tables == 0:
        return tables

    deal_offset = splitmix64((config.seed & UINT64_MASK) ^ 0x4445414C) % config.tables
    # Alternate flatness, zero-crossing rate, and RMS when sorting each spectral
    # band. Rotating the table assignment prevents any table from always receiving
    # the same secondary rank.
    secondary_indices = (1, 3, 2)

    for band_index in range(config.frame_count):
        start = band_index * config.tables
        band = ordered[start:start + config.tables]
        secondary = secondary_indices[band_index % len(secondary_indices)]
        band.sort(
            key=lambda record: (
                record.features[secondary],
                record.features[0],
                record.serial,
            )
        )
        if band_index % 2:
            band.reverse()

        offset = int((deal_offset + band_index) % config.tables)
        for position, record in enumerate(band):
            table_index = (position + offset) % config.tables
            tables[table_index].append(record.frame)

        report_progress(
            progress,
            stage="distribute",
            current=band_index + 1,
            total=config.frame_count,
            start_percent=80.0,
            end_percent=90.0,
            message=(
                f"Distributing slices: spectral band {band_index + 1}/{config.frame_count} "
                f"across {config.tables} table(s)"
            ),
        )

    if any(len(frames) != config.frame_count for frames in tables):
        raise RuntimeError("Internal distribution error: table frame counts are uneven.")
    return tables


def wavetable_filename(config: GeneratorConfig, table_index: int) -> str:
    """Return the self-describing filename for one generated wavetable."""
    return (
        f"Wavetable_{table_index + 1:04d}-of-{config.tables:04d}"
        f"__FrameSize-{config.frame_size}"
        f"__FrameCount-{config.frame_count}"
        f"__Seed-{config.seed}.wav"
    )


def archive_filename(config: GeneratorConfig) -> str:
    """Return the self-describing filename for an archived generation run."""
    return (
        f"Wavetable_Generator__Tables-{config.tables}"
        f"__FrameSize-{config.frame_size}"
        f"__FrameCount-{config.frame_count}"
        f"__Seed-{config.seed}.zip"
    )


def generate_wavetables(
    config: GeneratorConfig,
    progress: ProgressCallback | None = None,
) -> tuple[list[Path], Path | None]:
    """Generate the global slice pool, distribute it, write tables, and optionally archive."""
    config.validate()
    output_folder = Path(config.folder).expanduser().resolve()
    output_folder.mkdir(parents=True, exist_ok=True)

    pool = build_global_slice_pool(config, progress=progress)
    table_frames = distribute_slice_pool(config, pool, progress=progress)

    write_end = 98.0 if config.zip_and_delete else 100.0
    report_progress(
        progress,
        stage="write",
        current=0,
        total=config.tables,
        start_percent=90.0,
        end_percent=write_end,
        message=f"Writing wavetable files: 0/{config.tables}",
    )

    created_files: list[Path] = []
    for table_index, frames in enumerate(table_frames):
        wavetable = np.concatenate(frames)
        output_path = output_folder / wavetable_filename(config, table_index)
        wavfile.write(output_path, SAMPLE_RATE, frame_pcm16(wavetable))
        created_files.append(output_path)

        report_progress(
            progress,
            stage="write",
            current=table_index + 1,
            total=config.tables,
            start_percent=90.0,
            end_percent=write_end,
            message=f"Writing wavetable files: {table_index + 1}/{config.tables} • {output_path.name}",
            output_path=output_path,
        )

    archive_path: Path | None = None
    if config.zip_and_delete:
        archive_path = output_folder / archive_filename(config)
        if archive_path.exists():
            archive_path.unlink()

        report_progress(
            progress,
            stage="archive",
            current=0,
            total=len(created_files),
            start_percent=98.0,
            end_percent=100.0,
            message=f"Creating archive: 0/{len(created_files)} WAVs",
            output_path=archive_path,
        )

        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
            for archive_index, path in enumerate(created_files):
                archive.write(path, arcname=path.name)
                report_progress(
                    progress,
                    stage="archive",
                    current=archive_index + 1,
                    total=len(created_files),
                    start_percent=98.0,
                    end_percent=100.0,
                    message=(
                        f"Creating archive: {archive_index + 1}/{len(created_files)} WAVs "
                        f"• {path.name}"
                    ),
                    output_path=archive_path,
                )

        for path in created_files:
            path.unlink()

    report_progress(
        progress,
        stage="complete",
        current=1,
        total=1,
        start_percent=100.0,
        end_percent=100.0,
        message=(
            f"Finished: {archive_path.name}"
            if archive_path
            else f"Finished: {len(created_files)} wavetable(s) created"
        ),
        output_path=archive_path,
    )

    return created_files, archive_path