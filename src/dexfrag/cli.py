"""DexFraggler research CLI: doctor, structure audit, dataset inspect, monitor."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer

from . import __version__
from .algorithms import structural_audit_report
from .budget import Budget, BudgetCaps
from .collector import DEFAULT_PLAN, collect as run_collect
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


@app.command(name="dataset-coverage")
def dataset_coverage(dataset: Path = typer.Argument(..., help="Path to a native-observation Parquet dataset.")) -> None:
    """Full Phase 2 coverage report: structure, lineage, splits, versions, budget."""
    from collections import Counter

    table = read_observations(dataset)
    budget = Budget.load(dataset)
    report: dict = {
        "path": str(dataset),
        "observations": table.num_rows,
        "renders_attempted_lifetime": budget.renders_attempted,
        "renders_valid_lifetime": budget.renders_valid,
        "elapsed_seconds_lifetime": budget.elapsed_seconds,
        "dataset_bytes": dataset.stat().st_size if dataset.exists() else 0,
    }
    if table.num_rows == 0:
        typer.echo(json.dumps(report, indent=2))
        return

    algorithm_topology_signature = table.column("algorithm_topology_signature").to_pylist()
    algorithms = table.column("algorithm").to_pylist()
    validity = table.column("validity_class").to_pylist()
    sources = table.column("acquisition_source").to_pylist()
    splits = table.column("split").to_pylist()
    lineage_roots = table.column("lineage_root_key").to_pylist()
    parent_keys = table.column("parent_key").to_pylist()
    binary_shas = table.column("binary_sha256").to_pylist()
    feature_versions = table.column("feature_version").to_pylist()
    benchmark_flags = table.column("benchmark_holdout").to_pylist()
    algo_feedback = table.column("feedback").to_pylist()
    patch_jsons = table.column("patch_json").to_pylist()
    canonical_frames_jsons = table.column("canonical_frames_json").to_pylist()

    # Coarse-ratio-family coverage: bucket every operator's coarse value
    # into "integer-family" (0..15, matching structure_aware/coherent_ratio's
    # low-ratio range) vs "high" (16..31), plus a coherent-family fine==0
    # counter to make coherent_ratio_exploration's effect on the corpus
    # directly visible without re-deriving it from acquisition_source alone.
    coarse_bucket_counts = {"low_0_15": 0, "high_16_31": 0}
    fine_bucket_counts = {"0": 0, "1_25": 0, "26_50": 0, "51_75": 0, "76_99": 0}
    detune_bucket_counts = {"0": 0, "1_25": 0, "26_50": 0, "51_75": 0, "76_99": 0}
    output_level_bucket_counts = {"0": 0, "1_25": 0, "26_50": 0, "51_75": 0, "76_99": 0}
    carrier_count_distribution = Counter()
    exact_integer_ratio_operator_count = 0
    total_operators = 0
    for patch_json in patch_jsons:
        patch = json.loads(patch_json)
        carrier_count_distribution[len(patch["operators"])] += 1
        for operator in patch["operators"]:
            total_operators += 1
            coarse = operator["coarse"]
            if coarse <= 15:
                coarse_bucket_counts["low_0_15"] += 1
            else:
                coarse_bucket_counts["high_16_31"] += 1
            fine = operator["fine"]
            if fine == 0:
                fine_bucket_counts["0"] += 1
            elif fine <= 25:
                fine_bucket_counts["1_25"] += 1
            elif fine <= 50:
                fine_bucket_counts["26_50"] += 1
            elif fine <= 75:
                fine_bucket_counts["51_75"] += 1
            else:
                fine_bucket_counts["76_99"] += 1
            detune = operator["detune"]
            if detune == 0:
                detune_bucket_counts["0"] += 1
            elif detune <= 25:
                detune_bucket_counts["1_25"] += 1
            elif detune <= 50:
                detune_bucket_counts["26_50"] += 1
            elif detune <= 75:
                detune_bucket_counts["51_75"] += 1
            else:
                detune_bucket_counts["76_99"] += 1
            output_level = operator["level"]
            if output_level == 0:
                output_level_bucket_counts["0"] += 1
            elif output_level <= 25:
                output_level_bucket_counts["1_25"] += 1
            elif output_level <= 50:
                output_level_bucket_counts["26_50"] += 1
            elif output_level <= 75:
                output_level_bucket_counts["51_75"] += 1
            else:
                output_level_bucket_counts["76_99"] += 1
            if operator["fine"] == 0 and operator["detune"] == 7:
                exact_integer_ratio_operator_count += 1

    periodicity_ratios = []
    for frames_json in canonical_frames_jsons:
        frames = json.loads(frames_json)
        for frame_data in frames.values():
            if "periodicity_ratio" in frame_data:
                periodicity_ratios.append(frame_data["periodicity_ratio"])
    spectral_diversity = {
        "periodicity_ratio_mean": (
            sum(periodicity_ratios) / len(periodicity_ratios) if periodicity_ratios else 0.0
        ),
        "periodicity_ratio_std": (
            (sum((r - sum(periodicity_ratios) / len(periodicity_ratios)) ** 2 for r in periodicity_ratios) / len(periodicity_ratios)) ** 0.5
            if periodicity_ratios else 0.0
        ),
        "periodicity_ratio_count": len(periodicity_ratios),
    }

    renders_per_second = (
        budget.renders_valid / budget.elapsed_seconds if budget.elapsed_seconds > 0 else 0.0
    )
    duplicate_attempts_count = budget.renders_attempted - table.num_rows

    report.update({
        "by_algorithm": dict(sorted(Counter(algorithms).items())),
        "by_algorithm_topology_signature": dict(Counter(algorithm_topology_signature)),
        "by_validity_class": dict(Counter(validity)),
        "by_acquisition_source": dict(Counter(sources)),
        "by_split": dict(Counter(splits)),
        "by_feedback": dict(sorted(Counter(algo_feedback).items())),
        "unique_lineage_families": len(set(lineage_roots)),
        "mutation_derived_rows": sum(1 for p in parent_keys if p is not None),
        "benchmark_holdout_rows": sum(1 for b in benchmark_flags if b),
        "renderer_binary_sha256_distribution": dict(Counter(binary_shas)),
        "feature_version_distribution": dict(Counter(feature_versions)),
        "coarse_ratio_bucket_distribution": coarse_bucket_counts,
        "fine_bucket_distribution": fine_bucket_counts,
        "detune_bucket_distribution": detune_bucket_counts,
        "output_level_bucket_distribution": output_level_bucket_counts,
        "carrier_count_distribution": dict(sorted(carrier_count_distribution.items())),
        "spectral_diversity_summary": spectral_diversity,
        "renders_per_second": renders_per_second,
        "duplicate_attempts_count": duplicate_attempts_count,
        "exact_integer_ratio_operator_fraction": (
            exact_integer_ratio_operator_count / total_operators if total_operators else 0.0
        ),
    })
    typer.echo(json.dumps(report, indent=2))


@app.command()
def collect(
    dataset: Path = typer.Argument(..., help="Path to the native-observation Parquet dataset (created if missing)."),
    seed: int = typer.Option(0, help="Deterministic RNG seed for acquisition sources and mutation choices."),
    coherent_ratio: int = typer.Option(DEFAULT_PLAN["coherent_ratio"], help="Candidates from coherent-ratio exploration (deliberately periodic/stationary patches)."),
    broad_structured: int = typer.Option(DEFAULT_PLAN["broad_structured"], help="Candidates from broad structured exploration."),
    random_legal: int = typer.Option(DEFAULT_PLAN["random_legal"], help="Candidates from random legal exploration."),
    structure_aware: int = typer.Option(DEFAULT_PLAN["structure_aware"], help="Candidates from structure-aware exploration."),
    local_mutation: int = typer.Option(DEFAULT_PLAN["local_mutation"], help="Candidates from local mutation of existing valid observations."),
    max_renders: int = typer.Option(None, help="Hard cap on native renders attempted this run (required for bounded/smoke runs)."),
    max_seconds: float = typer.Option(None, help="Hard cap on wall-clock seconds this run."),
    max_dataset_bytes: int = typer.Option(None, help="Hard cap on dataset file size in bytes."),
    executable: Path = typer.Option(DEFAULT_EXECUTABLE, help="Native renderer executable path."),
    no_waveforms: bool = typer.Option(False, help="Do not store raw 4096-sample waveforms (canonical frames only; smaller dataset)."),
) -> None:
    """Run a bounded, resumable native-observation collection session.

    No default cap is applied automatically -- pass --max-renders (and/or
    --max-seconds / --max-dataset-bytes) explicitly. This mirrors the plan's
    "no unbounded default" requirement for operator-ready profiles.
    """
    plan = {
        "coherent_ratio": coherent_ratio,
        "broad_structured": broad_structured,
        "random_legal": random_legal,
        "structure_aware": structure_aware,
        "local_mutation": local_mutation,
    }
    caps = BudgetCaps(max_renders_attempted=max_renders, max_elapsed_seconds=max_seconds, max_dataset_bytes=max_dataset_bytes)
    summary = run_collect(
        dataset, plan=plan, seed=seed, caps=caps, executable_path=executable,
        include_waveforms=not no_waveforms,
    )
    typer.echo(json.dumps(summary.to_dict(), indent=2))


@app.command()
def monitor() -> None:
    """Print the TensorBoard command for the local runs/ directory."""
    typer.echo("tensorboard --logdir runs")


@app.command(name="train-forward")
def train_forward(
    corpus: Path = typer.Argument(..., help="Native-observation corpus."),
    checkpoint_dir: Path = typer.Option(Path("checkpoints/forward"), help="Checkpoint directory."),
    epochs: int = typer.Option(1, min=1),
    max_steps: int | None = typer.Option(None, min=1),
    max_rows: int | None = typer.Option(None, min=1),
    batch_size: int = typer.Option(4, min=1),
    learning_rate: float = typer.Option(1e-3, min=0.0),
    device: str = typer.Option("auto", help="cpu, cuda, or auto."),
    seed: int = typer.Option(0),
    tensorboard_dir: Path | None = typer.Option(None, help="TensorBoard log directory (optional)."),
    patience: int | None = typer.Option(None, min=1, help="Early-stopping patience: epochs without validation improvement before stopping."),
) -> None:
    """Train the bounded Phase 3 forward model on train/validation only."""
    from .forward_training import TrainConfig, train

    config = TrainConfig(
        corpus=corpus,
        checkpoint_dir=checkpoint_dir,
        epochs=epochs,
        max_steps=max_steps,
        max_rows=max_rows,
        batch_size=batch_size,
        learning_rate=learning_rate,
        device=device,
        seed=seed,
        tensorboard_dir=tensorboard_dir,
        patience=patience,
    )
    typer.echo(json.dumps(train(config), indent=2))


@app.command(name="evaluate-forward")
def evaluate_forward(
    corpus: Path = typer.Argument(..., help="Native-observation corpus."),
    checkpoint: Path = typer.Argument(..., help="Trained forward-model checkpoint."),
    max_targets: int = typer.Option(32, min=1, help="Max held-out targets for ranking diagnostics."),
    max_candidates: int = typer.Option(500, min=1, help="Max candidate pool size for ranking diagnostics."),
    device: str = typer.Option("cpu", help="cpu, cuda, or auto."),
    seed: int = typer.Option(0, help="Deterministic seed for target/candidate sampling."),
) -> None:
    """Evaluate a trained forward checkpoint on the protected test split."""
    from .forward_eval import evaluate_forward as run_eval_forward

    summary = run_eval_forward(
        corpus, checkpoint, device=device,
        max_targets=max_targets, max_candidates=max_candidates, seed=seed,
    )
    typer.echo(json.dumps(summary, indent=2))


@app.command(name="train-proposer")
def train_proposer(
    corpus: Path = typer.Argument(..., help="Native-observation corpus."),
    checkpoint_dir: Path = typer.Option(Path("checkpoints/proposer"), help="Checkpoint directory."),
    epochs: int = typer.Option(1, min=1),
    max_steps: int | None = typer.Option(None, min=1),
    max_rows: int | None = typer.Option(2048, min=2, help="Maximum train plus validation observations retained for this run."),
    batch_size: int = typer.Option(8, min=1),
    learning_rate: float = typer.Option(1e-3, min=0.0),
    device: str = typer.Option("auto", help="cpu, cuda, or auto."),
    seed: int = typer.Option(0),
    tensorboard_dir: Path | None = typer.Option(None, help="TensorBoard log directory (optional)."),
    patience: int | None = typer.Option(None, min=1),
    max_seconds: float | None = typer.Option(None, min=0.0),
    candidate_count: int = typer.Option(16, min=1, max=256),
    label_smoothing: float = typer.Option(0.05, min=0.0),
) -> None:
    """Train the bounded Phase 4 distribution proposer on train/validation only."""
    from .proposer_training import ProposerTrainConfig, train

    config = ProposerTrainConfig(
        corpus=corpus,
        checkpoint_dir=checkpoint_dir,
        epochs=epochs,
        max_steps=max_steps,
        max_rows=max_rows,
        batch_size=batch_size,
        learning_rate=learning_rate,
        device=device,
        seed=seed,
        tensorboard_dir=tensorboard_dir,
        patience=patience,
        max_seconds=max_seconds,
        candidate_count=candidate_count,
        label_smoothing=label_smoothing,
    )
    typer.echo(json.dumps(train(config), indent=2))


@app.command(name="evaluate-proposer")
def evaluate_proposer(
    corpus: Path = typer.Argument(..., help="Native-observation corpus."),
    checkpoint: Path = typer.Argument(..., help="Trained proposer checkpoint."),
    forward_checkpoint: Path | None = typer.Option(None, help="Optional Phase 3 forward checkpoint for surrogate ranking."),
    max_targets: int = typer.Option(8, min=1),
    candidate_count: int = typer.Option(16, min=1, max=256),
    native_budget: int = typer.Option(4, min=0, max=64),
    max_total_renders: int = typer.Option(16, min=0),
    device: str = typer.Option("cpu", help="cpu, cuda, or auto."),
    seed: int = typer.Option(0),
    temperature: float = typer.Option(1.0, min=0.0),
    include_baselines: bool = typer.Option(True, help="Include random, structured, and retrieval baselines."),
    report: Path | None = typer.Option(None, help="Optional JSON report output path."),
) -> None:
    """Evaluate legal candidate diversity, optional forward ranking, and bounded native quality."""
    from .proposer_eval import evaluate_proposer as run_evaluate_proposer
    from .proposer_eval import write_evaluation_report

    summary = run_evaluate_proposer(
        corpus,
        checkpoint,
        forward_checkpoint=forward_checkpoint,
        device=device,
        max_targets=max_targets,
        candidate_count=candidate_count,
        native_budget=native_budget,
        max_total_renders=max_total_renders,
        seed=seed,
        temperature=temperature,
        include_baselines=include_baselines,
    )
    if report is not None:
        summary["report_path"] = str(write_evaluation_report(summary, report))
    typer.echo(json.dumps(summary, indent=2))


@app.command(name="generate-targets")
def generate_targets(
    folder: Path = typer.Option(Path("datasets/target-wavetables"), help="Output folder for generated target wavetables."),
    tables: int = typer.Option(10, min=1, help="Number of wavetables to generate."),
    frame_size: int = typer.Option(2048, min=128, help="Samples per frame (canonical target frame is 2048)."),
    frame_count: int = typer.Option(256, min=1, help="Frames per table (canonical target count is 256)."),
    seed: int = typer.Option(42, help="Deterministic generation seed."),
    zip_delete: bool = typer.Option(False, help="Zip the generated WAVs, then delete the loose WAVs."),
) -> None:
    """Generate deterministic black-box target wavetables (curriculum producer).

    Produces the 'generated hard wavetable curriculum' consumed by the inverse
    search / active-learning pipeline as black-box targets. Generator
    provenance never enters target records -- route through
    ``dexfrag target-ingest`` to create waveform-derived target records.
    """
    from .curriculum import APP_NAME, GeneratorConfig, generate_wavetables

    config = GeneratorConfig(
        tables=tables,
        frame_size=frame_size,
        frame_count=frame_count,
        seed=seed,
        zip_and_delete=zip_delete,
        folder=folder,
    )
    last_stage: str | None = None
    last_percent = -5.0

    def progress(update):
        nonlocal last_stage, last_percent
        stage_changed = update.stage != last_stage
        enough_progress = update.overall_percent >= last_percent + 5.0
        finished = update.overall_percent >= 100.0
        if stage_changed or enough_progress or finished:
            print(f"[{update.overall_percent:6.2f}%] {update.message}")
            last_stage = update.stage
            last_percent = update.overall_percent

    print(APP_NAME)
    print(
        f"Tables={config.tables} | Frame size={config.frame_size} | "
        f"Frames={config.frame_count} | Seed={config.seed}"
    )
    try:
        created_files, archive_path = generate_wavetables(config, progress=progress)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise typer.Exit(code=1)
    typer.echo(
        json.dumps(
            {
                "tables_created": len(created_files),
                "folder": str(Path(config.folder).expanduser().resolve()),
                "archive": str(archive_path) if archive_path else None,
            },
            indent=2,
        )
    )


@app.command(name="target-ingest")
def target_ingest(
    folder: Path = typer.Argument(..., help="Folder of generated target wavetables (*.wav)."),
    output: Path = typer.Option(Path("datasets/target-records.parquet"), help="Target-records Parquet output."),
    experiment_id: str = typer.Option("curriculum-v1", help="Opaque experiment id (allow-listed target bookkeeping)."),
) -> None:
    """Ingest generated wavetables as black-box target records.

    Every frame becomes one TARGET_RECORD_SCHEMA row carrying waveform-derived
    features only (validate_wavetable + black_box_target_features). Generator
    provenance (seed, recipe, multiplex count, ...) is rejected at the
    boundary by FORBIDDEN_TARGET_KEYS.
    """
    from .targets import ingest_wavetable_folder

    summary = ingest_wavetable_folder(folder, output, experiment_id=experiment_id)
    typer.echo(json.dumps(summary, indent=2))


@app.command()
def gui(
    dataset: Path = typer.Option(Path("datasets/main.parquet"), help="Dataset to create or resume."),
    max_renders: int = typer.Option(12000, min=1, help="Cumulative render cap for the Phase 2 operator gate."),
    seed: int = typer.Option(42, help="Deterministic sampling seed."),
) -> None:
    """Show progress for the documented Phase 2 operator-gate sampling profile."""
    from .gui import launch
    launch(dataset, max_renders=max_renders, seed=seed)


@app.command(name="proposer-gui")
def proposer_gui(
    corpus: Path = typer.Option(Path("datasets/main.parquet"), help="Native-observation corpus."),
    checkpoint_dir: Path = typer.Option(Path("checkpoints/inverse-proposer"), help="Checkpoint directory."),
    forward_checkpoint: Path = typer.Option(Path("checkpoints/forward-operator/best.pt"), help="Phase 3 forward ranker for evaluation."),
    report: Path = typer.Option(Path("reports/phase4.json"), help="Evaluation report output path."),
    epochs: int = typer.Option(10, min=1, help="Training rounds to attempt."),
    max_rows: int = typer.Option(2048, min=2, help="Maximum train plus validation observations retained."),
    batch_size: int = typer.Option(8, min=1),
    seed: int = typer.Option(0),
    device: str = typer.Option("auto", help="cpu, cuda, or auto."),
) -> None:
    """Windowed Phase 4 proposer training with a live progress bar and counts."""
    from .proposer_gui import launch

    launch(
        corpus, checkpoint_dir=checkpoint_dir, forward_checkpoint=forward_checkpoint,
        report=report, epochs=epochs, max_rows=max_rows, batch_size=batch_size,
        seed=seed, device=device,
    )


if __name__ == "__main__":
    app()
