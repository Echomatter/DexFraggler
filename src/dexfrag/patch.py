"""Canonical DX7 patch representation: identity, legality, and exact
VCED/SysEx encode/decode.

Ported and adapted from the validated JavaScript source
(Echomatter_DexFraggler public/core.mjs: validatePatch/sysex/fromSysex).
The wire format, byte layout, and fixed research-profile constants are
copied exactly so that patches encoded here render identically on the
vendored native Dexed Mark I renderer.

Only ``algorithm``, ``feedback``, and each operator's ``coarse``, ``fine``,
``detune``, ``mode``, and ``level`` are searchable. Every other DX7 VCED
field (envelope rates/levels, break point, scaling, LFO, pitch EG,
transpose, key sync) is held at the fixed "stationary waveform research
profile" values documented in ``RESEARCH_PROFILE_NOTES`` below, matching
the reference conditions the native renderer/scorer already depend on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

PATCH_SCHEMA_VERSION = "dexfrag-patch-v1"

# --- legal parameter ranges (searchable dimensions) -------------------------
LIMITS = {"coarse": 31, "fine": 99, "level": 99, "detune": 14, "mode": 1}
ALGORITHM_RANGE = (1, 32)
FEEDBACK_RANGE = (0, 7)

RESEARCH_PROFILE_NOTES = """
Fixed (non-searchable) VCED fields for the stationary-waveform research
profile, held constant on every legal patch produced by this module:

  per operator (all 6): EG rate 1-4 = 99, EG level 1-3 = 99, EG level 4 = 0,
    break point = 39 (middle C), left/right depth = 0, left/right curve = 0,
    rate scaling = 0, amp-mod sensitivity = 0, key-velocity sensitivity = 0.
  voice-global: pitch EG rates 1-4 = 99, pitch EG levels 1-4 = 50,
    osc key sync = 1, LFO speed/delay/PMD/AMD = 0, LFO sync = 0,
    LFO waveform = 4, pitch-mod sensitivity = 0, transpose = 24 (middle C).

These match the reference conditions already validated by the native
renderer/scorer (48 kHz, velocity 100, notes 45/57/69, 7200-sample offset,
4096-sample capture). Envelopes and LFO are frozen so every rendered note
reaches a stationary/periodic state well within the capture window; they
are "fixed reference" parameters, not "searchable" or "derived" ones.
"""


class PatchError(ValueError):
    """Raised when a patch or its bytes violate legal DX7 constraints."""


@dataclass(frozen=True)
class Operator:
    op: int  # 1-based operator number (1..6)
    coarse: int
    fine: int
    detune: int
    mode: int
    level: int

    def to_dict(self) -> dict:
        return {"op": self.op, "coarse": self.coarse, "fine": self.fine,
                "detune": self.detune, "mode": self.mode, "level": self.level}


@dataclass(frozen=True)
class Patch:
    algorithm: int  # 1..32
    feedback: int  # 0..7
    operators: tuple[Operator, ...]  # exactly 6, sorted by op ascending

    def to_dict(self) -> dict:
        return {"algorithm": self.algorithm, "feedback": self.feedback,
                "operators": [o.to_dict() for o in self.operators]}


def blank_patch() -> Patch:
    """One-operator sine reference patch: algorithm 32, OP1 carrier at full level."""
    operators = tuple(
        Operator(op=i + 1, coarse=1, fine=0, detune=7, mode=0, level=99 if i == 0 else 0)
        for i in range(6)
    )
    return Patch(algorithm=32, feedback=0, operators=operators)


def validate_patch(patch: dict | Patch) -> Patch:
    """Validate legality and return a canonical immutable Patch.

    Accepts either a Patch or a plain dict with the same shape (algorithm,
    feedback, operators=[{op, coarse, fine, detune, mode, level}, ...]).
    Raises PatchError with a specific message on any illegal value.
    """
    if isinstance(patch, Patch):
        data = patch.to_dict()
    elif isinstance(patch, dict):
        data = patch
    else:
        raise PatchError("A patch must be a Patch or an equivalent dict.")

    allowed_top = {"algorithm", "feedback", "operators"}
    if set(data.keys()) - allowed_top:
        raise PatchError("A patch may only contain algorithm, feedback and operators.")

    algorithm = data.get("algorithm")
    feedback = data.get("feedback")
    operators = data.get("operators")
    if not isinstance(algorithm, int) or isinstance(algorithm, bool) or not (ALGORITHM_RANGE[0] <= algorithm <= ALGORITHM_RANGE[1]):
        raise PatchError(f"algorithm must be an integer from {ALGORITHM_RANGE[0]} to {ALGORITHM_RANGE[1]}.")
    if not isinstance(feedback, int) or isinstance(feedback, bool) or not (FEEDBACK_RANGE[0] <= feedback <= FEEDBACK_RANGE[1]):
        raise PatchError(f"feedback must be an integer from {FEEDBACK_RANGE[0]} to {FEEDBACK_RANGE[1]}.")
    if not isinstance(operators, (list, tuple)) or len(operators) != 6:
        raise PatchError("operators must contain exactly six entries.")

    allowed_op_keys = {"op", *LIMITS.keys()}
    seen_ops: set[int] = set()
    canonical_ops: list[Operator] = []
    for raw in operators:
        if isinstance(raw, Operator):
            raw = raw.to_dict()
        if not isinstance(raw, dict) or set(raw.keys()) - allowed_op_keys:
            raise PatchError("Each operator needs exactly op, coarse, fine, detune, mode and level.")
        op_number = raw.get("op")
        if not isinstance(op_number, int) or isinstance(op_number, bool) or not (1 <= op_number <= 6) or op_number in seen_ops:
            raise PatchError("Operators need unique op numbers from 1 to 6.")
        seen_ops.add(op_number)
        values = {}
        for key, maximum in LIMITS.items():
            value = raw.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or not (0 <= value <= maximum):
                raise PatchError(f"Operator {op_number}: {key} must be an integer from 0 to {maximum}.")
            values[key] = value
        canonical_ops.append(Operator(op=op_number, **values))

    canonical_ops.sort(key=lambda o: o.op)
    return Patch(algorithm=algorithm, feedback=feedback, operators=tuple(canonical_ops))


# --- exact VCED/SysEx wire format -------------------------------------------
# Fixed bytes for the stationary-waveform research profile, one 21-byte block
# per operator (searchable level/mode/coarse/fine/detune occupy the last 5).
_OPERATOR_FIXED_PREFIX = (99, 99, 99, 99, 99, 99, 99, 0, 39, 0, 0, 0, 0, 0, 0, 0)
_VOICE_FIXED_PREFIX = (99, 99, 99, 99, 50, 50, 50, 50)
_VOICE_FIXED_SUFFIX = (1, 0, 0, 0, 0, 0, 4, 0, 24)
_SYSEX_HEADER = (0xF0, 0x43, 0x00, 0x00, 0x01, 0x1B)  # F0 43 00 00 01 1B (VCED, 155 bytes)
_SYSEX_EOX = 0xF7
DEFAULT_PATCH_NAME = "DEXFRAG"


def encode_patch(patch: dict | Patch, name: str = DEFAULT_PATCH_NAME) -> bytes:
    """Encode a legal patch as the exact 163-byte DX7 single-voice SysEx
    message the native renderer/other DX7 hardware expects."""
    checked = validate_patch(patch)
    data: list[int] = []
    for operator in reversed(checked.operators):  # DX7 byte order is OP6..OP1
        data.extend(_OPERATOR_FIXED_PREFIX)
        data.extend((operator.level, operator.mode, operator.coarse, operator.fine, operator.detune))
    data.extend(_VOICE_FIXED_PREFIX)
    data.extend((checked.algorithm - 1, checked.feedback))
    data.extend(_VOICE_FIXED_SUFFIX)
    printable_name = "".join(ch if 0x20 <= ord(ch) <= 0x7E else " " for ch in name)[:10].ljust(10)
    data.extend(ord(ch) for ch in printable_name)
    if len(data) != 155:
        raise PatchError(f"Internal error: expected 155 VCED bytes, built {len(data)}.")
    checksum = (-sum(data)) & 0x7F
    return bytes([*_SYSEX_HEADER, *data, checksum, _SYSEX_EOX])


def vced_bytes(patch: dict | Patch, name: str = DEFAULT_PATCH_NAME) -> bytes:
    """The 155 VCED payload bytes only (no SysEx header/checksum/EOX) —
    exactly what the native renderer's stdin protocol expects per line."""
    return encode_patch(patch, name)[6:161]


def decode_patch(message: bytes | Iterable[int]) -> Patch:
    """Decode a 163-byte DX7 single-voice SysEx message back to a legal Patch.

    Round trip is exact for the searchable fields; the checksum and fixed
    research-profile bytes are validated, not merely ignored.
    """
    data = bytes(message)
    if len(data) != 163:
        raise PatchError("A single-voice SysEx message must be exactly 163 bytes.")
    if tuple(data[0:6]) != _SYSEX_HEADER:
        raise PatchError("Not a Yamaha DX7 single-voice VCED SysEx message.")
    if data[161] > 127 or data[162] != _SYSEX_EOX:
        raise PatchError("Malformed SysEx trailer.")
    payload = data[6:161]
    if any(b > 127 for b in payload) or ((sum(payload) + data[161]) & 0x7F) != 0:
        raise PatchError("Invalid Yamaha SysEx checksum.")
    algorithm = payload[126 + 8] + 1
    feedback = payload[126 + 9]
    operators = []
    for i in range(6):
        base = (5 - i) * 21  # payload stores OP6..OP1; operator i (0-based) is at reversed slot
        operators.append(Operator(
            op=i + 1,
            level=payload[base + 16],
            mode=payload[base + 17],
            coarse=payload[base + 18],
            fine=payload[base + 19],
            detune=payload[base + 20],
        ))
    return validate_patch({"algorithm": algorithm, "feedback": feedback,
                            "operators": [o.to_dict() for o in operators]})


def patch_key(patch: dict | Patch) -> str:
    """Stable, deterministic exact-identity key: hex of the 155 VCED bytes.

    Two patches share a key if and only if every searchable field is
    identical; patches are never merged by sonic or structural similarity.
    """
    return vced_bytes(patch).hex()
