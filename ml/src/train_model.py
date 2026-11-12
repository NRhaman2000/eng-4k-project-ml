"""
Step ML-6: Model Architecture Design & Offline Training
Project: eng-4k-project-ml

Changes vs. original:
- Trains on ALL three training cells (no leaky random validation split).
- Fixed epoch count chosen by cell-wise CV, so no early stopping on leaked data.
- Op determinism enabled; seed taken from config.py.
- Adds a linear baseline builder used by cross_validate.py / evaluate_model.py.
"""

import os
import sys
import time
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
import tensorflow as tf  # noqa: E402
from tensorflow import keras  # noqa: E402
from tensorflow.keras import layers, regularizers  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import EPOCHS, BATCH_SIZE, LEARNING_RATE, L2, DEPLOY_SEED  # noqa: E402

PROCESSED_DIR = Path("data/processed")
MODELS_DIR = Path("models")
SAVED_MODEL_DIR = MODELS_DIR / "saved"
SCALED_DATA_PATH = PROCESSED_DIR / "dataset_scaled.npz"
MODEL_OUTPUT_PATH = SAVED_MODEL_DIR / "soh_model.keras"
LOSS_PLOT_PATH = MODELS_DIR / "training_curves.png"


def build_tflm_compatible_model(input_dim: int) -> keras.Model:
    """Dense + ReLU only MLP: Input(n) -> 16 -> 8 -> 1 (fractional SoH)."""
    return keras.Sequential([
        layers.Input(shape=(input_dim,), name="physical_features_input"),
        layers.Dense(16, activation="relu", kernel_regularizer=regularizers.l2(L2), name="dense_1"),
        layers.Dense(8, activation="relu", kernel_regularizer=regularizers.l2(L2), name="dense_2"),
        layers.Dense(1, activation="linear", name="soh_fraction_output"),
    ], name="TinyML_Battery_SoH")


def build_linear_baseline(input_dim: int) -> keras.Model:
    """Plain linear regression, the baseline the MLP must beat."""
    return keras.Sequential([
        layers.Input(shape=(input_dim,)),
        layers.Dense(1, activation="linear", name="linear_soh"),
    ], name="Linear_Baseline")


def train(X, y, seed: int, verbose: int = 0):
    keras.utils.set_random_seed(seed)
    model = build_tflm_compatible_model(X.shape[1])
    model.compile(optimizer=keras.optimizers.legacy.Adam(learning_rate=LEARNING_RATE),
                  loss="mse", metrics=["mae"])
    history = model.fit(X, y, epochs=EPOCHS, batch_size=BATCH_SIZE, verbose=verbose)
    return model, history


def run_model_training():
    print("=" * 65)
    print("RUNNING STEP ML-6: MODEL TRAINING (ALL TRAINING CELLS)")
    print("=" * 65)

    if not SCALED_DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {SCALED_DATA_PATH}. Run Step ML-5 first.")
    SAVED_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tf.config.experimental.enable_op_determinism()

    data = np.load(SCALED_DATA_PATH)
    X_train, y_train, y_train_pct = data["X_train"], data["y_train"], data["y_train_pct"]
    print(f"  Training Set: {X_train.shape[0]} samples, {X_train.shape[1]} features "
          f"({list(data['feature_names'])})")

    start = time.time()
    model, history = train(X_train, y_train, DEPLOY_SEED, verbose=0)
    print(f" [PASS] Training completed in {time.time() - start:.2f} s ({EPOCHS} epochs, seed {DEPLOY_SEED}).")
    model.summary()

    total_params = model.count_params()
    assert total_params < 1000, f"Model too large: {total_params} parameters."
    print(f" [PASS] {total_params} parameters (< 1,000).")

    model.save(MODEL_OUTPUT_PATH)
    assert MODEL_OUTPUT_PATH.exists()
    print(f" [OUTPUT] Trained model saved to: {MODEL_OUTPUT_PATH}")

    train_mae = float(np.mean(np.abs(model.predict(X_train, verbose=0).ravel() * 100 - y_train_pct)))
    print(f"  Training-fit MAE: {train_mae:.2f}% SoH (in-sample; NOT a generalization estimate,")
    print("  see models/cv_results.csv for cell-wise CV and ML-7 for the test cell)")

    plt.figure(figsize=(10, 4.5))
    plt.subplot(1, 2, 1)
    plt.plot(history.history["loss"], label="Train loss (MSE)", color="#1f77b4")
    plt.title("Training loss"); plt.xlabel("Epoch"); plt.ylabel("MSE")
    plt.grid(True, linestyle="--", alpha=0.6); plt.legend()
    plt.subplot(1, 2, 2)
    plt.plot([m * 100 for m in history.history["mae"]], label="Train MAE (% SoH)", color="#2ca02c")
    plt.title("Training MAE (% SoH)"); plt.xlabel("Epoch"); plt.ylabel("MAE (%)")
    plt.grid(True, linestyle="--", alpha=0.6); plt.legend()
    plt.tight_layout(); plt.savefig(LOSS_PLOT_PATH, dpi=200); plt.close()
    print(f" [OUTPUT] Training curves plot saved to: {LOSS_PLOT_PATH}")
    print("=" * 65)


if __name__ == "__main__":
    run_model_training()
