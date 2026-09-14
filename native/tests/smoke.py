"""End-to-end protocol/audio checks. Prints a compact report, never PCM arrays."""
import hashlib
import argparse
import json
import math
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--executable", type=Path, default=ROOT / "build/Release/DexfragglerReference.exe")
parser.add_argument("--source-root", type=Path, help="Optionally compare to an independent original source tree.")
args = parser.parse_args()
EXE = args.executable.resolve()


def init_patch():
    patch = [0] * 155
    for op in range(6):
        offset = op * 21
        patch[offset:offset + 8] = [99, 99, 99, 60, 99, 99, 99, 0]
        patch[offset + 8] = 39
        patch[offset + 16] = 99 if op == 5 else 0
        patch[offset + 18] = 1
        patch[offset + 20] = 7
    patch[126:134] = [99] * 4 + [50] * 4
    patch[136] = 1
    patch[137] = 35
    patch[141] = 1
    patch[142] = 4
    patch[144] = 24
    patch[145:155] = list(b"INIT SINE ")
    return patch


def frequency(samples):
    crossings = []
    for i in range(1, len(samples)):
        if samples[i - 1] <= 0 < samples[i]:
            crossings.append(i - 1 - samples[i - 1] / (samples[i] - samples[i - 1]))
    assert len(crossings) > 2
    return 48000 * (len(crossings) - 1) / (crossings[-1] - crossings[0])


process = subprocess.Popen([str(EXE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, bufsize=1)


def request(line):
    process.stdin.write(line + "\n")
    process.stdin.flush()
    raw = process.stdout.readline()
    assert raw, "Renderer exited before replying."
    return json.loads(raw)


patch = init_patch()
line = ",".join(map(str, patch))
first = request(line)
assert first["ok"] and first["sampleRate"] == 48000
assert first["notes"] == [45, 57, 69]
assert first["offsetSamples"] == 7200 and first["captureSamples"] == 4096
measurements = []
for note, waveform, expected in zip(first["notes"], first["waveforms"], [110, 220, 440]):
    assert len(waveform) == 4096
    assert all(math.isfinite(x) and -1 <= x <= 1 for x in waveform)
    assert all(x * 32768 == round(x * 32768) for x in waveform)
    measured = frequency(waveform)
    rms = math.sqrt(sum(x * x for x in waveform) / len(waveform))
    peak = max(abs(x) for x in waveform)
    assert abs(measured - expected) < 1
    assert 0.08 < rms < 0.10 and 0.12 < peak < 0.13
    measurements.append({"note": note, "expectedHz": expected, "measuredHz": measured,
                         "rms": rms, "peak": peak})
assert request(line) == first, "Fresh isolated renders must be deterministic."
assert not request("1 2 3")["ok"]
invalid = patch.copy()
invalid[134] = 32
assert not request(" ".join(map(str, invalid)))["ok"]
assert not request("x " + " ".join(map(str, patch[1:])))["ok"]
assert request(" ".join(map(str, patch))) == first, "Invalid requests must not stop the process."
silent = patch.copy()
for op in range(6):
    silent[op * 21 + 16] = 0
assert all(x == 0 for wave in request(" ".join(map(str, silent)))["waveforms"] for x in wave)
process.stdin.close()
assert process.wait(timeout=10) == 0
assert process.stderr.read() == "", "Renderer wrote diagnostics during the protocol."

manifest = json.loads((ROOT / "source-provenance.json").read_text(encoding="utf-8-sig"))
for item in manifest["files"]:
    copied = ROOT / item["path"]
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == item["sha256"], f"Source hash mismatch: {item['path']}"
    if args.source_root is not None:
        original = args.source_root / Path(item["path"]).relative_to("vendor")
        assert copied.read_bytes() == original.read_bytes(), f"Copy differs: {item['path']}"
report = {
    "ok": True,
    "executableSha256": hashlib.sha256(EXE.read_bytes()).hexdigest(),
    "sourceTreeCompared": args.source_root is not None,
    "checks": ["native executable protocol", "three 4096-sample arrays", "110/220/440Hz tuning",
               "finite bounded 16-bit PCM", "expected unnormalized carrier amplitude", "deterministic repeated requests",
               "CSV and whitespace input", "malformed/out-of-range input rejected", "process survives invalid requests",
               "silent patch", "clean stdout JSON and empty stderr", "vendored source hashes match manifest"],
    "measurements": measurements,
}
(ROOT / "tests/smoke-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
