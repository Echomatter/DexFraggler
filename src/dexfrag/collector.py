"""Resumable, crash-safe, deduplicated native-observation collector.

Ties together acquisition sources (``acquisition.py``), mutation families
(``mutate.py``), the native renderer (``native.py``), canonical feature
extraction (``features.py``), the split policy (``splits.py``), the render
budget ledger (``budget.py``) and Parquet storage (``storage.py``) into the
single ``collect()`` entry point ``dexfrag collect`` calls.

Guarantees (Phase 2 STOP-gate requirements):

- **append-friendly / resumable**: existing dataset rows are loaded first;
  collection always continues from where it left off.
- **crash-safe**: rows are buffered and flushed to disk (and the budget
  ledger saved) every ``flush_every`` valid observations, and again in a
  ``finally`` block on any exception including ``KeyboardInterrupt``, so a
  Ctrl+C or crash loses at most one partial flush window of progress.
- **deduplicated by exact patch identity**: a patch already present in the
  dataset (or already produced earlier in this same run) is never
  re-rendered.
- **bounded**: a ``BudgetCaps`` is checked before every native render.
- **deterministic when seeded**: every acquisition source and mutation
  choice is driven by one ``random.Random(seed)`` instance, and iterated in
  a fixed source order.
- **explicit about failures**: renders that raise are logged to a sidecar
  ``*.failures.jsonl`` file (patch + error), never silently dropped and
  never mixed into the valid observation table.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from .acquisition import AcquisitionCandidate, broad_structured_exploration, coherent_ratio_exploration, \
    local_mutation, random_legal_exploration, structure_aware_exploration
from .budget import Budget, BudgetCaps, BudgetExceeded
from .features import canonical_frame
from .native import NativeRenderer, NativeRendererError
from .splits import assign_split, benchmark_holdout as compute_benchmark_holdout, lineage_root_key as compute_lineage_root_key
from .storage import append_observations, observation_row_from_capture, read_observations

DEFAULT_PLAN = {
    "coherent_ratio": 16,
    "broad_structured": 16,
    "random_legal": 16,
    "structure_aware": 16,
    "local_mutation": 16,
}

# --- training-data contract (Phase 2 operator-gate revision) ----------------
# Permanent native observations retain *every* validity class -- nothing is
# ever deleted, relabeled, or silently dropped, including genuinely
# `unstable` (non-periodic-at-the-played-note) and `silent`/`near_silent`
# renders. That is deliberate: those are real, legitimate DX7 behavior, and
# discarding them would bias the permanent corpus.
#
# However, `validity_class` is *not* decorative -- later phases (forward
# model, inverse proposer, structured search) must treat it as a first-class
# training-data selector, not just a coverage statistic:
#
#   - `valid`:        the canonical 2048-sample frame is a faithful,
#                      phase-bearing single-cycle reconstruction of a
#                      genuinely periodic-at-the-note waveform. This is the
#                      *only* class that should be used, by default, as a
#                      clean stationary-waveform training target/label.
#   - `near_silent`:   technically periodic-or-not, but too quiet to trust
#                      amplitude/phase estimates from (peak below
#                      NEAR_SILENT_PEAK_THRESHOLD). Usable as permanent
#                      truth for coverage/robustness experiments, but must
#                      not be treated as an ordinary clean training target
#                      without an explicit, documented decision to do so.
#   - `silent`:        true silence. Native ground truth (e.g. "this exact
#                      patch renders silent"), never a periodic-waveform
#                      training target.
#   - `clipped`:       peak at/above CLIPPED_PEAK_THRESHOLD; the canonical
#                      frame may not reflect true operator amplitudes past
#                      the quantization ceiling. Usable as native truth, not
#                      as a clean regression target for amplitude.
#   - `unstable`:      periodicity_ratio below UNSTABLE_PERIODICITY_THRESHOLD
#                      for at least one captured note -- the harmonic-series
#                      canonicalization model does not faithfully represent
#                      this capture at the played note's nominal fundamental
#                      (real inharmonic/beating/non-stationary DX7 behavior,
#                      not a defect). The raw 4096-sample native capture
#                      remains valid ground truth for *that capture*, but the
#                      derived 2048-sample canonical frame must not be fed to
#                      a model as if it were a clean periodic label. Any
#                      later phase that wants to use these rows must define
#                      an explicit different representation/objective for
#                      them (e.g. a raw-waveform or spectrogram-based target)
#                      rather than reusing the periodic-frame contract.
#   - render failures: never stored as observations at all (see
#                      `<dataset>.failures.jsonl`); there is no row, hence no
#                      validity_class, to accidentally consume downstream.
#
# This module and `storage.py` intentionally keep all classes in one table
# with one shared schema (permanent truth is not partitioned by validity),
# but any Phase 3+ dataset loader MUST filter on `validity_class` explicitly
# before treating `canonical_frames_json` as a ground-truth periodic label.

# Validity classification thresholds. These are deliberately conservative
# and documented here (not hidden constants elsewhere): "silent"/"clipped"
# are about raw waveform amplitude across all three captured notes;
# "unstable" is about the canonicalization contract's own periodicity
# diagnostic, i.e. this patch does not behave like a stationary/periodic
# voice at the reference profile's fixed envelope/LFO settings.
SILENT_PEAK_THRESHOLD = 1e-4
NEAR_SILENT_PEAK_THRESHOLD = 1e-3
CLIPPED_PEAK_THRESHOLD = 0.999
UNSTABLE_PERIODICITY_THRESHOLD = 0.5


def _failures_path(dataset_path: Path) -> Path:
    return dataset_path.with_suffix(dataset_path.suffix + ".failures.jsonl")


@dataclass
class CollectionSummary:
    requested: int = 0
    rendered: int = 0
    duplicates_skipped: int = 0
    render_failures: int = 0
    by_validity: dict = field(default_factory=dict)
    by_source: dict = field(default_factory=dict)
    stopped_reason: str | None = None
    elapsed_seconds: float = 0.0
    dataset_rows: int = 0
    dataset_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "requested": self.requested,
            "rendered": self.rendered,
            "duplicates_skipped": self.duplicates_skipped,
            "render_failures": self.render_failures,
            "by_validity": self.by_validity,
            "by_source": self.by_source,
            "stopped_reason": self.stopped_reason,
            "elapsed_seconds": self.elapsed_seconds,
            "dataset_rows": self.dataset_rows,
            "dataset_bytes": self.dataset_bytes,
        }


def classify_validity(capture, frames: dict) -> str:
    peaks = [max(abs(x) for x in wave) for wave in capture.waveforms]
    max_peak = max(peaks)
    if max_peak < SILENT_PEAK_THRESHOLD:
        return "silent"
    if max_peak >= CLIPPED_PEAK_THRESHOLD:
        return "clipped"
    if max_peak < NEAR_SILENT_PEAK_THRESHOLD:
        return "near_silent"
    if min(frame.periodicity_ratio for frame in frames.values()) < UNSTABLE_PERIODICITY_THRESHOLD:
        return "unstable"
    return "valid"


def _build_candidate_stream(rng: random.Random, plan: dict[str, int], mutation_parents: list):
    # coherent_ratio runs first so its (deliberately periodic) outputs are
    # available as local_mutation parents within this same collection run,
    # even when the dataset starts out with zero prior valid observations.
    yield from coherent_ratio_exploration(rng, plan.get("coherent_ratio", 0))
    for count in (plan.get("broad_structured", 0),):
        yield from broad_structured_exploration(rng, count)
    yield from random_legal_exploration(rng, plan.get("random_legal", 0))
    yield from structure_aware_exploration(rng, plan.get("structure_aware", 0))
    yield from local_mutation(rng, mutation_parents, plan.get("local_mutation", 0))


def _load_mutation_parents(existing_table) -> list:
    """(patch, patch_key, lineage_root_key) tuples for valid existing rows,
    usable as local_mutation acquisition parents."""
    if existing_table.num_rows == 0:
        return []
    from .patch import validate_patch
    parents = []
    keys = existing_table.column("key").to_pylist()
    patch_jsons = existing_table.column("patch_json").to_pylist()
    roots = existing_table.column("lineage_root_key").to_pylist()
    validity = existing_table.column("validity_class").to_pylist()
    for key, patch_json, root, valid_class in zip(keys, patch_jsons, roots, validity):
        if valid_class != "valid":
            continue
        parents.append((validate_patch(json.loads(patch_json)), key, root))
    return parents


def collect(
    dataset_path: Path | str,
    *,
    plan: dict[str, int] | None = None,
    seed: int = 0,
    caps: BudgetCaps | None = None,
    executable_path: Path | str | None = None,
    flush_every: int = 16,
    include_waveforms: bool = True,
    progress_callback=None,
) -> CollectionSummary:
    dataset_path = Path(dataset_path)
    plan = plan or DEFAULT_PLAN
    caps = caps or BudgetCaps()
    rng = random.Random(seed)

    existing_table = read_observations(dataset_path)
    existing_keys: set[str] = set(existing_table.column("key").to_pylist()) if existing_table.num_rows else set()
    mutation_parents = _load_mutation_parents(existing_table)

    summary = CollectionSummary()
    failures_path = _failures_path(dataset_path)
    budget = Budget.load(dataset_path)
    buffer: list[dict] = []
    renderer = NativeRenderer(executable_path=executable_path)
    start = time.monotonic()

    def flush():
        nonlocal buffer
        if buffer:
            table = append_observations(dataset_path, buffer)
            summary.dataset_rows = table.num_rows
            buffer = []
        budget.refresh_dataset_bytes(dataset_path)
        budget.save()
        summary.dataset_bytes = budget.dataset_bytes

    try:
        for candidate in _build_candidate_stream(rng, plan, mutation_parents):
            summary.requested += 1
            from .patch import patch_key as compute_patch_key
            key = compute_patch_key(candidate.patch)

            if key in existing_keys:
                summary.duplicates_skipped += 1
                if progress_callback:
                    progress_callback(summary)
                continue

            try:
                budget.check_can_attempt_one_more(caps)
            except BudgetExceeded as exc:
                summary.stopped_reason = str(exc)
                break

            existing_keys.add(key)  # never render the same key twice, even within one run
            try:
                capture = renderer.render(candidate.patch)
            except NativeRendererError as error:
                summary.render_failures += 1
                budget.record_attempt(valid=False)
                with open(failures_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "patch_key": key,
                        "patch": candidate.patch.to_dict(),
                        "acquisition_source": candidate.acquisition_source,
                        "error": str(error),
                        "time": time.time(),
                    }) + "\n")
                if progress_callback:
                    progress_callback(summary)
                continue

            frames = {
                note: canonical_frame(wave, note)
                for note, wave in zip(capture.notes, capture.waveforms)
            }
            validity_class = classify_validity(capture, frames)
            root = compute_lineage_root_key(key, candidate.parent_lineage_root_key)
            split = assign_split(root)
            holdout = compute_benchmark_holdout(root)
            row = observation_row_from_capture(
                capture, frames,
                acquisition_source=candidate.acquisition_source,
                validity_class=validity_class,
                split=split,
                lineage_root_key=root,
                benchmark_holdout=holdout,
                parent_key=candidate.parent_key,
                include_waveforms=include_waveforms,
            )
            buffer.append(row)
            summary.rendered += 1
            summary.by_validity[validity_class] = summary.by_validity.get(validity_class, 0) + 1
            summary.by_source[candidate.acquisition_source] = summary.by_source.get(candidate.acquisition_source, 0) + 1
            budget.record_attempt(valid=(validity_class == "valid"))

            if validity_class == "valid":
                mutation_parents.append((candidate.patch, key, root))

            if len(buffer) >= flush_every:
                flush()
            if progress_callback:
                progress_callback(summary)
        else:
            summary.stopped_reason = summary.stopped_reason or "plan_exhausted"
    finally:
        flush()
        renderer.close()
        summary.elapsed_seconds = time.monotonic() - start

    return summary
