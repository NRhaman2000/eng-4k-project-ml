"""
Step ML-6: Model Architecture Design & Offline Training
Project: eng-4k-project-ml
Designs an ultra-compact, high-speed MLP regression neural network strictly compatible with TFLM.
Trains on Group 1 (B0005, B0006, B0007), validates on held-out cycles, and exports the model.
"""

import os
import sys
import time
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers, regularizers, callbacks

PROCESSED_DIR = Path("data/processed")
MODELS_DIR = Path("models")
SAVED_MODEL_DIR = MODELS_DIR / "saved"
SCALED_DATA_PATH = PROCESSED_DIR / "dataset_scaled.npz"
MODEL_OUTPUT_PATH = SAVED_MODEL_DIR / "soh_model.keras"
LOSS_PLOT_PATH = MODELS_DIR / "training_curves.png"

# Fixed seed for 100% deterministic reproducibility
SEED = 42
np.random.seed(SEED)
tf.random.set_seed(SEED)


def build_tflm_compatible_model(input_dim: int = 3) -> keras.Model:
    """
    Constructs an ultra-lightweight regression model using exclusively Dense + ReLU operators.
    Total weights < 1 KB; RAM footprint < 5 KB in SRAM.
    """
    model = keras.Sequential([
        layers.Input(shape=(input_dim,), name="physical_features_input"),
        
        # Hidden Layer 1
        layers.Dense(
            16,
            activation="relu",
            kernel_regularizer=regularizers.l2(1e-4),
            name="dense_1"
        ),
        
        # Hidden Layer 2
        layers.Dense(
            8,
            activation="relu",
            kernel_regularizer=regularizers.l2(1e-4),
            name="dense_2"
        ),
        
        # Scalar Fractional SoH Output (e.g. 0.85 = 85% SoH)
        layers.Dense(
            1,
            activation="linear",
            name="soh_fraction_output"
        )
    ], name="TinyML_Battery_SoH")

    return model


def run_model_training():
    print("=" * 65)
    print("RUNNING STEP ML-6: ROBUST MODEL TRAINING & CONVERGENCE")
    print("=" * 65)

    if not SCALED_DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {SCALED_DATA_PATH}. Run Step ML-5 first.")

    SAVED_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load Normalized Datasets
    data = np.load(SCALED_DATA_PATH)
    X_train, y_train = data["X_train"], data["y_train"]
    X_val, y_val = data["X_val"], data["y_val"]
    y_val_pct = data["y_val_pct"]
    X_test, y_test_pct = data["X_test"], data["y_test_pct"]

    print(f"Loaded Tensors:")
    print(f"  Training Set:   {X_train.shape[0]} samples, {X_train.shape[1]} features")
    print(f"  Validation Set: {X_val.shape[0]} samples")
    print(f"  Holdout Test:   {X_test.shape[0]} samples (Cell B0018)")

    # 2. Build TFLM-Compatible Model
    model = build_tflm_compatible_model(input_dim=X_train.shape[1])
    model.summary()

    total_params = model.count_params()
    print(f"\nTotal Model Parameters: {total_params}")
    assert total_params < 1000, f"Model too large: {total_params} parameters."
    print(" [PASS] Model complexity is within micro-RAM budget (< 1,000 parameters).")

    # 3. Compile Optimizer & Loss
    optimizer = keras.optimizers.legacy.Adam(learning_rate=0.005)
    model.compile(
        optimizer=optimizer,
        loss="mse",
        metrics=["mae"]
    )

    # 4. Training Callbacks
    early_stopping = callbacks.EarlyStopping(
        monitor="val_loss",
        patience=25,
        restore_best_weights=True,
        verbose=1
    )
    lr_scheduler = callbacks.ReduceLROnPlateau(
        monitor="val_loss",
        factor=0.5,
        patience=10,
        min_lr=1e-5,
        verbose=1
    )

    # 5. Fit Model
    print("\nTraining neural network on Apple Silicon...")
    start_time = time.time()
    history = model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val),
        epochs=150,
        batch_size=16,
        callbacks=[early_stopping, lr_scheduler],
        verbose=1
    )
    elapsed_time = time.time() - start_time
    print(f" [PASS] Training completed in {elapsed_time:.2f} seconds.")

    # 6. Save Trained Keras Model
    model.save(MODEL_OUTPUT_PATH)
    assert MODEL_OUTPUT_PATH.exists(), f"ERROR: Failed to save model: {MODEL_OUTPUT_PATH}"
    print(f" [OUTPUT] Trained model saved to: {MODEL_OUTPUT_PATH}")

    # 7. Evaluate on Validation Set in Percentage Units
    val_preds_norm = model.predict(X_val, verbose=0).flatten()
    val_preds_pct = val_preds_norm * 100.0
    val_mae_pct = float(np.mean(np.abs(val_preds_pct - y_val_pct)))
    val_rmse_pct = float(np.sqrt(np.mean((val_preds_pct - y_val_pct) ** 2)))

    print(f"\n" + "=" * 65)
    print(f"FINAL VALIDATION PERFORMANCE:")
    print(f"  Validation MAE:  {val_mae_pct:.2f}% SoH")
    print(f"  Validation RMSE: {val_rmse_pct:.2f}% SoH")
    print("=" * 65)

    # Capstone Requirement: MAE must be < 4.0%
    assert val_mae_pct < 4.0, f"ERROR: Validation MAE {val_mae_pct:.2f}% exceeds 4.0% tolerance."
    print(" [PASS] Model satisfies capstone performance criteria (MAE < 4.0%).")

    # 8. Plot Training Curves
    plt.figure(figsize=(10, 4.5))

    # Loss subplot
    plt.subplot(1, 2, 1)
    plt.plot(history.history["loss"], label="Train Loss (MSE)", color="#1f77b4", linewidth=1.8)
    plt.plot(history.history["val_loss"], label="Val Loss (MSE)", color="#ff7f0e", linewidth=1.8)
    plt.title("Convergence Loss (MSE)")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()

    # MAE subplot (scaled to % SoH)
    plt.subplot(1, 2, 2)
    train_mae_pct = [m * 100.0 for m in history.history["mae"]]
    val_mae_history_pct = [m * 100.0 for m in history.history["val_mae"]]
    plt.plot(train_mae_pct, label="Train MAE (% SoH)", color="#2ca02c", linewidth=1.8)
    plt.plot(val_mae_history_pct, label="Val MAE (% SoH)", color="#d62728", linewidth=1.8)
    plt.title("State-of-Health Error (% SoH)")
    plt.xlabel("Epoch")
    plt.ylabel("MAE (%)")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()

    plt.tight_layout()
    plt.savefig(LOSS_PLOT_PATH, dpi=200)
    plt.close()
    assert LOSS_PLOT_PATH.exists(), "ERROR: Failed to save loss plot."
    print(f" [OUTPUT] Training curves plot saved to: {LOSS_PLOT_PATH}")

    print("\n" + "=" * 65)
    print("ALL ML-6 SANITY CHECKS PASSED: Ready for Step ML-7 benchmarking.")
    print("=" * 65)


if __name__ == "__main__":
    run_model_training()