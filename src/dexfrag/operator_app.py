"""Unified operator console: every roadmap step in one guided window.

The operator does not need to understand PyTorch or the CLI. Each tab
explains in plain language what the step does, what good looks like, runs
the exact same bounded engine calls as the CLI commands, and reports a
gate verdict. Long work runs in background threads; nothing here runs
unbounded (every training/collection/evaluation call carries an explicit
cap). TensorBoard opens from inside the app via the TensorBoard tab.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .proposer_gui import _fmt, _number, _resolve

APP_TITLE = "DexFraggler — Operator console"
TENSORBOARD_PORT = 6006
TENSORBOARD_LOGDIR = "runs"

DEFAULT_CORPUS = "datasets/main.parquet"
DEFAULT_RANKER_DIR = "checkpoints/ranker-v2"
DEFAULT_RANKER_CHECKPOINT = "checkpoints/ranker-v2/best.pt"
DEFAULT_FORWARD_DIR = "checkpoints/forward-v2"
DEFAULT_FORWARD_CHECKPOINT = "checkpoints/forward-v2/best.pt"
LEGACY_FORWARD_CHECKPOINT = "checkpoints/forward-operator/best.pt"
DEFAULT_PROPOSER_DIR = "checkpoints/inverse-proposer"
DEFAULT_PROPOSER_REPORT = "reports/phase4-console.json"
DEFAULT_TARGET_FOLDER = "datasets/target-wavetables"
DEFAULT_TARGET_RECORDS = "datasets/target-records.parquet"


# ---------------------------------------------------------------------------
# Step registry: drives the Start-here journey and is pinned by tests.
# ---------------------------------------------------------------------------
STEPS = (
    {
        "id": "doctor",
        "tab": "1 · Health check",
        "title": "Step 1 — Is my setup working?",
        "what": "Runs the same checks as `dexfrag doctor`: Python packages, "
                "the native DX7 renderer (one real render), and feature extraction.",
        "good": "Every check says OK. If anything fails, stop here — later "
                "steps cannot be trusted until this is green.",
    },
    {
        "id": "dataset",
        "tab": "2 · Dataset",
        "title": "Step 2 — What data do I have?",
        "what": "Reads your observation file and reports how many patches were "
                "rendered, how many are clean periodic voices (valid), and how "
                "they split across train / validation / test.",
        "good": "Thousands of rows, all 32 algorithms present, and a few "
                "thousand `valid` rows to train on. The rest (unstable, quiet) "
                "is real DX7 behavior kept for later — not a problem.",
    },
    {
        "id": "collect",
        "tab": "3 · Collect",
        "title": "Step 3 — Record more DX7 sounds (optional)",
        "what": "Renders new random patches through the real DX7 engine and "
                "adds them to your dataset. Skips duplicates automatically and "
                "never exceeds the render cap you set. You can close the app "
                "mid-run; already-recorded patches are kept.",
        "good": "Observation count rises, duplicates are skipped without "
                "re-rendering, every algorithm keeps receiving rows.",
    },
    {
        "id": "train_forward",
        "tab": "4 · Train ear",
        "title": "Step 4 — Teach the ear (compatibility ranker)",
        "what": "Trains the model that learns which patches sound alike, by "
                "comparing real rendered examples. It never draws waveforms — "
                "it learns an ear for ranking candidates, which is exactly "
                "what search needs. Saves into a NEW folder so your last good "
                "model is never overwritten; keeps only improving checkpoints.",
        "good": "The pairwise score (how often it orders two candidates the "
                "same way the real renderer does) climbs and then levels off. "
                "A flat line means stop and ask — do not just run longer.",
    },
    {
        "id": "check_forward",
        "tab": "5 · Test ear",
        "title": "Step 5 — Is the ear useful?",
        "what": "Tests the trained ear on held-out patches it never trained "
                "on: can it rank candidate patches in an order matching the "
                "real renderer?",
        "good": "Ranking accuracy clearly above 0.60 and top-1 regret clearly "
                "below the random baseline. Near 0.50 means the ear is "
                "guessing — stay here, do not move on.",
    },
    {
        "id": "train_proposer",
        "tab": "6 · Train guesser",
        "title": "Step 6 — Teach the guesser (inverse proposer)",
        "what": "Trains the model that hears a sound and suggests many legal "
                "patches that might make it. Judged on variety and quality of "
                "its suggestions, never on recovering one exact patch.",
        "good": "100% of suggestions legal, nearly all unique, spread across "
                "many algorithms. You can Stop any time — progress is "
                "checkpointed and resumes where it left off.",
    },
    {
        "id": "check_proposer",
        "tab": "7 · Test guesser",
        "title": "Step 7 — Does the guesser beat dumb luck?",
        "what": "Hides patches, asks the guesser for candidates, ranks them "
                "with the ear, and spot-checks the best ones through the REAL "
                "renderer (bounded: at most 256 renders). Compares against "
                "random guessing and against remembering old recordings.",
        "good": "Beats random/structured guessing. Losing to pure memory "
                "(nearest recording) on old sounds is expected — the real "
                "test is new sounds it never heard (step 8).",
    },
    {
        "id": "targets",
        "tab": "8 · New sounds",
        "title": "Step 8 — Challenge it with new sounds",
        "what": "Makes fresh mystery wavetables and imports them as "
                "black-box targets: the system only ever sees the 2048 "
                "samples, never how they were made.",
        "good": "Target records import with waveform-only features. These "
                "become the honest exam for guesser + search.",
    },
    {
        "id": "tensorboard",
        "tab": "9 · Charts",
        "title": "Step 9 — Watch the charts",
        "what": "Opens TensorBoard (the training charts website) in your "
                "browser with one click. The app starts it for you if needed.",
        "good": "Loss curves slope downward; validation tracks training. "
                "Flat or climbing validation while training improves means "
                "overfitting — stop the run.",
    },
    {
        "id": "next",
        "tab": "10 · What's next",
        "title": "Step 10 — Where am I in the journey?",
        "what": "Shows the phases not built yet (guided search, active "
                "learning, full wavetable benchmark) and what evidence "
                "unlocks each one.",
        "good": "You only move on when the current phase's gate verdict "
                "above says so — never because a step merely finished.",
    },
)


# ---------------------------------------------------------------------------
# Gate verdicts: pure functions, pinned by tests.
# ---------------------------------------------------------------------------
def forward_gate_verdict(pairwise_accuracy: float | None, top1_regret: float | None,
                         random_expected_regret: float | None) -> tuple[bool, str]:
    """Decide whether the forward model ranks usefully better than chance."""
    if pairwise_accuracy is None or top1_regret is None or random_expected_regret is None:
        return False, "No ranking numbers came back — the evaluation did not score."
    if not (pairwise_accuracy > 0.60):
        return False, (
            f"Ranking accuracy {pairwise_accuracy:.3f} is at or below 0.60 — the ear is "
            "guessing. Stay in step 4/5: do not just run longer, the encoding, loss, "
            "or data coverage needs a look."
        )
    if not (top1_regret < random_expected_regret):
        return False, (
            f"Top-1 regret {top1_regret:.5f} is not below random "
            f"({random_expected_regret:.5f}) — ranking is not useful yet."
        )
    return True, (
        f"Ranking accuracy {pairwise_accuracy:.3f} with top-1 regret {top1_regret:.5f} "
        f"vs random {random_expected_regret:.5f} — the ear beats chance. Step 6 unlocked."
    )


def proposer_gate_verdict(legal_rate: float | None, unique_rate: float | None,
                          proposer_similarity: float | None,
                          generative_best: float | None) -> tuple[bool, str]:
    """Decide whether the proposer puts strong solutions in the pool efficiently."""
    if None in (legal_rate, unique_rate, proposer_similarity, generative_best):
        return False, "Incomplete evaluation numbers — rerun step 7 with the full budget."
    if legal_rate < 1.0 or unique_rate < 0.9:
        return False, (
            f"Legal {legal_rate:.2f} / unique {unique_rate:.2f} — candidates are "
            "collapsing or invalid. More training or a wider candidate count first."
        )
    if proposer_similarity <= generative_best:
        return False, (
            f"Guesser quality {proposer_similarity:.3f} does not beat dumb guessing "
            f"({generative_best:.3f}). Stay in step 6."
        )
    return True, (
        f"Guesser {proposer_similarity:.3f} beats dumb guessing {generative_best:.3f} "
        "with fully legal, diverse candidates — useful starting basins for search. "
        "(Losing to pure memory on old recordings is expected; new sounds are the exam.)"
    )


# ---------------------------------------------------------------------------
# TensorBoard plumbing (side effects isolated for tests via injection).
# ---------------------------------------------------------------------------
_tb_process: subprocess.Popen | None = None


def tensorboard_url(port: int = TENSORBOARD_PORT) -> str:
    return f"http://localhost:{port}"


def find_tensorboard_command() -> list[str] | None:
    """Locate a TensorBoard launcher without starting anything."""
    found = shutil.which("tensorboard")
    if found:
        return [found]
    try:
        import tensorboard  # noqa: F401
    except ImportError:
        return None
    return [sys.executable, "-m", "tensorboard.main"]


def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_tensorboard(logdir: str = TENSORBOARD_LOGDIR, port: int = TENSORBOARD_PORT,
                       launcher=subprocess.Popen, opener=webbrowser.open,
                       probe=is_port_open) -> str:
    """Open TensorBoard in the browser, starting it first if needed."""
    global _tb_process
    command = find_tensorboard_command()
    if command is None:
        return "TensorBoard is not installed in this Python environment."
    if probe(port):
        opener(tensorboard_url(port))
        return f"TensorBoard was already running — opened {tensorboard_url(port)}."
    if _tb_process is not None and _tb_process.poll() is None:
        opener(tensorboard_url(port))
        return f"Reopened {tensorboard_url(port)} (started earlier by this app)."
    try:
        _tb_process = launcher(
            [*command, "--logdir", logdir, "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return f"Could not start TensorBoard: {exc}"
    for _ in range(40):
        if probe(port):
            break
        time.sleep(0.25)
    opener(tensorboard_url(port))
    return f"Started TensorBoard on {logdir} — opened {tensorboard_url(port)}."


def close_tensorboard() -> None:
    """Stop the TensorBoard started by this app, if it is still running."""
    global _tb_process
    process, _tb_process = _tb_process, None
    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Read-only snapshots (no training, no writes).
# ---------------------------------------------------------------------------
def dataset_snapshot(dataset: str | Path) -> dict:
    """Compact operator-facing summary of one observation file."""
    from collections import Counter

    from .budget import Budget
    from .storage import read_observations

    path = _resolve(str(dataset))
    if not path.exists():
        return {"exists": False, "path": str(path)}
    table = read_observations(path)
    rows = table.num_rows
    validity = Counter(table.column("validity_class").to_pylist()) if rows else Counter()
    splits = Counter(table.column("split").to_pylist()) if rows else Counter()
    algos = set(table.column("algorithm").to_pylist()) if rows else set()
    try:
        lifetime_valid = Budget.load(path).renders_valid
    except (OSError, ValueError):
        lifetime_valid = 0
    return {
        "exists": True,
        "path": str(path),
        "observations": rows,
        "valid_rows": validity.get("valid", 0),
        "by_validity": dict(sorted(validity.items())),
        "by_split": dict(sorted(splits.items())),
        "algorithms_covered": len(algos),
        "renders_valid_lifetime": lifetime_valid,
    }


def where_am_i(corpus: str = DEFAULT_CORPUS) -> list[str]:
    """Plain-language journey status derived from artifacts on disk."""
    lines = []
    snap = dataset_snapshot(corpus)
    if not snap.get("exists"):
        return ["No dataset yet — go to tab 3 (Collect) and record your first "
                "bounded batch, or point tab 2 at an existing file."]
    lines.append(
        f"Dataset: {snap['observations']} observations, {snap['valid_rows']} clean "
        f"voices, {snap['algorithms_covered']}/32 algorithms "
        f"(file: {snap['path']})."
    )
    for label, path in (
        ("Ear (ranker)", _resolve(DEFAULT_RANKER_CHECKPOINT)),
        ("Ear (forward v3, wide)", _resolve(DEFAULT_FORWARD_CHECKPOINT)),
        ("Ear (forward v1, old)", _resolve(LEGACY_FORWARD_CHECKPOINT)),
        ("Guesser (proposer)", _resolve(DEFAULT_PROPOSER_DIR) / "best.pt"),
    ):
        lines.append(f"{label}: {'trained ✓' if path.exists() else 'not trained yet —'} "
                     f"({path})")
    return lines


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
def _output_box(parent: tk.Widget) -> tuple[tk.Text, callable]:
    box = tk.Text(parent, height=12, wrap="word", font=("Consolas", 9),
                  bg="#f5f5f5", relief="sunken", padx=8, pady=6)
    box.configure(state="disabled")

    def show(lines: list[str]) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("end", "\n".join(lines))
        box.configure(state="disabled")

    return box, show


def _entry_row(parent: tk.Widget, label: str, variable: tk.StringVar,
               row: int, *, browse: callable | None = None, width: int = 52) -> None:
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
    ttk.Entry(parent, textvariable=variable, width=width).grid(row=row, column=1, sticky="ew", pady=2)
    if browse is not None:
        ttk.Button(parent, text="Browse…", width=9, command=browse).grid(row=row, column=2, padx=(6, 0))


def launch(corpus: Path | str = DEFAULT_CORPUS) -> None:
    root = tk.Tk()
    root.title(APP_TITLE)
    root.minsize(760, 560)
    busy = {"value": False}
    stop_event = threading.Event()

    header_status = tk.StringVar(value="Pick a tab on the left. Each tab explains itself — start at tab 1.")
    ttk.Label(root, text="DexFraggler operator console",
              font=("TkDefaultFont", 14, "bold")).pack(anchor="w", padx=14, pady=(12, 0))
    ttk.Label(root, textvariable=header_status, wraplength=700).pack(anchor="w", padx=14, pady=(0, 6))

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=12, pady=6)

    def set_busy(running: bool, message: str) -> None:
        busy["value"] = running
        header_status.set(message)

    def run_async(worker: callable, done: callable | None = None) -> None:
        def wrapper() -> None:
            try:
                result = worker()
            except Exception as exc:  # keep the console useful on failure
                root.after(0, lambda: _failed(exc))
                return
            if done is not None:
                root.after(0, lambda: done(result))

        def _failed(exc: Exception) -> None:
            set_busy(False, f"Failed: {exc}")
            messagebox.showerror("Step failed", str(exc))

        threading.Thread(target=wrapper, daemon=True).start()

    def guard(action: callable) -> callable:
        def inner() -> None:
            if busy["value"]:
                messagebox.showinfo("Busy", "Another step is still running — wait for it to finish.")
                return
            stop_event.clear()
            action()
        return inner

    # -- Start tab ----------------------------------------------------------
    start_frame = ttk.Frame(notebook, padding=14)
    notebook.add(start_frame, text="Start here")
    ttk.Label(start_frame, text="Your journey (do these in order)",
              font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(0, 6))
    journey = tk.Text(start_frame, height=16, wrap="word", font=("Consolas", 10),
                      bg="#f5f5f5", relief="flat", padx=6, pady=6)
    journey.pack(fill="both", expand=True)

    def refresh_journey() -> None:
        journey.configure(state="normal")
        journey.delete("1.0", "end")
        journey.insert("end", "\n".join(f"• {line}" for line in where_am_i(str(corpus_var.get()))))
        journey.insert("end", "\n\n" + "\n".join(
            f"{index + 1}. {step['tab']} — {step['what']}" for index, step in enumerate(STEPS)))
        journey.configure(state="disabled")

    corpus_var = tk.StringVar(value=str(corpus))
    top_row = ttk.Frame(start_frame)
    top_row.pack(fill="x", pady=(0, 6))
    ttk.Label(top_row, text="Dataset").pack(side="left", padx=(0, 8))
    ttk.Entry(top_row, textvariable=corpus_var, width=48).pack(side="left")
    ttk.Button(top_row, text="Refresh", command=guard(lambda: (
        set_busy(True, "Reading dataset…"),
        run_async(lambda: where_am_i(str(corpus_var.get())),
                  lambda lines: (journey.configure(state="normal"),
                                 journey.delete("1.0", "end"),
                                 journey.insert("end", "\n".join(f"• {l}" for l in lines)),
                                 journey.configure(state="disabled"),
                                 set_busy(False, "Pick a tab on the left."))),
    ))).pack(side="left", padx=6)
    refresh_journey()

    # -- Doctor tab ---------------------------------------------------------
    doctor_frame = ttk.Frame(notebook, padding=14)
    notebook.add(doctor_frame, text=STEPS[0]["tab"])
    _step_intro(doctor_frame, STEPS[0])
    doctor_out, doctor_show = _output_box(doctor_frame)
    doctor_out.pack(fill="both", expand=True, pady=6)

    @guard
    def run_doctor() -> None:
        from .cli import doctor_report

        set_busy(True, "Checking setup (renders one patch through the real DX7)…")
        run_async(doctor_report,
                  lambda report: doctor_show(_render_doctor(report)) or set_busy(False, _ok_line(report)))

    ttk.Button(doctor_frame, text="Run health check", command=run_doctor).pack(pady=6)

    # -- Dataset tab --------------------------------------------------------
    data_frame = ttk.Frame(notebook, padding=14)
    notebook.add(data_frame, text=STEPS[1]["tab"])
    _step_intro(data_frame, STEPS[1])
    data_form = ttk.Frame(data_frame)
    data_form.pack(fill="x", pady=4)
    data_form.columnconfigure(1, weight=1)
    data_corpus = tk.StringVar(value=str(corpus))
    _entry_row(data_form, "Dataset", data_corpus, 0,
               browse=lambda: _choose_file(data_corpus, "Dataset", [("Parquet", "*.parquet")]))
    data_out, data_show = _output_box(data_frame)
    data_out.pack(fill="both", expand=True, pady=6)

    @guard
    def run_snapshot() -> None:
        set_busy(True, "Reading dataset…")
        run_async(lambda: dataset_snapshot(data_corpus.get()),
                  lambda snap: data_show(_render_snapshot(snap)) or set_busy(False, "Pick a tab on the left."))

    ttk.Button(data_frame, text="Show dataset summary", command=run_snapshot).pack(pady=6)

    # -- Collect tab --------------------------------------------------------
    collect_frame = ttk.Frame(notebook, padding=14)
    notebook.add(collect_frame, text=STEPS[2]["tab"])
    _step_intro(collect_frame, STEPS[2])
    collect_form = ttk.Frame(collect_frame)
    collect_form.pack(fill="x", pady=4)
    collect_form.columnconfigure(1, weight=1)
    collect_vars = {
        "dataset": tk.StringVar(value=str(corpus)),
        "seed": tk.StringVar(value="42"),
        "max_renders": tk.StringVar(value="1000"),
    }
    _entry_row(collect_form, "Dataset", collect_vars["dataset"], 0,
               browse=lambda: _choose_file(collect_vars["dataset"], "Dataset", [("Parquet", "*.parquet")]))
    plan_row = ttk.Frame(collect_form)
    plan_row.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 2))
    collect_vars.update(_plan_fields(plan_row))
    small_row = ttk.Frame(collect_form)
    small_row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 2))
    for key, label in (("seed", "Seed"), ("max_renders", "Max renders (required cap)")):
        cell = ttk.Frame(small_row)
        cell.pack(side="left", padx=(0, 16))
        ttk.Label(cell, text=label).pack(anchor="w")
        ttk.Entry(cell, textvariable=collect_vars[key], width=16).pack(anchor="w")
    collect_bar = ttk.Progressbar(collect_frame, maximum=1000.0, length=680)
    collect_bar.pack(fill="x", pady=(10, 4))
    collect_out, collect_show = _output_box(collect_frame)
    collect_out.pack(fill="both", expand=True, pady=6)

    @guard
    def run_collect() -> None:
        from .budget import BudgetCaps
        from .collector import collect
        from .gui import OPERATOR_PLAN

        plan = {name: _number(collect_vars[name].get(), name) or 0 for name in OPERATOR_PLAN}
        cap = _number(collect_vars["max_renders"].get(), "Max renders") or 0
        if cap < 1:
            raise ValueError("Max renders must be at least 1 — collection never runs unbounded.")
        dataset = _resolve(collect_vars["dataset"].get())
        seed = _number(collect_vars["seed"].get(), "Seed") or 0
        collect_bar.configure(mode="determinate")
        collect_bar["value"] = 0

        def on_progress(summary) -> None:
            done = summary.rendered + summary.render_failures + summary.duplicates_skipped
            root.after(0, lambda: collect_bar.configure(
                value=max(0.0, min(1000.0, 1000.0 * done / cap))))

        def worker():
            return collect(dataset, plan=plan, seed=seed,
                           caps=BudgetCaps(max_renders_attempted=cap),
                           progress_callback=on_progress).to_dict()

        set_busy(True, f"Collecting up to {cap} renders into {dataset}…")
        run_async(worker, lambda s: (
            collect_bar.configure(value=1000.0),
            collect_show(_render_collect(s)),
            set_busy(False, "Collection finished. See tab 2 for the new totals."),
        ))

    ttk.Button(collect_frame, text="Start bounded collection", command=run_collect).pack(pady=6)

    # -- Train-forward tab --------------------------------------------------
    tf_frame = ttk.Frame(notebook, padding=14)
    notebook.add(tf_frame, text=STEPS[3]["tab"])
    _step_intro(tf_frame, STEPS[3])
    tf_form = ttk.Frame(tf_frame)
    tf_form.pack(fill="x", pady=4)
    tf_form.columnconfigure(1, weight=1)
    tf_vars = {
        "corpus": tk.StringVar(value=str(corpus)),
        "checkpoint_dir": tk.StringVar(value=DEFAULT_RANKER_DIR),
        "epochs": tk.StringVar(value="20"),
        "max_rows": tk.StringVar(value="2048"),
        "batch_size": tk.StringVar(value="32"),
        "patience": tk.StringVar(value="6"),
    }
    _entry_row(tf_form, "Corpus", tf_vars["corpus"], 0,
               browse=lambda: _choose_file(tf_vars["corpus"], "Corpus", [("Parquet", "*.parquet")]))
    _entry_row(tf_form, "Checkpoint folder (new!)", tf_vars["checkpoint_dir"], 1,
               browse=lambda: _choose_dir(tf_vars["checkpoint_dir"], "Checkpoint folder"))
    _mini_row(tf_form, 2, (("Epochs", tf_vars["epochs"]), ("Max rows", tf_vars["max_rows"]),
                           ("Batch size", tf_vars["batch_size"]), ("Patience", tf_vars["patience"])))
    tf_bar = ttk.Progressbar(tf_frame, mode="indeterminate", length=680)
    tf_bar.pack(fill="x", pady=(10, 4))
    tf_out, tf_show = _output_box(tf_frame)
    tf_out.pack(fill="both", expand=True, pady=6)

    @guard
    def run_train_forward() -> None:
        from .ranker import RankerTrainConfig, train

        config = RankerTrainConfig(
            corpus=_resolve(tf_vars["corpus"].get()),
            checkpoint_dir=_resolve(tf_vars["checkpoint_dir"].get()),
            epochs=_number(tf_vars["epochs"].get(), "Epochs") or 1,
            max_rows=_number(tf_vars["max_rows"].get(), "Max rows", minimum=2, allow_empty=True),
            batch_size=_number(tf_vars["batch_size"].get(), "Batch size") or 1,
            patience=_number(tf_vars["patience"].get(), "Patience", allow_empty=True),
            device="auto", seed=0,
            tensorboard_dir=_resolve("runs/ranker"),
        )
        tf_bar.start(14)
        set_busy(True, "Training the ear — watch the charts tab for live curves…")

        def done(summary: dict) -> None:
            tf_bar.stop()
            tf_show(_render_train(summary, "ear"))
            set_busy(False, "Training finished. Now open tab 5 (Test ear).")

        run_async(lambda: train(config), done)

    ttk.Button(tf_frame, text="Train the ear (bounded)", command=run_train_forward).pack(pady=6)

    # -- Check-forward tab --------------------------------------------------
    cf_frame = ttk.Frame(notebook, padding=14)
    notebook.add(cf_frame, text=STEPS[4]["tab"])
    _step_intro(cf_frame, STEPS[4])
    cf_form = ttk.Frame(cf_frame)
    cf_form.pack(fill="x", pady=4)
    cf_form.columnconfigure(1, weight=1)
    cf_vars = {
        "corpus": tk.StringVar(value=str(corpus)),
        "checkpoint": tk.StringVar(value=str(_resolve(DEFAULT_RANKER_CHECKPOINT))
                                  if _resolve(DEFAULT_RANKER_CHECKPOINT).exists()
                                  else _default_forward_checkpoint()),
        "max_targets": tk.StringVar(value="32"),
        "max_candidates": tk.StringVar(value="500"),
    }
    _entry_row(cf_form, "Corpus", cf_vars["corpus"], 0,
               browse=lambda: _choose_file(cf_vars["corpus"], "Corpus", [("Parquet", "*.parquet")]))
    _entry_row(cf_form, "Checkpoint", cf_vars["checkpoint"], 1,
               browse=lambda: _choose_file(cf_vars["checkpoint"], "Checkpoint", [("Checkpoint", "*.pt")]))
    _mini_row(cf_form, 2, (("Targets", cf_vars["max_targets"]), ("Candidates", cf_vars["max_candidates"])))
    cf_bar = ttk.Progressbar(cf_frame, mode="indeterminate", length=680)
    cf_bar.pack(fill="x", pady=(10, 4))
    cf_out, cf_show = _output_box(cf_frame)
    cf_out.pack(fill="both", expand=True, pady=6)

    @guard
    def run_check_forward() -> None:
        from .forward_eval import evaluate_forward as run_eval_forward

        use_ranker = _resolve(DEFAULT_RANKER_CHECKPOINT).exists()
        if use_ranker:
            from .ranker import evaluate_ranker as run_eval_ranker

        args = {
            "corpus": _resolve(cf_vars["corpus"].get()),
            "device": "cpu",
            "max_targets": _number(cf_vars["max_targets"].get(), "Targets") or 1,
            "max_candidates": _number(cf_vars["max_candidates"].get(), "Candidates") or 1,
        }
        if use_ranker:
            args["checkpoint"] = _resolve(DEFAULT_RANKER_CHECKPOINT)
        else:
            args["checkpoint"] = _resolve(cf_vars["checkpoint"].get())
        cf_bar.start(14)
        set_busy(True, "Testing the ear on held-out patches…")

        def done(summary: dict) -> None:
            cf_bar.stop()
            ranking = summary.get("ranking", summary)
            ok, verdict = forward_gate_verdict(
                ranking.get("pairwise_accuracy"), ranking.get("top1_regret"),
                ranking.get("random_expected_regret"))
            cf_show(_render_forward_eval(summary) + ["", f"GATE: {verdict}"])
            set_busy(False, "Gate reached: go to tab 6." if ok else "Gate missed: stay on tabs 4–5.")

        run_async(
            lambda: run_eval_ranker(**args) if use_ranker else run_eval_forward(**args),
            done,
        )

    ttk.Button(cf_frame, text="Test the ear", command=run_check_forward).pack(pady=6)

    # -- Train-proposer tab -------------------------------------------------
    tp_frame = ttk.Frame(notebook, padding=14)
    notebook.add(tp_frame, text=STEPS[5]["tab"])
    _step_intro(tp_frame, STEPS[5])
    tp_form = ttk.Frame(tp_frame)
    tp_form.pack(fill="x", pady=4)
    tp_form.columnconfigure(1, weight=1)
    tp_vars = {
        "corpus": tk.StringVar(value=str(corpus)),
        "checkpoint_dir": tk.StringVar(value=DEFAULT_PROPOSER_DIR),
        "epochs": tk.StringVar(value="10"),
        "max_rows": tk.StringVar(value="2048"),
        "batch_size": tk.StringVar(value="8"),
    }
    _entry_row(tp_form, "Corpus", tp_vars["corpus"], 0,
               browse=lambda: _choose_file(tp_vars["corpus"], "Corpus", [("Parquet", "*.parquet")]))
    _entry_row(tp_form, "Checkpoint folder", tp_vars["checkpoint_dir"], 1,
               browse=lambda: _choose_dir(tp_vars["checkpoint_dir"], "Checkpoint folder"))
    _mini_row(tp_form, 2, (("Epochs", tp_vars["epochs"]), ("Max rows", tp_vars["max_rows"]),
                           ("Batch size", tp_vars["batch_size"])))
    tp_bar = ttk.Progressbar(tp_frame, maximum=1000.0, length=680)
    tp_bar.pack(fill="x", pady=(10, 4))
    tp_live = tk.StringVar(value="No run yet.")
    ttk.Label(tp_frame, textvariable=tp_live, wraplength=680).pack(anchor="w", pady=2)
    tp_out, tp_show = _output_box(tp_frame)
    tp_out.pack(fill="both", expand=True, pady=6)
    tp_controls = ttk.Frame(tp_frame)
    tp_controls.pack(pady=6)
    tp_start = ttk.Button(tp_controls, text="Train the guesser (bounded)")
    tp_start.pack(side="left", padx=4)
    tp_stop = ttk.Button(tp_controls, text="Stop", state="disabled")
    tp_stop.pack(side="left", padx=4)

    def tp_event(event: dict) -> None:
        kind = event.get("event")
        if kind == "step":
            root.after(0, lambda: (
                tp_live.set(f"Epoch {event['epoch']}/{event['epochs']} batch {event['batch']}/"
                            f"{event['batches']} loss {float(event['loss']):.4f} "
                            f"best val {_fmt(event['best_val'])}"),
                tp_bar.configure(value=min(1000.0, 1000.0 * int(event["global_step"]) / max(
                    1, int(event["epochs"]) * max(1, int(event["batches"]))))),
            ))
        elif kind == "epoch_end":
            root.after(0, lambda: tp_live.set(
                f"Epoch {event['epoch']}/{event['epochs']} done — "
                f"train {float(event['train_loss']):.4f} val {float(event['val_loss']):.4f} "
                f"({'new best' if event['improved'] else 'no improvement'})"))

    def tp_worker() -> dict:
        from .proposer_training import ProposerTrainConfig, train

        config = ProposerTrainConfig(
            corpus=_resolve(tp_vars["corpus"].get()),
            checkpoint_dir=_resolve(tp_vars["checkpoint_dir"].get()),
            epochs=_number(tp_vars["epochs"].get(), "Epochs") or 1,
            max_rows=_number(tp_vars["max_rows"].get(), "Max rows", minimum=2, allow_empty=True),
            batch_size=_number(tp_vars["batch_size"].get(), "Batch size") or 1,
            device="auto", seed=0,
            tensorboard_dir=_resolve("runs/inverse-proposer"),
        )
        return train(config, progress_callback=tp_event, stop_requested=stop_event.is_set)

    def tp_begin() -> None:
        if busy["value"]:
            messagebox.showinfo("Busy", "Another step is still running — wait for it to finish.")
            return
        stop_event.clear()
        set_busy(True, "Training the guesser — Stop any time, progress is checkpointed…")
        tp_start.config(state="disabled")
        tp_stop.config(state="normal")

        def done(summary: dict) -> None:
            tp_bar.configure(value=1000.0)
            tp_show(_render_train(summary, "guesser"))
            tp_start.config(state="normal")
            tp_stop.config(state="disabled")
            stop_event.clear()
            set_busy(False, "Training finished. Now open tab 7 (Test guesser).")

        run_async(tp_worker, done)

    tp_start.config(command=tp_begin)
    tp_stop.config(command=stop_event.set)

    # -- Check-proposer tab -------------------------------------------------
    cp_frame = ttk.Frame(notebook, padding=14)
    notebook.add(cp_frame, text=STEPS[6]["tab"])
    _step_intro(cp_frame, STEPS[6])
    ttk.Label(cp_frame, text="This does up to 256 real DX7 renders (bounded and resumable). Takes minutes.",
              wraplength=680).pack(anchor="w", pady=(0, 4))
    cp_form = ttk.Frame(cp_frame)
    cp_form.pack(fill="x", pady=4)
    cp_form.columnconfigure(1, weight=1)
    cp_vars = {
        "corpus": tk.StringVar(value=str(corpus)),
        "checkpoint": tk.StringVar(value=str(_resolve(DEFAULT_PROPOSER_DIR) / "best.pt")),
        "forward": tk.StringVar(value=_default_forward_checkpoint()),
        "report": tk.StringVar(value=DEFAULT_PROPOSER_REPORT),
    }
    _entry_row(cp_form, "Corpus", cp_vars["corpus"], 0,
               browse=lambda: _choose_file(cp_vars["corpus"], "Corpus", [("Parquet", "*.parquet")]))
    _entry_row(cp_form, "Guesser checkpoint", cp_vars["checkpoint"], 1,
               browse=lambda: _choose_file(cp_vars["checkpoint"], "Checkpoint", [("Checkpoint", "*.pt")]))
    _entry_row(cp_form, "Ear checkpoint", cp_vars["forward"], 2,
               browse=lambda: _choose_file(cp_vars["forward"], "Checkpoint", [("Checkpoint", "*.pt")]))
    _entry_row(cp_form, "Report output", cp_vars["report"], 3,
               browse=lambda: _choose_file(cp_vars["report"], "Report", [("JSON", "*.json")]))
    cp_bar = ttk.Progressbar(cp_frame, mode="indeterminate", length=680)
    cp_bar.pack(fill="x", pady=(10, 4))
    cp_out, cp_show = _output_box(cp_frame)
    cp_out.pack(fill="both", expand=True, pady=6)

    @guard
    def run_check_proposer() -> None:
        from .proposer_eval import evaluate_proposer, write_evaluation_report

        ckpt = _resolve(cp_vars["checkpoint"].get())
        if not ckpt.exists():
            raise FileNotFoundError(f"no trained guesser at {ckpt} — run tab 6 first")
        forward_path = _resolve(cp_vars["forward"].get())
        args = {
            "corpus": _resolve(cp_vars["corpus"].get()),
            "checkpoint": ckpt,
            "forward_checkpoint": forward_path if forward_path.exists() else None,
            "device": "cpu", "max_targets": 8, "candidate_count": 16,
            "native_budget": 8, "max_total_renders": 256, "seed": 0,
        }
        cp_bar.start(14)
        set_busy(True, "Testing the guesser (up to 256 bounded native renders)…")

        def done(summary: dict) -> None:
            cp_bar.stop()
            written = write_evaluation_report(summary, _resolve(cp_vars["report"].get()))
            methods = summary.get("methods", {})
            cand = methods.get("proposer", {}).get("candidate", {})
            native = methods.get("proposer", {}).get("native", {})
            generative = max(
                methods.get(name, {}).get("native", {}).get("mean_best_similarity") or 0.0
                for name in ("random_legal", "broad_structured"))
            ok, verdict = proposer_gate_verdict(
                cand.get("legal_rate"), cand.get("unique_rate"),
                native.get("mean_best_similarity"), generative)
            cp_show(_render_proposer_eval(summary, str(written)) + ["", f"GATE: {verdict}"])
            set_busy(False, "Gate reached: new sounds next." if ok else "Gate missed: stay on tabs 6–7.")

        run_async(lambda: evaluate_proposer(**args), done)

    ttk.Button(cp_frame, text="Test the guesser (256 bounded renders)", command=run_check_proposer).pack(pady=6)

    # -- Targets tab --------------------------------------------------------
    tg_frame = ttk.Frame(notebook, padding=14)
    notebook.add(tg_frame, text=STEPS[7]["tab"])
    _step_intro(tg_frame, STEPS[7])
    tg_form = ttk.Frame(tg_frame)
    tg_form.pack(fill="x", pady=4)
    tg_form.columnconfigure(1, weight=1)
    tg_folder = tk.StringVar(value=DEFAULT_TARGET_FOLDER)
    tg_records = tk.StringVar(value=DEFAULT_TARGET_RECORDS)
    tg_tables = tk.StringVar(value="10")
    tg_seed = tk.StringVar(value="42")
    _entry_row(tg_form, "Wavetable folder", tg_folder, 0,
               browse=lambda: _choose_dir(tg_folder, "Wavetable folder"))
    _entry_row(tg_form, "Target records out", tg_records, 1,
               browse=lambda: _choose_file(tg_records, "Target records", [("Parquet", "*.parquet")]))
    _mini_row(tg_form, 2, (("Tables", tg_tables), ("Seed", tg_seed)))
    tg_out, tg_show = _output_box(tg_frame)
    tg_out.pack(fill="both", expand=True, pady=6)

    @guard
    def run_make_targets() -> None:
        from .curriculum import GeneratorConfig, generate_wavetables

        config = GeneratorConfig(
            tables=_number(tg_tables.get(), "Tables") or 1,
            frame_size=2048, frame_count=256,
            seed=_number(tg_seed.get(), "Seed") or 0,
            folder=_resolve(tg_folder.get()),
        )
        set_busy(True, "Generating mystery wavetables…")
        run_async(lambda: generate_wavetables(config),
                  lambda made: (tg_show([f"Tables created: {len(made[0])}", f"Folder: {config.folder}"]),
                                set_busy(False, "Now import them below — provenance never enters.")))

    @guard
    def run_ingest_targets() -> None:
        from .targets import ingest_wavetable_folder

        folder = _resolve(tg_folder.get())
        output = _resolve(tg_records.get())
        set_busy(True, "Importing as black-box targets…")
        run_async(lambda: ingest_wavetable_folder(folder, output, experiment_id="curriculum-v1"),
                  lambda s: (tg_show([f"Target records: {s.get('targets_written')}",
                                      f"Output: {output}"]),
                             set_busy(False, "Targets ready — the honest exam.")))

    tg_buttons = ttk.Frame(tg_frame)
    tg_buttons.pack(pady=6)
    ttk.Button(tg_buttons, text="1 · Make mystery sounds", command=run_make_targets).pack(side="left", padx=4)
    ttk.Button(tg_buttons, text="2 · Import as targets", command=run_ingest_targets).pack(side="left", padx=4)

    # -- TensorBoard tab ----------------------------------------------------
    tb_frame = ttk.Frame(notebook, padding=14)
    notebook.add(tb_frame, text=STEPS[8]["tab"])
    _step_intro(tb_frame, STEPS[8])
    tb_status = tk.StringVar(value=f"Charts read from `{TENSORBOARD_LOGDIR}/`. Nothing running yet.")
    ttk.Label(tb_frame, textvariable=tb_status, wraplength=680).pack(anchor="w", pady=6)
    ttk.Label(tb_frame, wraplength=680, justify="left", text=(
        "What to look for: training and validation curves slope downward together. "
        "If training improves while validation climbs, the model is memorizing — stop it. "
        "Tabs 4 and 6 log here automatically.")).pack(anchor="w", pady=6)

    def open_charts() -> None:
        tb_status.set("Opening charts…")
        run_async(lambda: ensure_tensorboard(TENSORBOARD_LOGDIR, TENSORBOARD_PORT),
                  lambda message: tb_status.set(message))

    ttk.Button(tb_frame, text="Open TensorBoard in browser", command=open_charts).pack(pady=10)

    # -- Next tab -----------------------------------------------------------
    nx_frame = ttk.Frame(notebook, padding=14)
    notebook.add(nx_frame, text=STEPS[9]["tab"])
    _step_intro(nx_frame, STEPS[9])
    ttk.Label(nx_frame, wraplength=680, justify="left", text=(
        "Not built yet — each unlocks only on evidence:\n\n"
        "• Guided search (Phase 5): needs a guesser that beats dumb luck (tab 7 gate). "
        "It will try many cheap ideas and spend few real renders.\n\n"
        "• Active learning (Phase 6): needs search traces showing where the models "
        "are weak, so new recordings target failures instead of piling up easy wins.\n\n"
        "• Full 256-frame benchmark (Phase 7): the final exam — one shared render "
        "budget spent wisely across a whole wavetable.\n\n"
        "If a tab above is red, that is where the project lives. Do not skip ahead."
    )).pack(anchor="w", pady=6)

    def on_close() -> None:
        if busy["value"] and not messagebox.askyesno(
                "A step is running",
                "A step is still running. Close anyway? Finished work is checkpointed."):
            return
        stop_event.set()
        close_tensorboard()
        root.after(400, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


# ---------------------------------------------------------------------------
# Rendering helpers (pure text shaping over engine summaries).
# ---------------------------------------------------------------------------
def _step_intro(parent: tk.Widget, step: dict) -> None:
    ttk.Label(parent, text=step["title"], font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(0, 2))
    ttk.Label(parent, text=step["what"], wraplength=680).pack(anchor="w", pady=2)
    ttk.Label(parent, text=f"What good looks like: {step['good']}",
              wraplength=680, foreground="#1a5c1a").pack(anchor="w", pady=(2, 6))


def _mini_row(parent: tk.Widget, row: int, fields: tuple) -> None:
    holder = ttk.Frame(parent)
    holder.grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 2))
    for label, variable in fields:
        cell = ttk.Frame(holder)
        cell.pack(side="left", padx=(0, 16))
        ttk.Label(cell, text=label).pack(anchor="w")
        ttk.Entry(cell, textvariable=variable, width=14).pack(anchor="w")


def _plan_fields(parent: tk.Widget) -> dict[str, tk.StringVar]:
    from .gui import OPERATOR_PLAN

    variables: dict[str, tk.StringVar] = {}
    for name, default in OPERATOR_PLAN.items():
        cell = ttk.Frame(parent)
        cell.pack(side="left", padx=(0, 12))
        ttk.Label(cell, text=name).pack(anchor="w")
        variable = tk.StringVar(value=str(default))
        ttk.Entry(cell, textvariable=variable, width=12).pack(anchor="w")
        variables[name] = variable
    return variables


def _choose_file(variable: tk.StringVar, title: str, filetypes: list) -> None:
    chosen = filedialog.askopenfilename(title=title, filetypes=filetypes)
    if chosen:
        variable.set(chosen)


def _choose_dir(variable: tk.StringVar, title: str) -> None:
    chosen = filedialog.askdirectory(title=title)
    if chosen:
        variable.set(chosen)


def _default_forward_checkpoint() -> str:
    """Prefer the new v2 ear; fall back to the legacy v1 checkpoint path."""
    if _resolve(DEFAULT_FORWARD_CHECKPOINT).exists():
        return DEFAULT_FORWARD_CHECKPOINT
    return LEGACY_FORWARD_CHECKPOINT


def _ok_line(report: dict) -> str:
    failed = [name for name, check in report.get("checks", {}).items() if not check.get("ok")]
    if failed:
        return f"Health check FAILED: {', '.join(failed)} — fix these first."
    return "All checks passed. Go to tab 2."


def _render_doctor(report: dict) -> list[str]:
    lines = [f"Overall: {'OK' if report.get('ok') else 'FAILED'}"]
    for name, check in report.get("checks", {}).items():
        mark = "OK " if check.get("ok") else "FAIL"
        lines.append(f"[{mark}] {name}: {check.get('detail')}")
    return lines


def _render_snapshot(snap: dict) -> list[str]:
    if not snap.get("exists"):
        return [f"No file at {snap.get('path')} — tab 3 can create it."]
    return [
        f"Observations: {snap['observations']} (clean voices: {snap['valid_rows']})",
        f"Algorithms covered: {snap['algorithms_covered']}/32",
        f"By validity: {snap['by_validity']}",
        f"By split: {snap['by_split']}",
        f"Lifetime valid renders: {snap['renders_valid_lifetime']}",
    ]


def _render_collect(summary: dict) -> list[str]:
    return [
        f"Stopped: {summary.get('stopped_reason') or 'complete'}",
        f"Rendered {summary.get('rendered')} · duplicates skipped "
        f"{summary.get('duplicates_skipped')} · failures {summary.get('render_failures')}",
        f"By validity: {summary.get('by_validity')}",
        f"Dataset rows now: {summary.get('dataset_rows')} "
        f"({summary.get('elapsed_seconds', 0):.0f}s elapsed)",
    ]


def _render_train(summary: dict, kind: str) -> list[str]:
    history = summary.get("history", [])
    last = history[-1] if history else {}
    return [
        f"The {kind} trained {summary.get('epochs_run', 0)} epochs, "
        f"{summary.get('global_step', 0)} steps.",
        f"Final train loss {_fmt(last.get('train_loss'))} · val loss "
        f"{_fmt(last.get('val_loss'))} · best val {_fmt(summary.get('best_val'))}",
        f"Best checkpoint: {summary.get('best_checkpoint')}",
    ]


def _render_forward_eval(summary: dict) -> list[str]:
    overall = summary.get("overall") or {}
    ranking = summary.get("ranking") or {}
    scored = summary.get("count", summary.get("target_count"))
    loss_text = (f"overall loss {overall['loss']:.4f}"
                 if isinstance(overall.get("loss"), float)
                 else "embedding-distance scorer (no waveform loss)")
    return [
        f"Test patches scored: {scored} · {loss_text}",
        f"Ranking accuracy: {ranking.get('pairwise_accuracy')} "
        f"(chance is 0.50; gate needs > 0.60)",
        f"Top-1 regret: {ranking.get('top1_regret')} vs random "
        f"{ranking.get('random_expected_regret')} (smaller is better)",
    ]


def _render_proposer_eval(summary: dict, written: str) -> list[str]:
    methods = summary.get("methods", {})
    lines = [f"Native renders used: {summary.get('actual_native_renders')}"]
    for name in ("proposer", "random_legal", "broad_structured", "nearest_native"):
        method = methods.get(name, {})
        native = method.get("native", {})
        candidate = method.get("candidate", {})
        lines.append(
            f"{name}: legal {candidate.get('legal_rate')} unique {candidate.get('unique_rate')} "
            f"best similarity {native.get('mean_best_similarity')} "
            f"curve {native.get('budget_curve')}")
    lines.append(f"Full report: {written}")
    return lines
