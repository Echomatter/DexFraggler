import pytest
import torch

from dexfrag.forward_model import ForwardModel
from dexfrag.native import NativeRendererError
from dexfrag.patch import blank_patch
from dexfrag.proposer_eval import (
    _render_method,
    evaluate_proposer,
    native_similarity,
    patch_model_inputs,
    rank_with_forward,
    write_evaluation_report,
)
from dexfrag.proposer_model import ProposerModel, candidate_diversity, generate_candidates
from dexfrag.proposer_training import ProposerTrainConfig, train
from test_forward_training import _build_corpus


def test_native_similarity_and_forward_ranking():
    target = torch.zeros(3, 2048)
    target[:, :] = torch.linspace(-1.0, 1.0, 2048)
    exact = native_similarity(target, target)
    assert exact["native_similarity"] == pytest.approx(1.0)
    assert exact["native_mse"] == pytest.approx(0.0)
    shifted = native_similarity(target + 0.5, target)
    assert shifted["native_similarity"] < 1.0
    candidates = generate_candidates(ProposerModel(hidden_dim=16, harmonic_bands=8, conv_channels=4), target, count=4, seed=4)
    inputs = patch_model_inputs(candidates, torch.device("cpu"))
    assert inputs["algorithm"].shape == (4,)
    ranked, scores = rank_with_forward(ForwardModel(hidden_dims=(8, 8)), candidates, target, torch.device("cpu"), batch_size=2)
    assert len(ranked) == len(scores) == 4
    assert scores == sorted(scores)


def test_proposer_evaluation_protected_split_and_report(tmp_path):
    corpus = _build_corpus(tmp_path, n_train=2, n_val=1)
    checkpoint_dir = tmp_path / "proposer"
    config = ProposerTrainConfig(
        corpus=corpus, checkpoint_dir=checkpoint_dir, device="cpu", epochs=1,
        max_rows=2, batch_size=1,
    )
    train(config, model=ProposerModel(hidden_dim=16, harmonic_bands=8, conv_channels=4))
    report = evaluate_proposer(
        corpus, config.best_path, max_targets=1, candidate_count=4,
        native_budget=0, include_baselines=False,
    )
    assert report["protected_split"] == "test"
    assert report["model_config"]["hidden_dim"] == 16
    assert report["forward_ranking_enabled"] is False
    assert report["methods"]["proposer"]["candidate"]["legal_rate"] == 1.0
    output = write_evaluation_report(report, tmp_path / "report.json")
    assert output.exists()


def test_candidate_diversity_rejects_empty():
    with pytest.raises(ValueError):
        candidate_diversity([])


def test_native_render_errors_are_returned_without_crashing():
    class BrokenRenderer:
        def render(self, patch):
            raise NativeRendererError("synthetic native failure")

    target = torch.zeros(3, 2048)
    candidates = [blank_patch()]
    scored, rendered, error = _render_method(
        BrokenRenderer(), candidates, target, 1, {}, [0], 1
    )
    assert scored == [] and rendered == 0
    assert error == "synthetic native failure"
