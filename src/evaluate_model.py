"""
Step ML-7: Holdout Evaluation on Unseen Cell B0018
Project: eng-4k-project-ml

Changes vs. original:
- Reports the deployed model AND mean +/- std over 10 training seeds, so the
  headline number is not one lucky draw.
- Compares against a linear baseline trained on the same data.
- Removed the R^2 > 0.60 gate (it looked tuned to the test cell); R^2 is still reported.
- Plots use the real discharge cycle index.
"""

import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
import tensorflow as tf  # noqa: E402
from tensorflow import keras  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import REPORT_SEEDS, MAE_SPEC_PCT, TEST_CELL, EPOCHS, BATCH_SIZE, LEARNING_RATE  # noqa: E402
from train_model import train, build_linear_baseline  # noqa: E402

MODELS_DIR = Path("models")
SAVED_MODEL_PATH = MODELS_DIR / "saved" / "soh_model.keras"
SCALED_DATA_PATH = Path("data/processed/dataset_scaled.npz")
BENCHMARK_PLOT_PATH = MODELS_DIR / "test_benchmark_b0018.png"
METRICS_CSV_PATH = MODELS_DIR / "evaluation_metrics.csv"


def metrics(pred, y):
    r = pred - y
    return {
        "mae": float(np.mean(np.abs(r))),
        "rmse": float(np.sqrt(np.mean(r ** 2))),
        "max_err": float(np.max(np.abs(r))),
        "r2": float(1 - np.sum(r ** 2) / np.sum((y - y.mean()) ** 2)),
    }


def run_evaluation():
    print("=" * 65)
    print(f"RUNNING STEP ML-7: UNSEEN CELL HOLDOUT BENCHMARK ({TEST_CELL})")
    print("=" * 65)
    tf.config.experimental.enable_op_determinism()

    data = np.load(SCALED_DATA_PATH)
    X_train, y_train = data["X_train"], data["y_train"]
    X_test, y_test_pct, cycles = data["X_test"], data["y_test_pct"], data["cycle_test"]

    # 1. Deployed model
    model = keras.models.load_model(SAVED_MODEL_PATH)
    preds_pct = model.predict(X_test, verbose=0).ravel() * 100.0
    dep = metrics(preds_pct, y_test_pct)

    # 2. Seed robustness: retrain with each report seed
    seed_maes = []
    for s in REPORT_SEEDS:
        m, _ = train(X_train, y_train, s)
        seed_maes.append(metrics(m.predict(X_test, verbose=0).ravel() * 100.0, y_test_pct)["mae"])
    seed_maes = np.array(seed_maes)

    # 3. Linear baseline
    keras.utils.set_random_seed(0)
    lin = build_linear_baseline(X_train.shape[1])
    lin.compile(optimizer=keras.optimizers.legacy.Adam(LEARNING_RATE), loss="mse")
    lin.fit(X_train, y_train, epochs=EPOCHS, batch_size=BATCH_SIZE, verbose=0)
    lin_pred = lin.predict(X_test, verbose=0).ravel() * 100.0
    base = metrics(lin_pred, y_test_pct)

    print(f"\nSCORECARD ({TEST_CELL}, never used for any choice):")
    print(f"  Deployed MLP:  MAE {dep['mae']:.2f}%  RMSE {dep['rmse']:.2f}%  Max {dep['max_err']:.2f}%  R² {dep['r2']:.3f}")
    print(f"  MLP over {len(REPORT_SEEDS)} seeds: MAE {seed_maes.mean():.2f} ± {seed_maes.std():.2f}% "
          f"(range {seed_maes.min():.2f} to {seed_maes.max():.2f})")
    print(f"  Linear baseline: MAE {base['mae']:.2f}%  Max {base['max_err']:.2f}%  R² {base['r2']:.3f}")

    assert dep["mae"] < MAE_SPEC_PCT, f"ERROR: deployed model MAE {dep['mae']:.2f}% exceeds spec"
    n_fail = int((seed_maes >= MAE_SPEC_PCT).sum())
    print(f" [PASS] Deployed MAE < {MAE_SPEC_PCT}%. Seeds failing spec: {n_fail}/{len(REPORT_SEEDS)}")

    pd.DataFrame([{
        "test_cell": TEST_CELL, "num_cycles": len(X_test),
        "mae_soh_percent": round(dep["mae"], 4), "rmse_soh_percent": round(dep["rmse"], 4),
        "max_error_percent": round(dep["max_err"], 4), "r2_score": round(dep["r2"], 4),
        "seed_mae_mean": round(seed_maes.mean(), 4), "seed_mae_std": round(seed_maes.std(), 4),
        "seed_mae_min": round(seed_maes.min(), 4), "seed_mae_max": round(seed_maes.max(), 4),
        "linear_baseline_mae": round(base["mae"], 4), "linear_baseline_max_error": round(base["max_err"], 4),
    }]).to_csv(METRICS_CSV_PATH, index=False)
    print(f" [OUTPUT] {METRICS_CSV_PATH}")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    ax1.plot(cycles, y_test_pct, label=f"Actual ({TEST_CELL})", color="#1f77b4", linewidth=2.0)
    ax1.plot(cycles, preds_pct, label="TinyML MLP", color="#d62728", linestyle="--")
    ax1.plot(cycles, lin_pred, label="Linear baseline", color="#7f7f7f", linestyle=":")
    ax1.set_title(f"SoH tracking ({TEST_CELL})", fontweight="bold")
    ax1.set_xlabel("Discharge cycle index"); ax1.set_ylabel("SoH (%)")
    ax1.grid(True, linestyle="--", alpha=0.6); ax1.legend()
    ax2.scatter(cycles, preds_pct - y_test_pct, color="#2ca02c", s=20, alpha=0.7)
    ax2.axhline(0, color="black", linewidth=1)
    for sgn in (1, -1):
        ax2.axhline(sgn * dep["mae"], color="red", linestyle=":")
    ax2.set_title("Residuals (predicted - actual)", fontweight="bold")
    ax2.set_xlabel("Discharge cycle index"); ax2.set_ylabel("Error (% SoH)")
    ax2.grid(True, linestyle="--", alpha=0.6)
    plt.tight_layout(); plt.savefig(BENCHMARK_PLOT_PATH, dpi=200); plt.close()
    print(f" [OUTPUT] {BENCHMARK_PLOT_PATH}")
    print("=" * 65)


if __name__ == "__main__":
    run_evaluation()
