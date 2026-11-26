"""
compare_baselines.py

Compares the MLP with simpler ways of estimating SoH, using the same NASA
cells and the same test protocol as the MLP:

  1. Linear-type models (Linear, Ridge, Lasso, Huber, polynomial) trained on
     the same features the MLP uses (v_drop_window, temp_rise).
  2. Coulomb counting (the conventional method): integrate current over the
     full discharge to get capacity, then SoH = capacity / 2.0 Ah x 100.
     It also tests what happens with a small current-sensor error, partial
     counting between 3.9 V and 3.5 V, and counting over only our 1000 s window.
  3. Float32 vs INT8 model file size.

Protocol (the same one cross_validate.py uses for the MLP):
  - leave-one-cell-out over B0005/6/7: train on 2 cells, test on the 3rd
  - report the mean and the worst fold
  - then train on all 3 and score once on B0018

Run it from the ml/ folder after the normal pipeline has been run:

    cd ml
    python src/compare_baselines.py

Output: printed tables, plus models/baseline_comparison.csv and
models/coulomb_counting.csv.
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge, Lasso, HuberRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler, PolynomialFeatures

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TRAIN_CELLS, TEST_CELL, TARGET_NAME  # noqa: E402

warnings.filterwarnings("ignore")
PROCESSED = Path("data/processed")
MODELS = Path("models")
RATED_AH = 2.0


def mae(err):
    return float(np.mean(np.abs(err)))


# ---------------------------------------------------------------------------
# 1. Linear-type models on the MLP's features
# ---------------------------------------------------------------------------
def linear_models():
    df = pd.read_csv(PROCESSED / "features_extracted.csv")
    f1 = ["v_drop_window"]
    f2 = ["v_drop_window", "temp_rise"]
    f3 = ["v_drop_ohmic", "v_drop_window", "temp_rise"]

    def lin():
        return LinearRegression()

    models = {
        "Linear, sag only": (f1, lin),
        "Linear (2 feat)": (f2, lin),
        "Ridge alpha=1 (2 feat)": (f2, lambda: Ridge(alpha=1.0)),
        "Lasso alpha=0.05 (2 feat)": (f2, lambda: Lasso(alpha=0.05)),
        "Huber (2 feat)": (f2, HuberRegressor),
        "Polynomial deg 2 (2 feat)": (f2, None),
        "Linear (3 feat, with ohmic)": (f3, lin),
    }

    def build(name, make):
        if make is None:
            return make_pipeline(StandardScaler(), PolynomialFeatures(2), Ridge(alpha=0.1))
        return make_pipeline(StandardScaler(), make())

    rows = []
    for name, (feats, make) in models.items():
        folds = {}
        for held in TRAIN_CELLS:
            tr = df[df.cell_id.isin([c for c in TRAIN_CELLS if c != held])]
            ev = df[df.cell_id == held]
            m = build(name, make).fit(tr[feats], tr[TARGET_NAME])
            folds[held] = mae(m.predict(ev[feats]) - ev[TARGET_NAME])

        tr = df[df.cell_id.isin(TRAIN_CELLS)]
        te = df[df.cell_id == TEST_CELL]
        m = build(name, make).fit(tr[feats], tr[TARGET_NAME])
        err = m.predict(te[feats]) - te[TARGET_NAME]
        est = m[-1]
        n_params = sum(np.size(getattr(est, a)) for a in ("coef_", "intercept_") if hasattr(est, a))
        rows.append({
            "method": name, "params": n_params,
            "cv_mean_mae": np.mean(list(folds.values())),
            "cv_worst_fold_mae": max(folds.values()),
            **{f"cv_{k}": v for k, v in folds.items()},
            f"{TEST_CELL}_mae": mae(err),
            f"{TEST_CELL}_max_err": float(np.max(np.abs(err))),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. Coulomb counting
# ---------------------------------------------------------------------------
def charge_ah(t, i):
    """Trapezoid integral of current over time, in Ah."""
    return float(np.sum((i[1:] + i[:-1]) / 2 * np.diff(t)) / 3600)


def coulomb_counting():
    summary = pd.read_csv(PROCESSED / "discharge_cycles_summary.csv")
    rows = []
    for cell, g in summary.groupby("cell_id"):
        z = np.load(PROCESSED / f"{cell}_discharge.npz")
        for _, r in g.iterrows():
            k = f"cycle_{int(r.discharge_cycle_idx):03d}"
            t = z[k + "_time"].astype(float)
            v = z[k + "_voltage"].astype(float)
            i = np.abs(z[k + "_current"].astype(float))

            q_full = charge_ah(t, i)                 # full discharge
            q_offset = charge_ah(t, i + 0.020)       # sensor reads 20 mA high
            q_gain = charge_ah(t, i * 1.01)          # sensor reads 1 % high

            on = np.where(i >= 1.5)[0]
            s = on[0] if len(on) else 0
            tt, vv, ii = t[s:], v[s:], i[s:]
            a, b = np.argmax(vv <= 3.9), np.argmax(vv <= 3.5)
            q_part = charge_ah(tt[a:b + 1], ii[a:b + 1]) if b > a else np.nan
            w = (tt - tt[0]) <= 1000
            q_1000 = charge_ah(tt[w], ii[w])          # only our 1000 s test window

            rows.append({
                "cell_id": cell, "cycle": int(r.discharge_cycle_idx),
                "soh_label": r[TARGET_NAME], "duration_min": (t[-1] - t[0]) / 60,
                "q_full_ah": q_full, "q_1000s_ah": q_1000, "q_3v9_3v5_ah": q_part,
                "soh_cc": q_full / RATED_AH * 100,
                "soh_cc_offset20mA": q_offset / RATED_AH * 100,
                "soh_cc_gain1pct": q_gain / RATED_AH * 100,
            })
    d = pd.DataFrame(rows)

    # Partial counting needs a fitted map from Ah (3.9 -> 3.5 V) to SoH: same protocol
    dd = d.dropna(subset=["q_3v9_3v5_ah"])
    folds = {}
    for held in TRAIN_CELLS:
        tr = dd[dd.cell_id.isin([c for c in TRAIN_CELLS if c != held])]
        ev = dd[dd.cell_id == held]
        m = LinearRegression().fit(tr[["q_3v9_3v5_ah"]], tr.soh_label)
        folds[held] = mae(m.predict(ev[["q_3v9_3v5_ah"]]) - ev.soh_label)
    tr, te = dd[dd.cell_id.isin(TRAIN_CELLS)], dd[dd.cell_id == TEST_CELL]
    m = LinearRegression().fit(tr[["q_3v9_3v5_ah"]], tr.soh_label)
    e_part = m.predict(te[["q_3v9_3v5_ah"]]) - te.soh_label

    err = d.soh_cc - d.soh_label
    rows = [
        {"method": "Coulomb count, full discharge (all 4 cells, no fitting)",
         f"{TEST_CELL}_mae": mae(err), f"{TEST_CELL}_max_err": float(np.max(np.abs(err)))},
        {"method": "  same, current sensor +20 mA offset",
         f"{TEST_CELL}_mae": mae(d.soh_cc_offset20mA - d.soh_label)},
        {"method": "  same, current sensor +1 % gain error",
         f"{TEST_CELL}_mae": mae(d.soh_cc_gain1pct - d.soh_label)},
        {"method": "Coulomb count, partial 3.9 -> 3.5 V + linear map",
         "cv_mean_mae": np.mean(list(folds.values())), "cv_worst_fold_mae": max(folds.values()),
         **{f"cv_{k}": v for k, v in folds.items()},
         f"{TEST_CELL}_mae": mae(e_part), f"{TEST_CELL}_max_err": float(np.max(np.abs(e_part)))},
    ]
    d.to_csv(MODELS / "coulomb_counting.csv", index=False)

    print("\nCoulomb counting facts")
    print(f"  full discharge takes {d.duration_min.min():.0f} to {d.duration_min.max():.0f} min")
    print(f"  charge in our 1000 s window: {d.q_1000s_ah.min():.3f} to {d.q_1000s_ah.max():.3f} Ah "
          f"(correlation with SoH {np.corrcoef(d.q_1000s_ah, d.soh_label)[0, 1]:.2f}), "
          "so counting over our short test says nothing about health")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. MLP row (from the files the pipeline already wrote)
# ---------------------------------------------------------------------------
def mlp_row():
    cv = pd.read_csv(MODELS / "cv_results.csv")
    r = cv[(cv.model == "mlp") & (cv.features == "win+temp")].iloc[0]
    ev = pd.read_csv(MODELS / "evaluation_metrics.csv").iloc[0]
    return pd.DataFrame([{
        "method": "MLP 2-16-8-1 (ours)", "params": 193,
        "cv_mean_mae": r.cv_mean_mae, "cv_worst_fold_mae": r.cv_worst_fold_mae,
        "cv_B0005": r.holdout_B0005, "cv_B0006": r.holdout_B0006, "cv_B0007": r.holdout_B0007,
        f"{TEST_CELL}_mae": ev.mae_soh_percent, f"{TEST_CELL}_max_err": ev.max_error_percent,
    }])


def model_sizes():
    try:
        import tensorflow as tf
    except ImportError:
        print("\n(TensorFlow not found, skipping the float vs INT8 size check)")
        return
    keras_path = MODELS / "saved" / "soh_model.keras"
    int8_path = MODELS / "tflite" / "soh_model_int8.tflite"
    model = tf.keras.models.load_model(keras_path)
    f32 = tf.lite.TFLiteConverter.from_keras_model(model).convert()
    weights = sum(np.size(w) for layer in model.layers for w in layer.get_weights()[:1])
    biases = sum(np.size(w) for layer in model.layers for w in layer.get_weights()[1:])
    print("\nFloat32 vs INT8")
    print(f"  parameters: {model.count_params()} ({weights} weights, {biases} biases)")
    print(f"  .tflite file: float32 {len(f32)} B, INT8 {int8_path.stat().st_size} B")
    print(f"  weights+biases: float32 {4 * (weights + biases)} B, INT8 {weights + 4 * biases} B "
          "(int8 weights, int32 biases)")


if __name__ == "__main__":
    table = pd.concat([mlp_row(), linear_models(), coulomb_counting()], ignore_index=True)
    pd.set_option("display.width", 200)
    print("\nSoH error in % points (lower is better)")
    print(table.round(2).fillna("").to_string(index=False))
    table.round(3).to_csv(MODELS / "baseline_comparison.csv", index=False)
    print(f"\nSaved {MODELS / 'baseline_comparison.csv'} and {MODELS / 'coulomb_counting.csv'}")
    model_sizes()
