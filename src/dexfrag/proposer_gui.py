"""Phase 4 proposer operator GUI: bounded training and evaluation with live counts."""
from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

DEFAULT_CORPUS = Path("datasets/main.parquet")
DEFAULT_CHECKPOINT_DIR = Path("checkpoints/inverse-proposer")
DEFAULT_FORWARD_CHECKPOINT = Path("checkpoints/forward-operator/best.pt")
DEFAULT_REPORT = Path("reports/phase4.json")
DEFAULT_TENSORBOARD_DIR = Path("runs/inverse-proposer")


def _project_root() -> Path:
    """Repository root (src/dexfrag/proposer_gui.py -> parents[2])."""
    return Path(__file__).resolve().parents[2]


def _resolve(text: str) -> Path:
    """Resolve a path relative to the working directory, else the project root.

    The window is often launched from an unrelated folder, so a relative
    default like ``datasets/main.parquet`` must still find the corpus.
    """
    path = Path(text).expanduser()
    if path.is_absolute() or path.exists():
        return path
    root = _project_root()
    if (root / "src" / "dexfrag").is_dir():
        return root / path
    return path


def _number(text: str, name: str, *, minimum: int = 1, allow_empty: bool = False) -> int | None:
    cleaned = text.strip()
    if not cleaned and allow_empty:
        return None
    try:
        value = int(cleaned)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number, got {cleaned!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.4f}" if value == value and abs(value) != float("inf") else "—"
    return str(value) if value is not None else "—"


def launch(corpus: Path = DEFAULT_CORPUS, *, checkpoint_dir: Path = DEFAULT_CHECKPOINT_DIR,
           forward_checkpoint: Path = DEFAULT_FORWARD_CHECKPOINT,
           report: Path = DEFAULT_REPORT, epochs: int = 10,
           max_rows: int = 2048, batch_size: int = 8, seed: int = 0,
           device: str = "auto") -> None:
    root = tk.Tk()
    root.title("DexFraggler — Phase 4 inverse proposer")
    root.minsize(680, 380)

    stop_event = threading.Event()
    started_at = {"value": None}
    state = {"running": False, "train_batches": 0, "start_epoch": 0, "total_units": 1,
             "pending": False, "latest": None}

    progress = tk.DoubleVar(value=0.0)
    status = tk.StringVar(value="Ready. Training only reads the train and validation splits.")
    counts = tk.StringVar(value="No run yet.")
    corpus_var = tk.StringVar(value=str(corpus))
    checkpoints_var = tk.StringVar(value=str(checkpoint_dir))
    epochs_var = tk.StringVar(value=str(epochs))
    rows_var = tk.StringVar(value=str(max_rows))
    batch_var = tk.StringVar(value=str(batch_size))

    ttk.Label(root, text="Phase 4 · Inverse proposer training",
              font=("TkDefaultFont", 13, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
    ttk.Label(root, textvariable=status, wraplength=620).pack(anchor="w", padx=16, pady=(0, 6))

    form = ttk.Frame(root)
    form.pack(fill="x", padx=16, pady=2)
    form.columnconfigure(1, weight=1)

    ttk.Label(form, text="Corpus").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
    ttk.Entry(form, textvariable=corpus_var).grid(row=0, column=1, sticky="ew", pady=2)
    ttk.Button(form, text="Browse…", width=9,
               command=lambda: _choose(corpus_var, "Corpus", [("Parquet", "*.parquet")])).grid(row=0, column=2, padx=(6, 0))

    ttk.Label(form, text="Checkpoints").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
    ttk.Entry(form, textvariable=checkpoints_var).grid(row=1, column=1, sticky="ew", pady=2)
    ttk.Button(form, text="Browse…", width=9,
               command=lambda: _choose_dir(checkpoints_var, "Checkpoint folder")).grid(row=1, column=2, padx=(6, 0))

    options = ttk.Frame(form)
    options.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 2))
    for index, (label, variable) in enumerate(
        (("Epochs", epochs_var), ("Max rows", rows_var), ("Batch size", batch_var))
    ):
        cell = ttk.Frame(options)
        cell.pack(side="left", padx=(0, 16))
        ttk.Label(cell, text=label).pack(anchor="w")
        ttk.Entry(cell, textvariable=variable, width=12).pack(anchor="w")

    bar = ttk.Progressbar(root, maximum=1000.0, variable=progress, length=620)
    bar.pack(fill="x", padx=16, pady=(14, 6))

    summary = tk.Label(root, textvariable=counts, justify="left", anchor="w",
                       font=("Consolas", 10), bg="#f2f2f2", relief="sunken",
                       padx=10, pady=8)
    summary.pack(fill="x", padx=16, pady=4)

    controls = ttk.Frame(root)
    controls.pack(pady=12)
    start = ttk.Button(controls, text="Start training")
    start.pack(side="left", padx=4)
    stop = ttk.Button(controls, text="Stop", state="disabled")
    stop.pack(side="left", padx=4)
    evaluate = ttk.Button(controls, text="Run evaluation")
    evaluate.pack(side="left", padx=4)

    def paint() -> None:
        state["pending"] = False
        event = state["latest"]
        if event is None:
            return
        state["latest"] = None
        kind = event.get("event")
        if kind == "ready":
            state["train_batches"] = max(1, int(event["train_batches"]))
            state["start_epoch"] = int(event["start_epoch"])
            state["total_units"] = max(
                1, (int(event["epochs"]) - state["start_epoch"]) * state["train_batches"]
            )
            bar.configure(mode="determinate")
            progress.set(0.0)
            counts.set(
                f"Epoch {event['start_epoch']}/{event['epochs']}   Step {event['global_step']}\n"
                f"Train batches {event['train_batches']}   Validation batches {event['val_batches']}   "
                f"Train samples {event['train_samples']}   Validation samples {event['val_samples']}"
            )
        elif kind == "step":
            train_batches = state["train_batches"] or max(1, int(event["batches"]))
            unit = ((int(event["epoch"]) - 1 - state["start_epoch"]) * train_batches
                    + int(event["batch"]) - 1)
            fraction = max(0.0, min(1.0, unit / max(1, state["total_units"])))
            progress.set(fraction * 1000.0)
            elapsed = 0.0 if started_at["value"] is None else time.monotonic() - started_at["value"]
            counts.set(
                f"Epoch {event['epoch']}/{event['epochs']}   Batch {event['batch']}/{event['batches']}   "
                f"Step {event['global_step']}\n"
                f"Samples {event['samples_seen']}/{event['train_samples']}   "
                f"Loss {float(event['loss']):.4f}   Best val {_fmt(event['best_val'])}   "
                f"Elapsed {int(elapsed)}s"
            )
        elif kind == "validation":
            status.set(f"Epoch {event['epoch']}/{event['epochs']} complete — validating…")
        elif kind == "epoch_end":
            train_batches = state["train_batches"] or 1
            unit = ((int(event["epoch"]) - state["start_epoch"]) * train_batches)
            progress.set(max(0.0, min(1.0, unit / state["total_units"])) * 1000.0)
            marker = "new best" if event["improved"] else "no improvement"
            counts.set(
                f"Epoch {event['epoch']}/{event['epochs']}   Step {event['global_step']}   ({marker})\n"
                f"Train loss {float(event['train_loss']):.4f}   "
                f"Val loss {float(event['val_loss']):.4f}   Best val {_fmt(event['best_val'])}"
            )
            status.set(f"Epoch {event['epoch']}/{event['epochs']} finished — {marker}.")
        elif kind == "finished":
            result = event["result"]
            progress.set(1000.0)
            stop.config(state="disabled")
            state["running"] = False
            start.config(state="normal")
            evaluate.config(state="normal")
            verdict = "Stopped early" if result.get("stopped") else (
                "Stopped on patience" if result.get("early_stopped") else "Finished"
            )
            status.set(f"{verdict}: {result.get('epochs_run', 0)} epochs, {result.get('global_step', 0)} steps.")
            counts.set(
                f"{verdict}   Epochs run {result.get('epochs_run', 0)}   Steps {result.get('global_step', 0)}\n"
                f"Best val {_fmt(result.get('best_val'))}   Parameters {result.get('parameter_count')}\n"
                f"Best checkpoint {result.get('best_checkpoint')}"
            )

    def on_event(event: dict) -> None:
        state["latest"] = event
        if state["pending"]:
            return
        state["pending"] = True
        root.after(80, paint)

    def run_training() -> None:
        from .proposer_training import ProposerTrainConfig, train

        try:
            corpus_path = _resolve(corpus_var.get())
            checkpoint_path = _resolve(checkpoints_var.get())
            config = ProposerTrainConfig(
                corpus=corpus_path,
                checkpoint_dir=checkpoint_path,
                epochs=_number(epochs_var.get(), "Epochs") or 1,
                max_rows=_number(rows_var.get(), "Max rows", minimum=2, allow_empty=True),
                batch_size=_number(batch_var.get(), "Batch size") or 1,
                device=device,
                seed=seed,
                tensorboard_dir=_resolve(str(DEFAULT_TENSORBOARD_DIR)),
            )
            status.set(f"Loading {corpus_path}…")
            started_at["value"] = time.monotonic()
            result = train(
                config,
                progress_callback=on_event,
                stop_requested=stop_event.is_set,
            )
            root.after(0, lambda: on_event({"event": "finished", "result": result}))
        except Exception as exc:  # keep the window useful on failure
            root.after(0, lambda: _fail("Training failed", exc))
        finally:
            root.after(0, lambda: (
                stop.config(state="disabled"),
                evaluate.config(state="normal"),
                state.update(running=False),
                stop_event.clear(),
            ))

    def begin_training() -> None:
        if state["running"]:
            return
        stop_event.clear()
        state["running"] = True
        started_at["value"] = time.monotonic()
        start.config(state="disabled")
        stop.config(state="normal")
        evaluate.config(state="disabled")
        status.set("Starting training…")
        progress.set(0.0)
        threading.Thread(target=run_training, daemon=True).start()

    def run_evaluation() -> None:
        from .proposer_eval import evaluate_proposer, write_evaluation_report

        try:
            corpus_path = _resolve(corpus_var.get())
            checkpoint_path = _resolve(checkpoints_var.get()) / "best.pt"
            if not checkpoint_path.exists():
                raise FileNotFoundError(f"no trained checkpoint at {checkpoint_path}")
            resolved_forward = _resolve(str(forward_checkpoint))
            forward_path = resolved_forward if resolved_forward.exists() else None
            summary = evaluate_proposer(
                corpus_path, checkpoint_path,
                forward_checkpoint=forward_path,
                device="cpu",
                max_targets=8,
                candidate_count=16,
                native_budget=4,
                max_total_renders=16,
                seed=seed,
            )
            written = write_evaluation_report(summary, _resolve(str(report)))
            root.after(0, lambda: _show_evaluation(summary, written))
        except Exception as exc:
            root.after(0, lambda: _fail("Evaluation failed", exc))
        finally:
            root.after(0, lambda: (
                bar.stop(),
                bar.configure(mode="determinate"),
                evaluate.config(state="normal"),
                state.update(running=False),
            ))

    def begin_evaluation() -> None:
        if state["running"]:
            return
        state["running"] = True
        start.config(state="disabled")
        evaluate.config(state="disabled")
        status.set("Evaluating against held-out targets…")
        counts.set("Evaluating… (no per-step counts; native renders are bounded)")
        bar.configure(mode="indeterminate")
        bar.start(14)
        threading.Thread(target=run_evaluation, daemon=True).start()

    def _show_evaluation(summary: dict, written: Path) -> None:
        proposer = summary.get("methods", {}).get("proposer", {})
        candidate = proposer.get("candidate", {})
        native = proposer.get("native", {})
        similarity = native.get("mean_best_similarity")
        status.set("Evaluation finished.")
        scored = native.get("targets_scored", 0)
        available = native.get("target_count", 0)
        counts.set(
            f"Legal {int(candidate.get('legal_count', 0))}/{summary.get('candidate_count', 0)}   "
            f"Unique {int(candidate.get('unique_count', 0))}   "
            f"Algorithm spread {candidate.get('algorithm_diversity')}\n"
            f"Native renders {summary.get('actual_native_renders')}   "
            f"Targets scored {scored}/{available}   "
            f"Errors {native.get('render_errors')}   "
            f"Best similarity {_fmt(similarity)}\n"
            f"Report {written}"
        )

    def _fail(title: str, error: Exception) -> None:
        stop_event.clear()
        state["running"] = False
        start.config(state="normal")
        evaluate.config(state="normal")
        stop.config(state="disabled")
        bar.stop()
        bar.configure(mode="determinate")
        status.set(f"{title}: {error}")
        messagebox.showerror(title, str(error))

    def on_close() -> None:
        if state["running"] and not messagebox.askyesno(
            "Training is running", "Stop the run and close? Last progress is checkpointed."
        ):
            return
        stop_event.set()
        root.after(400, root.destroy)

    start.config(command=begin_training)
    stop.config(command=stop_event.set)
    evaluate.config(command=begin_evaluation)
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def _choose(variable: tk.StringVar, title: str, filetypes: list[tuple[str, str]]) -> None:
    chosen = filedialog.askopenfilename(title=title, filetypes=filetypes)
    if chosen:
        variable.set(chosen)


def _choose_dir(variable: tk.StringVar, title: str) -> None:
    chosen = filedialog.askdirectory(title=title)
    if chosen:
        variable.set(chosen)
