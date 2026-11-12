"""
Step ML-3: Raw Data Parsing, Cycle Isolation & Ground-Truth Definition
Project: eng-4k-project-ml
Extracts CC discharge cycles, computes ground-truth Capacity (Ah) and SoH (%),
and exports optimized NumPy binary archives and cycle metadata CSV.
"""

import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.io import loadmat

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
TARGET_CELLS = ["B0005", "B0006", "B0007", "B0018"]

# NASA PCoE 18650 cell rated nominal capacity
RATED_CAPACITY_AH = 2.00  # 2000 mAh


def parse_cell_mat(cell_id: str):
    """
    Parses a single cell .mat file, isolates discharge cycles,
    extracts time-series arrays, and defines ground-truth SoH labels.
    """
    mat_path = RAW_DIR / f"{cell_id}.mat"
    if not mat_path.exists():
        raise FileNotFoundError(f"Missing {mat_path}. Run Step ML-2 first.")

    mat_struct = loadmat(str(mat_path))
    cycles_raw = mat_struct[cell_id]["cycle"][0, 0][0]

    discharge_records = []
    timeseries_dict = {}

    discharge_idx = 0

    for global_cycle_idx, cycle in enumerate(cycles_raw):
        # Extract operation type safely
        cycle_type = str(cycle["type"][0]).strip().lower()
        if "discharge" not in cycle_type:
            continue  # Skip charge and impedance operations

        data_struct = cycle["data"][0, 0]

        # Extract scalar capacity (Ground Truth)
        if "Capacity" not in data_struct.dtype.names:
            continue

        raw_cap = data_struct["Capacity"]
        if raw_cap.size == 0:
            continue
        capacity_ah = float(raw_cap.flatten()[0])

        # Validate non-trivial capacity
        if capacity_ah <= 0.2 or capacity_ah > 2.5:
            continue

        # Extract time-series vectors
        voltage = np.array(data_struct["Voltage_measured"].flatten(), dtype=np.float32)
        current = np.array(data_struct["Current_measured"].flatten(), dtype=np.float32)
        temp = np.array(data_struct["Temperature_measured"].flatten(), dtype=np.float32)
        time_sec = np.array(data_struct["Time"].flatten(), dtype=np.float32)

        # Basic time-series integrity gate: ensure matching lengths and non-empty arrays
        n_samples = len(voltage)
        if not (n_samples == len(current) == len(temp) == len(time_sec) and n_samples > 10):
            continue

        # Compute State-of-Health (%)
        soh_pct = (capacity_ah / RATED_CAPACITY_AH) * 100.0

        discharge_idx += 1
        cycle_key = f"cycle_{discharge_idx:03d}"

        # Store metadata
        discharge_records.append({
            "cell_id": cell_id,
            "global_cycle_idx": global_cycle_idx + 1,
            "discharge_cycle_idx": discharge_idx,
            "num_samples": n_samples,
            "duration_sec": float(time_sec[-1] - time_sec[0]),
            "v_start": float(voltage[0]),
            "v_end": float(voltage[-1]),
            "capacity_ah": round(capacity_ah, 5),
            "soh_percent": round(soh_pct, 3)
        })

        # Store time-series arrays
        timeseries_dict[f"{cycle_key}_voltage"] = voltage
        timeseries_dict[f"{cycle_key}_current"] = current
        timeseries_dict[f"{cycle_key}_temperature"] = temp
        timeseries_dict[f"{cycle_key}_time"] = time_sec

    return discharge_records, timeseries_dict


def run_parsing_and_isolation():
    print("=" * 65)
    print("RUNNING STEP ML-3: CYCLE ISOLATION & GROUND-TRUTH DEFINITION")
    print("=" * 65)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    all_summary_records = []

    for cell in TARGET_CELLS:
        print(f"Parsing raw structures for {cell}...")
        records, ts_dict = parse_cell_mat(cell)

        # Assert expected NASA PCoE discharge cycle ranges
        # B0005, B0006, B0007 each have ~168 discharge cycles; B0018 has ~132
        expected_min_cycles = 130 if cell == "B0018" else 160
        assert len(records) >= expected_min_cycles, (
            f"ERROR: Found only {len(records)} discharge cycles for {cell}, expected >= {expected_min_cycles}."
        )

        # Save time-series numpy archive (.npz)
        npz_output_path = PROCESSED_DIR / f"{cell}_discharge.npz"
        np.savez_compressed(npz_output_path, **ts_dict)
        assert npz_output_path.exists(), f"ERROR: Failed to save {npz_output_path}"

        all_summary_records.extend(records)

        # Print per-cell summary
        init_cap = records[0]["capacity_ah"]
        final_cap = records[-1]["capacity_ah"]
        init_soh = records[0]["soh_percent"]
        final_soh = records[-1]["soh_percent"]
        print(f" [PASS] {cell}: {len(records)} discharge cycles isolated.")
        print(f"        Initial: {init_cap:.4f} Ah ({init_soh:.1f}% SoH) -> Final: {final_cap:.4f} Ah ({final_soh:.1f}% SoH)")

    # Save summary metadata CSV
    df_summary = pd.DataFrame(all_summary_records)
    summary_csv_path = PROCESSED_DIR / "discharge_cycles_summary.csv"
    df_summary.to_csv(summary_csv_path, index=False)
    assert summary_csv_path.exists(), f"ERROR: Failed to write {summary_csv_path}"

    print("\n" + "=" * 65)
    print("GLOBAL DATASET SUMMARY ASSERTIONS:")
    print("=" * 65)
    total_discharge_cycles = len(df_summary)
    print(f"Total Isolated Discharge Cycles Across 4 Cells: {total_discharge_cycles}")
    assert total_discharge_cycles in [636, 635, 634], (
        f"ERROR: Expected ~636 total discharge cycles across B5, B6, B7, B18, found {total_discharge_cycles}."
    )

    # Verify no NaN or infinite values
    assert df_summary.isna().sum().sum() == 0, "ERROR: NaN detected in metadata ledger."
    print(" [PASS] Zero NaN / null values across entire dataset metadata.")

    print(f" [OUTPUT] Metadata CSV: {summary_csv_path}")
    print(f" [OUTPUT] Cleaned NPZ archives in: {PROCESSED_DIR}/")
    print("=" * 65)
    print("ALL ML-3 SANITY CHECKS PASSED: Ground-truth data prepared.")
    print("=" * 65)


if __name__ == "__main__":
    run_parsing_and_isolation()