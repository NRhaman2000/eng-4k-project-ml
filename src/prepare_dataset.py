"""
Step ML-5: Dataset Normalization, Scaling & Cell-wise Partitioning
Project: eng-4k-project-ml

Changes vs. original:
- No random cycle shuffle into train/val. Neighbouring cycles from the same
  cell are near-duplicates, so a random split leaked and gave a falsely low
  validation MAE. Model selection now uses leave-one-cell-out CV
  (src/cross_validate.py) and the final model trains on all three training cells.
- Feature list comes from src/config.py.
"""

import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import FEATURE_NAMES, TARGET_NAME, TRAIN_CELLS, TEST_CELL  # noqa: E402

PROCESSED_DIR = Path("data/processed")
MODELS_DIR = Path("models")
C_HEADERS_DIR = MODELS_DIR / "c_headers"
FEATURES_CSV = PROCESSED_DIR / "features_extracted.csv"
OUTPUT_NPZ = PROCESSED_DIR / "dataset_scaled.npz"
SCALING_JSON = MODELS_DIR / "scaling_params.json"
SCALING_HEADER = C_HEADERS_DIR / "scaling_params.h"


def run_data_preparation():
    print("=" * 65)
    print("RUNNING STEP ML-5: FEATURE NORMALIZATION & CELL-WISE PARTITIONING")
    print("=" * 65)

    if not FEATURES_CSV.exists():
        raise FileNotFoundError(f"Missing {FEATURES_CSV}. Run Step ML-4 first.")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    C_HEADERS_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(FEATURES_CSV)
    df_train = df[df["cell_id"].isin(TRAIN_CELLS)].sort_values(["cell_id", "discharge_cycle_idx"])
    df_test = df[df["cell_id"] == TEST_CELL].sort_values("discharge_cycle_idx")

    # Guard: no cell may appear in both sets
    assert set(df_train["cell_id"]).isdisjoint(set(df_test["cell_id"])), "ERROR: cell overlap train/test"

    print("Dataset Partitioning (by physical cell):")
    print(f"  Training cells {TRAIN_CELLS}: {len(df_train)} cycles")
    print(f"  Holdout test cell {TEST_CELL}:     {len(df_test)} cycles")
    print(f"  Features: {FEATURE_NAMES}")

    X_train_raw = df_train[FEATURE_NAMES].values.astype(np.float64)
    y_train_pct = df_train[TARGET_NAME].values.astype(np.float32)
    X_test_raw = df_test[FEATURE_NAMES].values.astype(np.float64)
    y_test_pct = df_test[TARGET_NAME].values.astype(np.float32)

    # Fit standard scaler on training cells ONLY
    mean_vec_64 = np.mean(X_train_raw, axis=0)
    std_vec_64 = np.std(X_train_raw, axis=0)
    std_vec_64[std_vec_64 == 0.0] = 1.0

    X_train_scaled = ((X_train_raw - mean_vec_64) / std_vec_64).astype(np.float32)
    X_test_scaled = ((X_test_raw - mean_vec_64) / std_vec_64).astype(np.float32)

    np.testing.assert_allclose(np.mean(X_train_scaled, axis=0), 0.0, atol=1e-3)
    np.testing.assert_allclose(np.std(X_train_scaled, axis=0), 1.0, atol=1e-3)
    print(" [PASS] Features normalized on training cells (mean ~ 0, std ~ 1).")

    # Report how far the test cell sits outside the training distribution
    print(f"  Test-cell z-score range: min {X_test_scaled.min(0).round(2)}, max {X_test_scaled.max(0).round(2)}")

    mean_vec_32 = mean_vec_64.astype(np.float32)
    std_vec_32 = std_vec_64.astype(np.float32)

    np.savez_compressed(
        OUTPUT_NPZ,
        X_train=X_train_scaled,
        y_train=(y_train_pct / 100.0).astype(np.float32),
        y_train_pct=y_train_pct,
        cell_train=df_train["cell_id"].values.astype(str),
        X_test=X_test_scaled,
        y_test=(y_test_pct / 100.0).astype(np.float32),
        y_test_pct=y_test_pct,
        cycle_test=df_test["discharge_cycle_idx"].values.astype(np.int32),
        feature_names=np.array(FEATURE_NAMES),
    )
    print(f" [OUTPUT] Tensors saved to: {OUTPUT_NPZ}")

    with open(SCALING_JSON, "w") as f_json:
        json.dump({
            "features": FEATURE_NAMES,
            "mean": [float(v) for v in mean_vec_32],
            "std": [float(v) for v in std_vec_32],
            "target_scale_factor": 100.0,
        }, f_json, indent=4)
    print(f" [OUTPUT] Scaling metadata saved to: {SCALING_JSON}")

    with open(SCALING_HEADER, "w") as f_hdr:
        f_hdr.write("/*\n * Auto-generated scaling parameters for on-device TinyML inference\n")
        f_hdr.write(" * Project: eng-4k-project-ml\n")
        f_hdr.write(" * Feature order: " + ", ".join(FEATURE_NAMES) + "\n */\n\n")
        f_hdr.write("#ifndef SCALING_PARAMS_H\n#define SCALING_PARAMS_H\n\n")
        f_hdr.write(f"#define NUM_FEATURES {len(FEATURE_NAMES)}\n\n")
        f_hdr.write("static const float FEATURE_MEANS[NUM_FEATURES] = {\n")
        f_hdr.write("    " + ", ".join([f"{v:.8f}f" for v in mean_vec_32]) + "\n};\n\n")
        f_hdr.write("static const float FEATURE_STDS[NUM_FEATURES] = {\n")
        f_hdr.write("    " + ", ".join([f"{v:.8f}f" for v in std_vec_32]) + "\n};\n\n")
        f_hdr.write("static inline void normalize_features(const float* raw_in, float* norm_out) {\n")
        f_hdr.write("    for (int i = 0; i < NUM_FEATURES; i++) {\n")
        f_hdr.write("        norm_out[i] = (raw_in[i] - FEATURE_MEANS[i]) / FEATURE_STDS[i];\n")
        f_hdr.write("    }\n}\n\n#endif /* SCALING_PARAMS_H */\n")
    print(f" [OUTPUT] Firmware C header generated: {SCALING_HEADER}\n")

    for name, m, s in zip(FEATURE_NAMES, mean_vec_32, std_vec_32):
        print(f"  - {name:<15}: mean = {m:11.6f} | std = {s:11.6f}")

    print("\n" + "=" * 65)
    print("ALL ML-5 SANITY CHECKS PASSED: run src/cross_validate.py next.")
    print("=" * 65)


if __name__ == "__main__":
    run_data_preparation()
