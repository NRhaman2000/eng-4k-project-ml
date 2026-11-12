"""
Step ML-5b: Leave-One-Cell-Out Cross-Validation (model & feature selection)
Project: eng-4k-project-ml

Uses ONLY the training cells (B0005, B0006, B0007). For every candidate
(model type x feature set), it trains on two cells and tests on the third,
for every fold and several seeds. Selection rule: lowest worst-fold MAE
(a BMS must be accurate on every cell, not just on average). The test cell
B0018 is never touched here.

Output: models/cv_results.csv
"""

import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
import tensorflow as tf  # noqa: E402
from tensorflow import keras  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (TRAIN_CELLS, TEST_CELL, CANDIDATE_FEATURE_SETS, TARGET_NAME,  # noqa: E402
                    EPOCHS, BATCH_SIZE, LEARNING_RATE, CV_SEEDS, FEATURE_NAMES)
from train_model import build_tflm_compatible_model, build_linear_baseline  # noqa: E402

FEATURES_CSV = Path("data/processed/features_extracted.csv")
CV_CSV = Path("models/cv_results.csv")

tf.config.experimental.enable_op_determinism()


def fit_predict(kind, X_tr, y_tr, X_ev, seed):
    keras.utils.set_random_seed(seed)
    mu, sd = X_tr.mean(0), X_tr.std(0)
    sd[sd == 0] = 1.0
    model = build_tflm_compatible_model(X_tr.shape[1]) if kind == "mlp" else build_linear_baseline(X_tr.shape[1])
    model.compile(optimizer=keras.optimizers.legacy.Adam(LEARNING_RATE), loss="mse")
    model.fit((X_tr - mu) / sd, y_tr / 100.0, epochs=EPOCHS, batch_size=BATCH_SIZE, verbose=0)
    return model.predict((X_ev - mu) / sd, verbose=0).ravel() * 100.0


def run_cross_validation():
    print("=" * 65)
    print("RUNNING STEP ML-5b: LEAVE-ONE-CELL-OUT CROSS-VALIDATION")
    print("=" * 65)
    df = pd.read_csv(FEATURES_CSV)
    assert TEST_CELL not in TRAIN_CELLS
    df = df[df["cell_id"].isin(TRAIN_CELLS)]   # test cell excluded on purpose

    rows = []
    for kind in ["linear", "mlp"]:
        for fs_name, feats in CANDIDATE_FEATURE_SETS.items():
            fold_maes = {}
            for hold in TRAIN_CELLS:
                tr = df[df["cell_id"] != hold]
                ev = df[df["cell_id"] == hold]
                seeds = CV_SEEDS if kind == "mlp" else CV_SEEDS[:1]
                fold_maes[hold] = [
                    float(np.mean(np.abs(fit_predict(kind, tr[feats].values, tr[TARGET_NAME].values,
                                                     ev[feats].values, s) - ev[TARGET_NAME].values)))
                    for s in seeds
                ]
            all_maes = [m for v in fold_maes.values() for m in v]
            row = {
                "model": kind,
                "features": fs_name,
                "cv_mean_mae": np.mean(all_maes),
                "cv_worst_fold_mae": max(np.mean(v) for v in fold_maes.values()),
                "seed_std": np.std(all_maes),
                **{f"holdout_{c}": np.mean(v) for c, v in fold_maes.items()},
            }
            rows.append(row)
            print(f"  {kind:<6} {fs_name:<9} mean {row['cv_mean_mae']:.2f}%  worst {row['cv_worst_fold_mae']:.2f}%  "
                  f"seed std {row['seed_std']:.2f}")

    res = pd.DataFrame(rows).sort_values("cv_worst_fold_mae").round(3)
    CV_CSV.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(CV_CSV, index=False)
    best = res.iloc[0]
    print(f"\n [OUTPUT] {CV_CSV}")
    print(f" Best by worst-fold MAE: {best['model']} / {best['features']} ({best['cv_worst_fold_mae']:.2f}%)")
    chosen = [k for k, v in CANDIDATE_FEATURE_SETS.items() if v == FEATURE_NAMES]
    print(f" Configured in config.py: mlp / {chosen[0] if chosen else FEATURE_NAMES}")
    print("=" * 65)


if __name__ == "__main__":
    run_cross_validation()
