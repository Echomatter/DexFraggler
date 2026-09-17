"""Wrapper around the vendored native Dexed Mark I renderer.

The renderer is a prebuilt Windows executable (native/bin/DexfragglerReference.exe)
speaking a simple line-oriented protocol over stdin/stdout: send 155
comma/whitespace-separated decimal VCED bytes, receive one JSON line with
three 4096-sample captures at notes 45/57/69 (A2/A3/A4), 48 kHz, velocity
100, starting 7200 samples after note-on. See native/README.md for the
full protocol description and native/source-provenance.json for exact
vendored-source SHA-256 provenance.

This module never redefines the reference conditions silently: every
capture is validated against the exact contract before being accepted as
a NativeObservation.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .patch import Patch, patch_key, validate_patch, vced_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXECUTABLE = REPO_ROOT / "native" / "bin" / "DexfragglerReference.exe"

EXPECTED_SAMPLE_RATE = 48000
EXPECTED_VELOCITY = 100
EXPECTED_OFFSET_SAMPLES = 7200
EXPECTED_CAPTURE_SAMPLES = 4096
EXPECTED_NOTES = (45, 57, 69)  # A2, A3, A4

NATIVE_OBSERVATION_VERSION = "dexfrag-native-observation-v1"


class NativeRendererError(RuntimeError):
    """Raised for renderer process failures or reference-contract violations."""


@dataclass
class NativeCapture:
    """One raw, contract-validated native render (before feature extraction)."""

    patch_key: str
    patch: Patch
    sample_rate: int
    velocity: int
    offset_samples: int
    capture_samples: int
    notes: tuple[int, ...]
    waveforms: tuple[tuple[float, ...], ...]  # one 4096-sample tuple per note
    binary_sha256: str
    source_manifest: str
    rendered_at: float

    def to_dict(self, include_waveforms: bool = True) -> dict:
        result = {
            "version": NATIVE_OBSERVATION_VERSION,
            "key": self.patch_key,
            "patch": self.patch.to_dict(),
            "sample_rate": self.sample_rate,
            "velocity": self.velocity,
            "offset_samples": self.offset_samples,
            "capture_samples": self.capture_samples,
            "notes": list(self.notes),
            "binary_sha256": self.binary_sha256,
            "source_manifest": self.source_manifest,
            "rendered_at": self.rendered_at,
        }
        if include_waveforms:
            result["waveforms"] = [list(w) for w in self.waveforms]
        return result


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class NativeRenderer:
    """Long-lived subprocess wrapper. One process renders many patches.

    Not thread-safe; use one instance per worker/thread. Automatically
    restarts once (and only once) after an unexpected process exit.
    """

    def __init__(self, executable_path: Path | str | None = None, timeout_seconds: float = 30.0):
        self.executable_path = Path(executable_path or DEFAULT_EXECUTABLE).resolve()
        if not self.executable_path.is_file():
            raise NativeRendererError(
                f"Native renderer executable not found at {self.executable_path}. "
                "Set an explicit path or restore native/bin/DexfragglerReference.exe."
            )
        self.binary_sha256 = _sha256_of_file(self.executable_path)
        self.source_manifest = str((self.executable_path.parents[1] / "source-provenance.json"))
        self.timeout_seconds = timeout_seconds
        self._restarted_once = False
        self._process: subprocess.Popen | None = None
        self._start_process()

    def _start_process(self) -> None:
        self._process = subprocess.Popen(
            [str(self.executable_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            try:
                self._process.stdin.close()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
        self._process = None

    def __enter__(self) -> "NativeRenderer":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _request(self, line: str) -> dict:
        assert self._process is not None
        if self._process.poll() is not None:
            if self._restarted_once:
                raise NativeRendererError("Native renderer process exited and was already restarted once.")
            self._restarted_once = True
            self._start_process()
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()
        raw = self._process.stdout.readline()
        if not raw:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise NativeRendererError(f"Native renderer produced no response (stderr: {stderr!r}).")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise NativeRendererError(f"Native renderer returned non-JSON output: {raw!r}") from error

    def render(self, patch: Patch | dict) -> NativeCapture:
        checked = validate_patch(patch)
        payload = vced_bytes(checked)
        line = ",".join(str(b) for b in payload)
        response = self._request(line)
        if not response.get("ok"):
            raise NativeRendererError(f"Native render failed: {response.get('error')!r}")
        self._validate_contract(response)
        waveforms = tuple(tuple(wave) for wave in response["waveforms"])
        return NativeCapture(
            patch_key=patch_key(checked),
            patch=checked,
            sample_rate=response["sampleRate"],
            velocity=response["velocity"],
            offset_samples=response["offsetSamples"],
            capture_samples=response["captureSamples"],
            notes=tuple(response["notes"]),
            waveforms=waveforms,
            binary_sha256=self.binary_sha256,
            source_manifest=self.source_manifest,
            rendered_at=time.time(),
        )

    @staticmethod
    def _validate_contract(response: dict) -> None:
        if response.get("sampleRate") != EXPECTED_SAMPLE_RATE:
            raise NativeRendererError("Native renderer sample rate does not match the reference contract.")
        if response.get("velocity") != EXPECTED_VELOCITY:
            raise NativeRendererError("Native renderer velocity does not match the reference contract.")
        if response.get("offsetSamples") != EXPECTED_OFFSET_SAMPLES:
            raise NativeRendererError("Native renderer offset does not match the reference contract.")
        if response.get("captureSamples") != EXPECTED_CAPTURE_SAMPLES:
            raise NativeRendererError("Native renderer capture length does not match the reference contract.")
        notes = tuple(response.get("notes", ()))
        if notes != EXPECTED_NOTES:
            raise NativeRendererError("Native renderer notes do not match the reference contract (A2/A3/A4).")
        waveforms = response.get("waveforms")
        if not isinstance(waveforms, list) or len(waveforms) != 3:
            raise NativeRendererError("Native renderer must return exactly three waveforms.")
        for wave in waveforms:
            if not isinstance(wave, list) or len(wave) != EXPECTED_CAPTURE_SAMPLES:
                raise NativeRendererError("Each native waveform must contain exactly 4096 samples.")
            if not all(isinstance(x, (int, float)) and _is_finite(x) for x in wave):
                raise NativeRendererError("Native renderer returned non-finite audio.")


def _is_finite(x: float) -> bool:
    return x == x and x not in (float("inf"), float("-inf"))
