"""
Step ML-4: Embedded-Friendly Feature Extraction (Event-Synchronized)
Project: eng-4k-project-ml
Extracts 6 low-compute physical features from partial discharge curves:
- Dynamic Ohmic Voltage Drop (OCV - Loaded Step)
- Partial Discharge Sag (100s to 1000s under load)
- Discharge Slope (dV/dt)
- Temperature Rise & Mean Operating Temperature
- Steady-state Current Verification
"""

import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROCESSED_DIR = Path("data/processed")
SUMMARY_CSV = PROCESSED_DIR / "discharge_cycles_summary.csv"
OUTPUT_FEATURES_CSV = PROCESSED_DIR / "features_extracted.csv"

# Partial discharge evaluation window relative to load engagement (seconds)
T_START = 100.0    # 100s after load begins (transients settled)
T_END = 1000.0     # 1000s (~16.6 minutes) evaluation point


def extract_cycle_features(voltage: np.ndarray, current: np.ndarray, temp: np.ndarray, time_sec: np.ndarray):
    """
    Computes 6 low-compute features synchronized to the physical load engagement event (|I| >= 1.5A).
    """
    # 1. Identify the exact sample where the 2A discharge current turns ON
    is_loaded = np.abs(current) >= 1.5
    load_indices = np.where(is_loaded)[0]

    if len(load_indices) == 0:
        # Fallback threshold in case of mild current deviation
        is_loaded = np.abs(current) >= 0.8
        load_indices = np.where(is_loaded)[0]

    if len(load_indices) == 0:
        raise ValueError("No active discharge load current found in cycle.")

    idx_load_start = int(load_indices[0])

    # 2. Extract true Open-Circuit Voltage (OCV) prior to load application
    if idx_load_start > 0:
        v_ocv = float(np.max(voltage[:idx_load_start]))
        t_0 = float(temp[0])
    else:
        v_ocv = float(voltage[0])
        t_0 = float(temp[0])

    # First loaded voltage sample under 2A load
    v_loaded_start = float(voltage[idx_load_start])

    # Feature 1: True Ohmic Drop (proportional to internal DC resistance ESR)
    v_drop_ohmic = v_ocv - v_loaded_start

    # 3. Create time series relative to the load engagement point (t_rel = 0 at load start)
    t_rel = time_sec[idx_load_start:] - time_sec[idx_load_start]
    v_rel = voltage[idx_load_start:]
    i_rel = current[idx_load_start:]
    temp_rel = temp[idx_load_start:]

    # Interpolate key points along the relative timeline
    v_100 = float(np.interp(T_START, t_rel, v_rel))
    v_1000 = float(np.interp(T_END, t_rel, v_rel))
    t_1000 = float(np.interp(T_END, t_rel, temp_rel))

    # Feature 2: Voltage Drop across 900s stabilized window
    v_drop_window = v_100 - v_1000

    # Feature 3: Discharge Voltage Slope dV/dt (V/s)
    v_slope = v_drop_window / (T_END - T_START)

    # Feature 4: Temperature Rise over 1000s (°C)
    temp_rise = t_1000 - t_0

    # Feature 5 & 6: Mean Temperature and Mean Current over [100s, 1000s]
    mask = (t_rel >= T_START) & (t_rel <= T_END)
    temp_mean = float(np.mean(temp_rel[mask]))
    current_mean = float(np.mean(np.abs(i_rel[mask])))

    return {
        "v_drop_ohmic": round(v_drop_ohmic, 6),
        "v_drop_window": round(v_drop_window, 6),
        "v_slope": round(v_slope, 8),
        "temp_rise": round(temp_rise, 4),
        "temp_mean": round(temp_mean, 4),
        "current_mean": round(current_mean, 4)
    }


def run_feature_extraction():
    print("=" * 65)
    print("RUNNING STEP ML-4: EMBEDDED-FRIENDLY FEATURE EXTRACTION")
    print("=" * 65)

    if not SUMMARY_CSV.exists():
        raise FileNotFoundError(f"Missing {SUMMARY_CSV}. Run Step ML-3 first.")

    df_summary = pd.read_csv(SUMMARY_CSV)
    extracted_rows = []

    # Process cell by cell
    for cell_id, group in df_summary.groupby("cell_id"):
        npz_path = PROCESSED_DIR / f"{cell_id}_discharge.npz"
        assert npz_path.exists(), f"ERROR: Missing archive: {npz_path}"

        npz_data = np.load(npz_path)

        for _, row in group.iterrows():
            d_idx = int(row["discharge_cycle_idx"])
            cycle_key = f"cycle_{d_idx:03d}"

            voltage = npz_data[f"{cycle_key}_voltage"]
            current = npz_data[f"{cycle_key}_current"]
            temp = npz_data[f"{cycle_key}_temperature"]
            time_sec = npz_data[f"{cycle_key}_time"]

            # Compute features
            feats = extract_cycle_features(voltage, current, temp, time_sec)

            # Combine with ground-truth labels and identifiers
            record = {
                "cell_id": cell_id,
                "discharge_cycle_idx": d_idx,
                **feats,
                "capacity_ah": row["capacity_ah"],
                "soh_percent": row["soh_percent"]
            }
            extracted_rows.append(record)

        print(f" [PASS] Extracted features for {cell_id} ({len(group)} cycles)")

    df_features = pd.DataFrame(extracted_rows)

    # Strict Sanity & Assertion Gates
    print("\nExecuting Feature Integrity Checks...")
    assert len(df_features) == 636, f"ERROR: Expected 636 rows, got {len(df_features)}"
    assert df_features.isna().sum().sum() == 0, "ERROR: NaN values detected in extracted features."

    # Physical Boundary Checks
    assert (df_features["v_drop_ohmic"] > 0.05).all(), (
        f"ERROR: Ohmic drop out of physical bounds. Min found: {df_features['v_drop_ohmic'].min()}"
    )
    assert (df_features["v_drop_window"] > 0.0).all(), "ERROR: Non-positive discharge voltage drop."
    assert (df_features["current_mean"] > 1.8).all() and (df_features["current_mean"] < 2.2).all(), (
        "ERROR: Current out of expected 2.0A test range."
    )
    assert (df_features["temp_mean"] > 15.0).all() and (df_features["temp_mean"] < 50.0).all(), (
        "ERROR: Operating temperatures out of physical bounds."
    )

    # Export to CSV
    df_features.to_csv(OUTPUT_FEATURES_CSV, index=False)
    assert OUTPUT_FEATURES_CSV.exists(), f"ERROR: Failed to save {OUTPUT_FEATURES_CSV}"

    print(" [PASS] All physical boundary assertions verified.")
    print(f" [OUTPUT] Features exported to: {OUTPUT_FEATURES_CSV}\n")

    # Display statistical distribution table
    print("Feature Distribution Summary (Input Matrix):")
    summary_cols = ["v_drop_ohmic", "v_drop_window", "v_slope", "temp_rise", "temp_mean", "current_mean", "soh_percent"]
    print(df_features[summary_cols].describe().round(4).to_string())

    print("\n" + "=" * 65)
    print("ALL ML-4 SANITY CHECKS PASSED: Feature dataset ready for scaling.")
    print("=" * 65)


if __name__ == "__main__":
    run_feature_extraction()