import pytest

from dexfrag.patch import (
    Patch, Operator, blank_patch, validate_patch, encode_patch, decode_patch,
    patch_key, vced_bytes, PatchError,
)


def test_blank_patch_is_legal():
    patch = validate_patch(blank_patch())
    assert patch.algorithm == 32
    assert patch.feedback == 0
    assert len(patch.operators) == 6


def test_encode_decode_round_trip_exact():
    patch = blank_patch()
    message = encode_patch(patch)
    assert len(message) == 163
    decoded = decode_patch(message)
    assert decoded == validate_patch(patch)


def test_vced_bytes_length_and_range():
    payload = vced_bytes(blank_patch())
    assert len(payload) == 155
    assert all(0 <= b <= 127 for b in payload)


def test_patch_key_is_deterministic_and_sensitive_to_every_searchable_field():
    a = blank_patch()
    key_a = patch_key(a)
    assert key_a == patch_key(a)

    b_dict = a.to_dict()
    b_dict["operators"][0]["level"] = 50
    key_b = patch_key(b_dict)
    assert key_b != key_a

    c_dict = a.to_dict()
    c_dict["feedback"] = 3
    assert patch_key(c_dict) != key_a

    d_dict = a.to_dict()
    d_dict["algorithm"] = 1
    assert patch_key(d_dict) != key_a


def test_patch_identity_never_merges_distinct_legal_patches():
    a = blank_patch()
    b_dict = a.to_dict()
    b_dict["operators"][3]["fine"] = 1  # a tiny, sonically negligible change
    b = validate_patch(b_dict)
    assert patch_key(a) != patch_key(b)
    assert encode_patch(a) != encode_patch(b)


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(algorithm=0),
    lambda d: d.update(algorithm=33),
    lambda d: d.update(feedback=-1),
    lambda d: d.update(feedback=8),
])
def test_illegal_voice_level_fields_rejected(mutation):
    d = blank_patch().to_dict()
    mutation(d)
    with pytest.raises(PatchError):
        validate_patch(d)


def test_illegal_operator_fields_rejected():
    d = blank_patch().to_dict()
    d["operators"][0]["level"] = 100
    with pytest.raises(PatchError):
        validate_patch(d)

    d = blank_patch().to_dict()
    d["operators"][0]["op"] = 1
    d["operators"][1]["op"] = 1  # duplicate op number
    with pytest.raises(PatchError):
        validate_patch(d)


def test_decode_rejects_wrong_length_or_bad_checksum():
    message = bytearray(encode_patch(blank_patch()))
    with pytest.raises(PatchError):
        decode_patch(bytes(message[:-1]))
    corrupted = bytearray(message)
    corrupted[161] = (corrupted[161] + 1) % 128
    with pytest.raises(PatchError):
        decode_patch(bytes(corrupted))


def test_all_32_algorithms_produce_valid_patches():
    for algorithm in range(1, 33):
        d = blank_patch().to_dict()
        d["algorithm"] = algorithm
        patch = validate_patch(d)
        assert patch.algorithm == algorithm
        round_tripped = decode_patch(encode_patch(patch))
        assert round_tripped == patch
