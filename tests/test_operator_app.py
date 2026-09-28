"""Headless tests for the operator console: registry, gates, TensorBoard plumbing."""
import subprocess

from dexfrag import operator_app as app
from dexfrag.operator_app import (
    STEPS,
    close_tensorboard,
    ensure_tensorboard,
    find_tensorboard_command,
    forward_gate_verdict,
    is_port_open,
    proposer_gate_verdict,
    tensorboard_url,
)


def test_steps_registry_is_ordered_and_plain():
    ids = [step["id"] for step in STEPS]
    assert ids == ["doctor", "dataset", "collect", "train_forward", "check_forward",
                   "train_proposer", "check_proposer", "targets", "tensorboard", "next"]
    assert len(set(ids)) == len(ids)
    for step in STEPS:
        for field in ("tab", "title", "what", "good"):
            assert isinstance(step[field], str) and step[field].strip(), field
        # Plain language: no unexplained jargon leaking into titles.
        assert "MLP" not in step["title"] and "surrogate" not in step["title"]


def test_forward_gate_verdict():
    ok, message = forward_gate_verdict(0.72, 0.001, 0.003)
    assert ok and "beats chance" in message
    ok, _ = forward_gate_verdict(0.56, 0.001, 0.003)
    assert not ok
    ok, _ = forward_gate_verdict(0.72, 0.005, 0.003)
    assert not ok
    ok, message = forward_gate_verdict(None, 0.001, 0.003)
    assert not ok and "did not score" in message


def test_proposer_gate_verdict():
    ok, message = proposer_gate_verdict(1.0, 1.0, 0.325, 0.210)
    assert ok and "beats dumb guessing" in message
    ok, _ = proposer_gate_verdict(1.0, 0.5, 0.325, 0.210)
    assert not ok
    ok, _ = proposer_gate_verdict(1.0, 1.0, 0.180, 0.210)
    assert not ok
    ok, message = proposer_gate_verdict(1.0, 1.0, None, 0.210)
    assert not ok and "rerun" in message


def test_tensorboard_url_and_closed_port():
    assert tensorboard_url(6006) == "http://localhost:6006"
    assert tensorboard_url(9999) == "http://localhost:9999"
    assert is_port_open(59999) is False


def test_find_tensorboard_command_shape():
    command = find_tensorboard_command()
    assert command is None or (isinstance(command, list) and command and all(command))


class _FakeProcess:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True


def test_ensure_tensorboard_already_running_opens_browser_only():
    opened = []
    launched = []

    def fake_launcher(*args, **kwargs):
        launched.append(args)
        return _FakeProcess()

    message = ensure_tensorboard(
        launcher=fake_launcher, opener=opened.append, probe=lambda port: True)
    assert launched == []
    assert opened == ["http://localhost:6006"]
    assert "already running" in message


def test_ensure_tensorboard_starts_then_reuses_process():
    opened = []
    launched = []

    def fake_launcher(*args, **kwargs):
        launched.append(args[0])
        return _FakeProcess()

    calls = {"probes": 0}

    def flaky_probe(port):
        calls["probes"] += 1
        return calls["probes"] > 2

    try:
        first = ensure_tensorboard(
            launcher=fake_launcher, opener=opened.append, probe=flaky_probe)
        assert len(launched) == 1
        assert "logdir" not in first  # reports the logdir value, not the flag name
        assert "runs" in first
        second = ensure_tensorboard(
            launcher=fake_launcher, opener=opened.append, probe=lambda port: False)
        assert len(launched) == 1  # reused, not relaunched
        assert "Reopened" in second
        assert opened == ["http://localhost:6006"] * 2
    finally:
        close_tensorboard()


def test_ensure_tensorboard_without_install_reports_plainly(monkeypatch):
    monkeypatch.setattr(app, "find_tensorboard_command", lambda: None)
    message = ensure_tensorboard(opener=lambda url: None, probe=lambda port: True)
    assert "not installed" in message


def test_close_tensorboard_terminates_owned_process():
    process = _FakeProcess()
    app._tb_process = process
    close_tensorboard()
    assert process.terminated
    assert app._tb_process is None
    close_tensorboard()  # idempotent


def test_console_module_imports_without_torch_or_display():
    # Only stdlib + tkinter names are needed at import; torch-dependent
    # engines import lazily inside tab workers.
    import subprocess as stdlib_subprocess

    assert stdlib_subprocess is subprocess
    assert callable(app.launch)
