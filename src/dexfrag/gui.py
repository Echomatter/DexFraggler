"""Small operator GUI for the bounded Phase 2 initial sampling run."""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .budget import BudgetCaps
from .collector import CollectionSummary, collect

OPERATOR_PLAN = {
    "coherent_ratio": 2000,
    "broad_structured": 5000,
    "random_legal": 2000,
    "structure_aware": 2000,
    "local_mutation": 2000,
}


def launch(dataset: Path, *, max_renders: int, seed: int = 0) -> None:
    root = tk.Tk()
    root.title("DexFraggler — Phase 2 initial sampling")
    root.minsize(480, 250)
    state = {"running": False}
    progress = tk.IntVar(value=0)
    status = tk.StringVar(value="Ready to build the initial test sampling.")
    detail = tk.StringVar(value="")

    ttk.Label(root, text="Phase 2 · Build initial test sampling", font=("TkDefaultFont", 13, "bold")).pack(pady=(14, 4))
    ttk.Label(root, textvariable=status, wraplength=440).pack(pady=4)
    bar = ttk.Progressbar(root, maximum=max_renders, variable=progress, length=410)
    bar.pack(pady=8)
    ttk.Label(root, textvariable=detail).pack(pady=2)
    controls = ttk.Frame(root)
    controls.pack(pady=10)
    start = ttk.Button(controls, text="Start sampling")
    start.pack(side="left", padx=4)
    ttk.Button(controls, text="Choose dataset", command=lambda: _choose_dataset(dataset, status)).pack(side="left", padx=4)

    def update(summary: CollectionSummary) -> None:
        root.after(0, lambda: (
            progress.set(min(summary.rendered + summary.render_failures + summary.duplicates_skipped, max_renders)),
            detail.set(f"Rendered {summary.rendered} · duplicates {summary.duplicates_skipped} · failures {summary.render_failures}"),
        ))

    def run() -> None:
        try:
            summary = collect(dataset, plan=OPERATOR_PLAN, seed=seed,
                              caps=BudgetCaps(max_renders_attempted=max_renders),
                              progress_callback=update)
            root.after(0, lambda: status.set(f"Finished: {summary.stopped_reason or 'complete'}"))
        except Exception as exc:  # keep the operator window useful on failure
            root.after(0, lambda: messagebox.showerror("Sampling failed", str(exc)))
        finally:
            root.after(0, lambda: (start.config(state="normal"), state.update(running=False)))

    def begin() -> None:
        if state["running"]:
            return
        state["running"] = True
        start.config(state="disabled")
        status.set(f"Running bounded sampling into {dataset}…")
        threading.Thread(target=run, daemon=True).start()

    start.config(command=begin)
    root.mainloop()


def _choose_dataset(current: Path, status: tk.StringVar) -> None:
    chosen = filedialog.asksaveasfilename(initialfile=str(current), filetypes=[("Parquet", "*.parquet")])
    if chosen:
        status.set(f"Selected dataset: {chosen}")
