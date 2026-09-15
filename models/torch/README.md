# Optional PyTorch predictor

This directory contains an optional CPU PyTorch training and inference path for native-observation JSONL files produced by `scripts/build-native-dataset.mjs`.

```text
python models/torch/train.py --dataset native.jsonl --algorithm 1 --out predictor.pt
python models/torch/infer.py --checkpoint predictor.pt --target DexFraggler-imported-targets.json
```

PyTorch is intentionally not bundled with DexFraggler. If it is unavailable, the dependency-free `npm run train:predictor` / `npm run infer:predictor` path and native retrieval remain available. Both predictors emit proposals only; the Windows runner must measure them with the native Dexed reference before saving a result.
