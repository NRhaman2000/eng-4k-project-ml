"""
Step ML-5: Dataset Normalization, Scaling & Group Partitioning
Project: eng-4k-project-ml
Extracts the 3 pure physical degradation features (ohmic drop, window drop, temp rise),
partitions Group 1 (B0005, B0006, B0007) for train/validation, reserves B0018 for testing,
and exports C header scaling constants.
"""

import os
import sys
import json
from pathlib import Path
import numpy as np
import pandas as pd

PROCESSED_DIR = Path("data/processed")
MODELS_DIR = Path("models")
C_HEADERS_DIR = MODELS_DIR / "c_headers"
FEATURES_CSV = PROCESSED_DIR / "features_extracted.csv"
OUTPUT_NPZ = PROCESSED_DIR / "dataset_scaled.npz"
SCALING_JSON = MODELS_DIR / "scaling_params.json"
SCALING_HEADER = C_HEADERS_DIR / "scaling_params.h"

# 3 Pure Physical Degradation Features (All relative deltas)
FEATURE_NAMES = [
    "v_drop_ohmic",    # Ohmic resistance drop (ESR)
    "v_drop_window",   # Polarization sag over 900s
    "temp_rise"        # Joulean self-heating (I^2 * R)
]
TARGET_NAME = "soh_percent"


def run_data_preparation():
    print("=" * 65)
    print("RUNNING STEP ML-5: ROBUST FEATURE NORMALIZATION & PARTITIONING")
    print("=" * 65)

    if not FEATURES_CSV.exists():
        raise FileNotFoundError(f"Missing {FEATURES_CSV}. Run Step ML-4 first.")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    C_HEADERS_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(FEATURES_CSV)

    # 1. Dataset Partitioning (Literature Standard)
    # Group 1 (B0005, B0006, B0007) -> Train (80%) and Validation (20%)
    # Group 2 (B0018) -> Completely Unseen Holdout Test Battery
    group1_mask = df["cell_id"].isin(["B0005", "B0006", "B0007"])
    test_mask = df["cell_id"] == "B0018"

    df_group1 = df[group1_mask].copy()
    df_test = df[test_mask].copy()

    # Deterministic reproducible 80/20 train/val split of Group 1
    np.random.seed(42)
    indices = np.arange(len(df_group1))
    np.random.shuffle(indices)

    split_boundary = int(0.80 * len(df_group1))
    train_idx = indices[:split_boundary]
    val_idx = indices[split_boundary:]

    df_train = df_group1.iloc[train_idx].copy()
    df_val = df_group1.iloc[val_idx].copy()

    print(f"Dataset Partitioning:")
    print(f"  Training Cohort (B0005, B0006, B0007):   {len(df_train)} cycles")
    print(f"  Validation Cohort (B0005, B0006, B0007): {len(df_val)} cycles")
    print(f"  Holdout Test Battery (Cell B0018):       {len(df_test)} cycles")

    # 2. Extract 3 Physical Features and Target
    X_train_raw = df_train[FEATURE_NAMES].values.astype(np.float64)
    y_train_pct = df_train[TARGET_NAME].values.astype(np.float32)

    X_val_raw = df_val[FEATURE_NAMES].values.astype(np.float64)
    y_val_pct = df_val[TARGET_NAME].values.astype(np.float32)

    X_test_raw = df_test[FEATURE_NAMES].values.astype(np.float64)
    y_test_pct = df_test[TARGET_NAME].values.astype(np.float32)

    # 3. Fit Standard Scaler on Training Set ONLY
    mean_vec_64 = np.mean(X_train_raw, axis=0)
    std_vec_64 = np.std(X_train_raw, axis=0)
    std_vec_64[std_vec_64 == 0.0] = 1.0

    # 4. Standardize Feature Tensors: (X - mean) / std
    X_train_scaled = ((X_train_raw - mean_vec_64) / std_vec_64).astype(np.float32)
    X_val_scaled = ((X_val_raw - mean_vec_64) / std_vec_64).astype(np.float32)
    X_test_scaled = ((X_test_raw - mean_vec_64) / std_vec_64).astype(np.float32)

    # Normalize targets to [0.0, 1.0] scale (fractional SoH)
    y_train_norm = (y_train_pct / 100.0).astype(np.float32)
    y_val_norm = (y_val_pct / 100.0).astype(np.float32)
    y_test_norm = (y_test_pct / 100.0).astype(np.float32)

    mean_vec_32 = mean_vec_64.astype(np.float32)
    std_vec_32 = std_vec_64.astype(np.float32)

    # 5. Sanity Checks
    np.testing.assert_allclose(np.mean(X_train_scaled, axis=0), 0.0, atol=1e-3)
    np.testing.assert_allclose(np.std(X_train_scaled, axis=0), 1.0, atol=1e-3)
    print(" [PASS] 3 physical features normalized cleanly (mean ≈ 0.0, std ≈ 1.0).")

    # 6. Save Compressed Binary Tensors
    np.savez_compressed(
        OUTPUT_NPZ,
        X_train=X_train_scaled,
        y_train=y_train_norm,
        y_train_pct=y_train_pct,
        X_val=X_val_scaled,
        y_val=y_val_norm,
        y_val_pct=y_val_pct,
        X_test=X_test_scaled,
        y_test=y_test_norm,
        y_test_pct=y_test_pct,
        feature_names=FEATURE_NAMES
    )
    print(f" [OUTPUT] Clean tensors saved to: {OUTPUT_NPZ}")

    # 7. Export Scaling Parameters to JSON
    scaling_dict = {
        "features": FEATURE_NAMES,
        "mean": [float(v) for v in mean_vec_32],
        "std": [float(v) for v in std_vec_32],
        "target_scale_factor": 100.0
    }
    with open(SCALING_JSON, "w") as f_json:
        json.dump(scaling_dict, f_json, indent=4)
    print(f" [OUTPUT] Scaling metadata saved to: {SCALING_JSON}")

    # 8. Export C Header for Microcontroller Firmware
    with open(SCALING_HEADER, "w") as f_hdr:
        f_hdr.write("/*\n")
        f_hdr.write(" * Auto-generated scaling parameters for on-device TinyML inference\n")
        f_hdr.write(" * Project: eng-4k-project-ml\n")
        f_hdr.write(" */\n\n")
        f_hdr.write("#ifndef SCALING_PARAMS_H\n")
        f_hdr.write("#define SCALING_PARAMS_H\n\n")
        f_hdr.write(f"#define NUM_FEATURES {len(FEATURE_NAMES)}\n\n")

        f_hdr.write("static const float FEATURE_MEANS[NUM_FEATURES] = {\n")
        f_hdr.write("    " + ", ".join([f"{val:.8f}f" for val in mean_vec_32]) + "\n")
        f_hdr.write("};\n\n")

        f_hdr.write("static const float FEATURE_STDS[NUM_FEATURES] = {\n")
        f_hdr.write("    " + ", ".join([f"{val:.8f}f" for val in std_vec_32]) + "\n")
        f_hdr.write("};\n\n")

        f_hdr.write("static inline void normalize_features(const float* raw_in, float* norm_out) {\n")
        f_hdr.write("    for (int i = 0; i < NUM_FEATURES; i++) {\n")
        f_hdr.write("        norm_out[i] = (raw_in[i] - FEATURE_MEANS[i]) / FEATURE_STDS[i];\n")
        f_hdr.write("    }\n")
        f_hdr.write("}\n\n")
        f_hdr.write("#endif /* SCALING_PARAMS_H */\n")

    print(f" [OUTPUT] Firmware C header generated: {SCALING_HEADER}\n")

    print("Fitted Physical Normalization Constants:")
    for name, m, s in zip(FEATURE_NAMES, mean_vec_32, std_vec_32):
        print(f"  - {name:<15}: mean = {m:11.6f} | std = {s:11.6f}")

    print("\n" + "=" * 65)
    print("ALL ML-5 SANITY CHECKS PASSED: Tensors ready for Step ML-6.")
    print("=" * 65)


if __name__ == "__main__":
    run_data_preparation()