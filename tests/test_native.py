import math

import pytest

from dexfrag.native import NativeRenderer, NativeRendererError, DEFAULT_EXECUTABLE
from dexfrag.patch import blank_patch, validate_patch, patch_key

pytestmark = pytest.mark.skipif(
    not DEFAULT_EXECUTABLE.is_file(),
    reason="native/bin/DexfragglerReference.exe is required for native renderer tests",
)


@pytest.fixture(scope="module")
def renderer():
    r = NativeRenderer()
    yield r
    r.close()


def test_renders_reference_contract(renderer):
    capture = renderer.render(blank_patch())
    assert capture.sample_rate == 48000
    assert capture.velocity == 100
    assert capture.offset_samples == 7200
    assert capture.capture_samples == 4096
    assert capture.notes == (45, 57, 69)
    assert len(capture.waveforms) == 3
    for wave in capture.waveforms:
        assert len(wave) == 4096
        assert all(math.isfinite(x) for x in wave)


def test_exact_patch_identity_matches_render_input(renderer):
    patch = blank_patch()
    capture = renderer.render(patch)
    assert capture.patch_key == patch_key(patch)
    assert capture.patch == validate_patch(patch)


def test_deterministic_repeated_renders(renderer):
    patch = blank_patch()
    first = renderer.render(patch)
    second = renderer.render(patch)
    assert first.waveforms == second.waveforms


def test_renderer_provenance_recorded(renderer):
    capture = renderer.render(blank_patch())
    assert len(capture.binary_sha256) == 64
    assert capture.source_manifest


def test_silent_patch_yields_zero_waveforms(renderer):
    silent = blank_patch().to_dict()
    for op in silent["operators"]:
        op["level"] = 0
    capture = renderer.render(silent)
    for wave in capture.waveforms:
        assert all(x == 0.0 for x in wave)


def test_missing_executable_raises_clear_error(tmp_path):
    with pytest.raises(NativeRendererError):
        NativeRenderer(executable_path=tmp_path / "does-not-exist.exe")
