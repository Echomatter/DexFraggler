"""DexFraggler research CLI: doctor, structure audit, dataset inspect, monitor."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer

from . import __version__
from .algorithms import structural_audit_report
from .features import canonical_frame, validate_wavetable
from .native import DEFAULT_EXECUTABLE, NativeRenderer, NativeRendererError
from .patch import blank_patch
from .storage import read_observations

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def doctor(executable: Path = typer.Option(DEFAULT_EXECUTABLE, help="Native renderer executable path.")) -> None:
    """Validate the local environment end to end, including one bounded native render."""
    report: dict = {"version": __version__, "checks": {}, "ok": True}

    def check(name: str, fn):
        try:
            value = fn()
            report["checks"][name] = {"ok": True, "detail": value}
        except Exception as error:  # noqa: BLE001 - doctor must report, not crash
            report["checks"][name] = {"ok": False, "detail": str(error)}
            report["ok"] = False

    def check_python():
        return f"Python {sys.version.split()[0]}"

    def check_numpy():
        import numpy
        return f"numpy {numpy.__version__}"

    def check_torch():
        import torch
        cuda = torch.cuda.is_available()
        return f"torch {torch.__version__} (cuda_available={cuda})"

    def check_pyarrow():
        import pyarrow
        return f"pyarrow {pyarrow.__version__}"

    def check_tensorboard_smoke():
        from torch.utils.tensorboard import SummaryWriter
        log_dir = Path("runs") / "doctor-smoke"
        writer = SummaryWriter(log_dir=str(log_dir))
        writer.add_scalar("doctor/smoke", 1.0, 0)
        writer.flush()
        writer.close()
        return f"wrote scalar to {log_dir}"

    def check_native_render():
        renderer = NativeRenderer(executable_path=executable)
        try:
            capture = renderer.render(blank_patch())
        finally:
            renderer.close()
        return {
            "binary_sha256": capture.binary_sha256,
            "notes": list(capture.notes),
            "sample_rate": capture.sample_rate,
            "capture_samples": capture.capture_samples,
        }

    def check_canonical_frame():
        renderer = NativeRenderer(executable_path=executable)
        try:
            capture = renderer.render(blank_patch())
        finally:
            renderer.close()
        frame = canonical_frame(capture.waveforms[1], capture.notes[1], max_harmonics=64)
        assert len(frame.samples) == 2048
        return {"bands": frame.bands, "periodicity_ratio": frame.periodicity_ratio}

    def check_algorithm_topology():
        audit = structural_audit_report()
        assert audit["all_32_present"]
        return {"algorithm_count": audit["algorithm_count"]}

    check("python_environment", check_python)
    check("numpy", check_numpy)
    check("torch", check_torch)
    check("pyarrow", check_pyarrow)
    check("tensorboard_smoke", check_tensorboard_smoke)
    check("algorithm_topology", check_algorithm_topology)
    check("native_render", check_native_render)
    check("canonical_frame_extraction", check_canonical_frame)

    typer.echo(json.dumps(report, indent=2))
    if not report["ok"]:
        raise typer.Exit(code=1)


@app.command(name="structure-audit")
def structure_audit(out: Path = typer.Option(None, help="Write the JSON report here as well as stdout.")) -> None:
    """Emit the machine-readable structural-reduction report (no search)."""
    report = structural_audit_report()
    text = json.dumps(report, indent=2)
    typer.echo(text)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")


@app.command(name="dataset-inspect")
def dataset_inspect(dataset: Path = typer.Argument(..., help="Path to a native-observation Parquet dataset.")) -> None:
    """Report basic coverage statistics for a native-observation dataset."""
    table = read_observations(dataset)
    if table.num_rows == 0:
        typer.echo(json.dumps({"path": str(dataset), "observations": 0}, indent=2))
        return
    algorithms = table.column("algorithm").to_pylist()
    validity = table.column("validity_class").to_pylist()
    sources = table.column("acquisition_source").to_pylist()
    splits = table.column("split").to_pylist()
    from collections import Counter
    report = {
        "path": str(dataset),
        "observations": table.num_rows,
        "by_algorithm": dict(sorted(Counter(algorithms).items())),
        "by_validity_class": dict(Counter(validity)),
        "by_acquisition_source": dict(Counter(sources)),
        "by_split": dict(Counter(splits)),
    }
    typer.echo(json.dumps(report, indent=2))


@app.command()
def monitor() -> None:
    """Print the TensorBoard command for the local runs/ directory."""
    typer.echo("tensorboard --logdir runs")


if __name__ == "__main__":
    app()
