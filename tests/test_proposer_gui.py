import os
from pathlib import Path

from dexfrag.proposer_gui import _fmt, _number, _project_root, _resolve


def test_project_root_is_repository():
    root = _project_root()
    assert (root / "src" / "dexfrag" / "proposer_gui.py").is_file()


def test_resolve_falls_back_to_project_root(tmp_path):
    original = Path.cwd()
    os.chdir(tmp_path)
    try:
        # Nothing exists in the unrelated working directory, so a relative
        # path must resolve against the repository instead of failing.
        assert not Path("pyproject.toml").exists()
        resolved = _resolve("pyproject.toml")
        assert resolved.is_absolute()
        assert resolved.is_file()
        assert resolved.parent == _project_root()

        # Absolute paths are never rewritten.
        absolute = tmp_path / "elsewhere.parquet"
        assert _resolve(str(absolute)) == absolute
    finally:
        os.chdir(original)


def test_resolve_prefers_working_directory(tmp_path):
    original = Path.cwd()
    os.chdir(tmp_path)
    try:
        (tmp_path / "local.parquet").write_bytes(b"")
        assert _resolve("local.parquet") == Path("local.parquet")
    finally:
        os.chdir(original)


def test_number_and_format_helpers():
    assert _number("10", "Epochs") == 10
    assert _number("", "Max rows", allow_empty=True) is None
    assert _number("8", "Batch size") == 8
    for bad in ("abc", "1.5"):
        try:
            _number(bad, "Epochs")
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad} should be rejected")
    try:
        _number("0", "Epochs")
    except ValueError:
        pass
    else:
        raise AssertionError("zero epochs should be rejected")

    assert _fmt(1.5) == "1.5000"
    assert _fmt(float("inf")) == "—"
    assert _fmt(None) == "—"
    assert _fmt(3) == "3"
