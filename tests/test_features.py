import math

import pytest

from dexfrag.features import (
    canonical_frame, validate_wavetable, black_box_target_features,
    FeatureError, DEFAULT_FRAME_LENGTH, CANONICAL_WAVETABLE_FRAMES,
)


def _sine_capture(freq_hz=220.0, sample_rate=48000, n=4096, amplitude=0.5):
    return [amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate) for i in range(n)]


def test_canonical_frame_shape_and_determinism():
    wave = _sine_capture()
    a = canonical_frame(wave, note_midi=57, max_harmonics=32)  # A3 = 220 Hz
    b = canonical_frame(wave, note_midi=57, max_harmonics=32)
    assert len(a.samples) == DEFAULT_FRAME_LENGTH
    assert a.samples == b.samples
    assert a.sin_coefficients == b.sin_coefficients


def test_canonical_frame_recovers_pure_sine_amplitude_and_phase():
    wave = _sine_capture(amplitude=0.5)
    frame = canonical_frame(wave, note_midi=57, max_harmonics=8)
    assert frame.periodicity_ratio > 0.999
    # 4096 samples at 220 Hz / 48 kHz is not an exact integer number of
    # periods, so the rectangular-window direct-summation projection has a
    # small, expected spectral-leakage bias (a few parts per thousand).
    assert abs(frame.sin_coefficients[0] - 0.5) < 1e-2
    assert abs(frame.cos_coefficients[0]) < 1e-2
    assert frame.peak == pytest.approx(0.5, abs=1e-2)


def test_canonical_frame_rejects_non_finite_input():
    wave = _sine_capture()
    wave[10] = float("nan")
    with pytest.raises(FeatureError):
        canonical_frame(wave, note_midi=57)


def test_canonical_frame_rejects_bad_note():
    with pytest.raises(FeatureError):
        canonical_frame(_sine_capture(), note_midi=200)


def test_silent_capture_has_zero_periodicity_ratio():
    wave = [0.0] * 4096
    frame = canonical_frame(wave, note_midi=57, max_harmonics=8)
    assert frame.periodicity_ratio == 0.0
    assert all(x == 0.0 for x in frame.samples)


def test_validate_wavetable_requires_all_256_frames():
    good = [[0.0] * DEFAULT_FRAME_LENGTH for _ in range(CANONICAL_WAVETABLE_FRAMES)]
    validate_wavetable(good)  # should not raise
    with pytest.raises(FeatureError):
        validate_wavetable(good[:32])  # no 32-frame reduction allowed


def test_validate_wavetable_rejects_wrong_frame_length():
    bad = [[0.0] * 1024 for _ in range(CANONICAL_WAVETABLE_FRAMES)]
    with pytest.raises(FeatureError):
        validate_wavetable(bad)


def test_black_box_target_features_rejects_generator_provenance():
    wave = _sine_capture(n=2048)
    with pytest.raises(FeatureError):
        black_box_target_features(wave, bookkeeping={"seed": 42})
    with pytest.raises(FeatureError):
        black_box_target_features(wave, bookkeeping={"generator_name": "sawtooth-gen"})


def test_black_box_target_features_allows_only_bookkeeping():
    wave = _sine_capture(n=2048)
    features = black_box_target_features(wave, bookkeeping={"frame_index": 3, "table_hash": "abc"})
    assert features["frame_index"] == 3
    assert features["table_hash"] == "abc"
    assert "seed" not in features


def test_black_box_target_features_is_pure_function_of_samples():
    wave = _sine_capture(n=2048)
    a = black_box_target_features(list(wave))
    b = black_box_target_features(list(wave))
    assert a["sin_coefficients"] == b["sin_coefficients"]
    assert a["cos_coefficients"] == b["cos_coefficients"]
