"""
Step ML-7: Model Evaluation, Residual Analysis & MAE Benchmarking
Project: eng-4k-project-ml
Evaluates the trained model against Cell B0018 (completely unseen holdout test battery),
computes MAE, RMSE, R2, and exports evaluation plots.
"""

import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import tensorflow as tf
from tensorflow import keras

PROCESSED_DIR = Path("data/processed")
MODELS_DIR = Path("models")
SAVED_MODEL_PATH = MODELS_DIR / "saved" / "soh_model.keras"
SCALED_DATA_PATH = PROCESSED_DIR / "dataset_scaled.npz"
BENCHMARK_PLOT_PATH = MODELS_DIR / "test_benchmark_b0018.png"
METRICS_CSV_PATH = MODELS_DIR / "evaluation_metrics.csv"


def run_evaluation():
    print("=" * 65)
    print("RUNNING STEP ML-7: UNSEEN BATTERY HOLDOUT BENCHMARK (CELL B0018)")
    print("=" * 65)

    if not SAVED_MODEL_PATH.exists():
        raise FileNotFoundError(f"Missing {SAVED_MODEL_PATH}. Run Step ML-6 first.")
    if not SCALED_DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {SCALED_DATA_PATH}. Run Step ML-5 first.")

    # 1. Load Data
    data = np.load(SCALED_DATA_PATH)
    X_test = data["X_test"]
    y_test_pct = data["y_test_pct"]
    
    print(f"Loaded Holdout Battery Data:")
    print(f"  Target Test Cell:  Cell B0018")
    print(f"  Total Test Cycles: {len(X_test)} cycles")
    print(f"  Actual SoH Range:  {y_test_pct.min():.2f}% to {y_test_pct.max():.2f}% SoH")

    # 2. Load Model & Run Inference
    model = keras.models.load_model(SAVED_MODEL_PATH)
    preds_norm = model.predict(X_test, verbose=0).flatten()
    
    # Scale from normalized [0.0, 1.0] back to percentage [0.0, 100.0]
    preds_pct = preds_norm * 100.0

    # 3. Compute Rigorous Statistical Metrics
    residuals = preds_pct - y_test_pct
    abs_errors = np.abs(residuals)
    
    mae = float(np.mean(abs_errors))
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    max_err = float(np.max(abs_errors))
    
    # R2 Score calculation
    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((y_test_pct - np.mean(y_test_pct)) ** 2)
    r2_score = float(1.0 - (ss_res / ss_tot))

    # 4. Display Benchmark Scorecard
    print("\n" + "=" * 65)
    print("CAPSTONE TEST SCORECARD (CELL B0018 - COMPLETELY UNSEEN):")
    print("=" * 65)
    print(f"  Mean Absolute Error (MAE): {mae:.2f}% SoH")
    print(f"  Root Mean Sq Error (RMSE): {rmse:.2f}% SoH")
    print(f"  Max Absolute Error:        {max_err:.2f}% SoH")
    print(f"  Coefficient of Det. (R²):  {r2_score:.4f}")
    print("=" * 65)

    # 5. Assertion Gates
    # Capstone Requirement: MAE must be < 4.0%
    assert mae < 4.0, f"ERROR: Holdout Test MAE {mae:.2f}% exceeds 4.0% tolerance."
    assert r2_score > 0.60, f"ERROR: R² score {r2_score:.4f} is too low (expected > 0.60 for single cell holdout)."
    print(" [PASS] Test MAE satisfies capstone performance criteria (MAE < 4.0%).")
    print(" [PASS] R² score confirms tracking of battery capacity degradation trend.")

    # 6. Save Metrics to CSV for Documentation
    df_metrics = pd.DataFrame([{
        "test_cell": "B0018",
        "num_cycles": len(X_test),
        "mae_soh_percent": round(mae, 4),
        "rmse_soh_percent": round(rmse, 4),
        "max_error_percent": round(max_err, 4),
        "r2_score": round(r2_score, 4)
    }])
    df_metrics.to_csv(METRICS_CSV_PATH, index=False)
    print(f" [OUTPUT] Metrics summary exported to: {METRICS_CSV_PATH}")

    # 7. Generate Benchmark Visualization
    cycles = np.arange(1, len(X_test) + 1)
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Subplot 1: Degradation Curve Tracking
    ax1.plot(cycles, y_test_pct, label="Actual Ground Truth (B0018)", color="#1f77b4", linewidth=2.0)
    ax1.plot(cycles, preds_pct, label="TinyML Predicted SoH", color="#d62728", linestyle="--", linewidth=1.8)
    ax1.set_title("SoH Capacity Fade Tracking (Cell B0018)", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Discharge Cycle Number")
    ax1.set_ylabel("State-of-Health (%)")
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.legend()

    # Subplot 2: Residual Error Distribution
    ax2.scatter(cycles, residuals, color="#2ca02c", alpha=0.7, edgecolors="none", s=25)
    ax2.axhline(0.0, color="black", linestyle="-", linewidth=1.0)
    ax2.axhline(mae, color="red", linestyle=":", label=f"+MAE ({mae:.2f}%)")
    ax2.axhline(-mae, color="red", linestyle=":", label=f"-MAE (-{mae:.2f}%)")
    ax2.set_title("Prediction Residuals (Predicted - Actual)", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Discharge Cycle Number")
    ax2.set_ylabel("Error (% SoH)")
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.legend()

    plt.tight_layout()
    plt.savefig(BENCHMARK_PLOT_PATH, dpi=200)
    plt.close()
    assert BENCHMARK_PLOT_PATH.exists(), f"ERROR: Failed to save {BENCHMARK_PLOT_PATH}"
    print(f" [OUTPUT] Benchmark curves plot saved to: {BENCHMARK_PLOT_PATH}")

    print("\n" + "=" * 65)
    print("ALL ML-7 SANITY CHECKS PASSED: Model is verified for INT8 quantization.")
    print("=" * 65)


if __name__ == "__main__":
    run_evaluation()