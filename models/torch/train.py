"""Train an optional native-descriptor -> legal-DX7-parameter proposal model."""
import argparse
import json
from pathlib import Path

try:
    import torch
    from torch import nn
except ModuleNotFoundError as error:
    raise SystemExit("PyTorch is optional and is not installed. Install torch in the active Python environment, or use npm run train:predictor.") from error

FEATURE_SIZE = 64
LABEL_SIZE = 31


def load_records(filename, algorithm):
    records = []
    for line in Path(filename).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if value.get("patch", {}).get("algorithm") == algorithm:
            descriptor = next((note["descriptor"] for note in value["notes"] if note["note"] == 57), None)
            if descriptor:
                values = [float(item) for item in descriptor["magnitude"][:FEATURE_SIZE]]
                values += [0.0] * (FEATURE_SIZE - len(values))
                norm = sum(item * item for item in values) ** 0.5 or 1.0
                patch = value["patch"]
                labels = []
                for operator in patch["operators"]:
                    labels += [operator["coarse"] / 31, operator["fine"] / 99, operator["detune"] / 14, operator["mode"], operator["level"] / 99]
                labels.append(patch["feedback"] / 7)
                records.append(( [item / norm for item in values], labels, value["key"] ))
    if not records:
        raise ValueError(f"No A3 descriptors for algorithm {algorithm}.")
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--algorithm", required=True, type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument("--epochs", type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.algorithm <= 32 or args.epochs < 1:
        raise ValueError("algorithm must be 1..32 and epochs must be positive")
    torch.manual_seed(7)
    records = load_records(args.dataset, args.algorithm)
    x = torch.tensor([record[0] for record in records], dtype=torch.float32)
    y = torch.tensor([record[1] for record in records], dtype=torch.float32)
    model = nn.Sequential(nn.Linear(FEATURE_SIZE, 128), nn.Tanh(), nn.Linear(128, LABEL_SIZE))
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=0.0005)
    loss_fn = nn.MSELoss()
    for _ in range(args.epochs):
        optimizer.zero_grad()
        loss = loss_fn(model(x), y)
        loss.backward()
        optimizer.step()
    torch.save({"format": "dexfraggler-pytorch-predictor", "version": 1, "algorithm": args.algorithm, "feature_size": FEATURE_SIZE, "label_size": LABEL_SIZE, "state_dict": model.state_dict(), "training": {"epochs": args.epochs, "examples": len(records), "loss": float(loss.detach()), "keys": [record[2] for record in records]}}, args.out)
    print(json.dumps({"out": str(Path(args.out).resolve()), "algorithm": args.algorithm, "examples": len(records), "loss": float(loss.detach())}))


if __name__ == "__main__":
    main()
