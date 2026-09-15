"""Infer a legal DX7 proposal from an imported periodic target."""
import argparse
import json
from pathlib import Path

try:
    import torch
    from torch import nn
except ModuleNotFoundError as error:
    raise SystemExit("PyTorch is optional and is not installed. Install torch in the active Python environment, or use npm run infer:predictor.") from error

FEATURE_SIZE = 64
LABEL_SIZE = 31


def target_values(filename):
    raw = json.loads(Path(filename).read_text(encoding="utf-8"))
    target = raw[0] if isinstance(raw, list) else raw
    harmonics = target.get("harmonics")
    if not harmonics:
        raise ValueError("The target must contain imported harmonic coefficients.")
    values = [((float(sine) ** 2 + float(cosine) ** 2) ** 0.5) for sine, cosine in zip(harmonics["sin"][:FEATURE_SIZE], harmonics["cos"][:FEATURE_SIZE])]
    values += [0.0] * (FEATURE_SIZE - len(values))
    norm = sum(item * item for item in values) ** 0.5 or 1.0
    return [item / norm for item in values]


def patch_from_labels(labels, algorithm):
    operators = []
    for index in range(6):
        offset = index * 5
        operators.append({"op": index + 1, "coarse": max(0, min(31, round(labels[offset] * 31))), "fine": max(0, min(99, round(labels[offset + 1] * 99))), "detune": max(0, min(14, round(labels[offset + 2] * 14))), "mode": 1 if labels[offset + 3] >= 0.5 else 0, "level": max(0, min(99, round(labels[offset + 4] * 99)))})
    return {"algorithm": algorithm, "feedback": max(0, min(7, round(labels[-1] * 7))), "operators": operators}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    model = nn.Sequential(nn.Linear(FEATURE_SIZE, 128), nn.Tanh(), nn.Linear(128, LABEL_SIZE))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    with torch.no_grad():
        labels = model(torch.tensor([target_values(args.target)], dtype=torch.float32))[0].tolist()
    print(json.dumps({"patch": patch_from_labels(labels, checkpoint["algorithm"]), "source": "pytorch-predictor-v1"}))


if __name__ == "__main__":
    main()
