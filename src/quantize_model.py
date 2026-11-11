"""
Step ML-8: Post-Training Quantization (INT8) & TFLite Conversion
Project: eng-4k-project-ml
Converts Keras model to full INT8 TFLite, extracts affine quantization parameters,
exports C header scaling constants, and asserts Float32 vs INT8 numerical parity.
"""

import os
import sys
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import tensorflow as tf
from tensorflow import keras

PROCESSED_DIR = Path("data/processed")
MODELS_DIR = Path("models")
SAVED_MODEL_PATH = MODELS_DIR / "saved" / "soh_model.keras"
TFLITE_DIR = MODELS_DIR / "tflite"
TFLITE_PATH = TFLITE_DIR / "soh_model_int8.tflite"
C_HEADERS_DIR = MODELS_DIR / "c_headers"
QUANT_HEADER = C_HEADERS_DIR / "quantization_params.h"
QUANT_JSON = MODELS_DIR / "quantization_params.json"
PARITY_PLOT_PATH = MODELS_DIR / "quantization_parity.png"
SCALED_DATA_PATH = PROCESSED_DIR / "dataset_scaled.npz"


def run_quantization():
    print("=" * 65)
    print("RUNNING STEP ML-8: POST-TRAINING INT8 QUANTIZATION & TFLITE EXPORT")
    print("=" * 65)

    if not SAVED_MODEL_PATH.exists():
        raise FileNotFoundError(f"Missing {SAVED_MODEL_PATH}. Run Step ML-6 first.")
    if not SCALED_DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {SCALED_DATA_PATH}. Run Step ML-5 first.")

    TFLITE_DIR.mkdir(parents=True, exist_ok=True)
    C_HEADERS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load Data & Keras Model
    data = np.load(SCALED_DATA_PATH)
    X_train = data["X_train"]
    X_test = data["X_test"]
    y_test_pct = data["y_test_pct"]

    model = keras.models.load_model(SAVED_MODEL_PATH)

    # 2. Define Representative Calibration Dataset Generator
    def representative_dataset_gen():
        # Samples from the training set to establish dynamic activation ranges
        for i in range(len(X_train)):
            sample = np.expand_dims(X_train[i], axis=0).astype(np.float32)
            yield [sample]

    # 3. Configure TFLite Converter for Full INT8 Quantization
    print("Configuring TFLite Converter for Full INT8 Quantization...")
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_dataset_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8

    # Convert to TFLite flatbuffer
    tflite_model_bytes = converter.convert()

    # 4. Save Quantized Model
    with open(TFLITE_PATH, "wb") as f_tflite:
        f_tflite.write(tflite_model_bytes)
    assert TFLITE_PATH.exists(), f"ERROR: Failed to save {TFLITE_PATH}"

    tflite_size_bytes = len(tflite_model_bytes)
    print(f" [PASS] Quantization complete: {TFLITE_PATH}")
    print(f"        Flash Size: {tflite_size_bytes} bytes ({tflite_size_bytes / 1024:.2f} KB)")
    assert tflite_size_bytes < 4096, f"ERROR: Model is larger than 4KB ({tflite_size_bytes} bytes)."
    print(" [PASS] Model size easily satisfies microcontroller flash budget (< 4 KB).")

    # 5. Extract Quantization Scale and Zero-Point
    interpreter = tf.lite.Interpreter(model_content=tflite_model_bytes)
    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]

    in_scale, in_zero_point = input_details["quantization"]
    out_scale, out_zero_point = output_details["quantization"]

    print("\nExtracted Affine Quantization Parameters:")
    print(f"  Input  Tensor: Scale = {in_scale:.8f}, Zero-Point = {in_zero_point}")
    print(f"  Output Tensor: Scale = {out_scale:.8f}, Zero-Point = {out_zero_point}")

    # 6. Export Parameters to JSON
    quant_dict = {
        "input_scale": float(in_scale),
        "input_zero_point": int(in_zero_point),
        "output_scale": float(out_scale),
        "output_zero_point": int(out_zero_point),
        "target_multiplier": 100.0
    }
    with open(QUANT_JSON, "w") as f_json:
        json.dump(quant_dict, f_json, indent=4)
    print(f" [OUTPUT] Quantization metadata saved to: {QUANT_JSON}")

    # 7. Export C Header for Microcontroller Firmware
    with open(QUANT_HEADER, "w") as f_hdr:
        f_hdr.write("/*\n")
        f_hdr.write(" * Auto-generated affine quantization parameters for on-device INT8 inference\n")
        f_hdr.write(" * Project: eng-4k-project-ml\n")
        f_hdr.write(" */\n\n")
        f_hdr.write("#ifndef QUANTIZATION_PARAMS_H\n")
        f_hdr.write("#define QUANTIZATION_PARAMS_H\n\n")
        f_hdr.write("#include <stdint.h>\n")
        f_hdr.write("#include <math.h>\n\n")
        f_hdr.write(f"#define INPUT_SCALE       {in_scale:.8f}f\n")
        f_hdr.write(f"#define INPUT_ZERO_POINT   {int(in_zero_point)}\n")
        f_hdr.write(f"#define OUTPUT_SCALE      {out_scale:.8f}f\n")
        f_hdr.write(f"#define OUTPUT_ZERO_POINT  {int(out_zero_point)}\n\n")
        
        f_hdr.write("/* Quantizes a normalized float feature into signed INT8 for the neural network */\n")
        f_hdr.write("static inline int8_t quantize_input(float norm_val) {\n")
        f_hdr.write("    int32_t q = (int32_t)roundf(norm_val / INPUT_SCALE) + INPUT_ZERO_POINT;\n")
        f_hdr.write("    if (q < -128) q = -128;\n")
        f_hdr.write("    if (q > 127)  q = 127;\n")
        f_hdr.write("    return (int8_t)q;\n")
        f_hdr.write("}\n\n")

        f_hdr.write("/* Dequantizes the neural network's INT8 output back to physical SoH (%) */\n")
        f_hdr.write("static inline float dequantize_output(int8_t q_out) {\n")
        f_hdr.write("    float norm_soh = ((float)q_out - (float)OUTPUT_ZERO_POINT) * OUTPUT_SCALE;\n")
        f_hdr.write("    return norm_soh * 100.0f; /* Convert fraction back to percentage */\n")
        f_hdr.write("}\n\n")
        f_hdr.write("#endif /* QUANTIZATION_PARAMS_H */\n")

    print(f" [OUTPUT] C header for integer conversion saved: {QUANT_HEADER}")

    # 8. Rigorous Numerical Parity Check (Float32 vs INT8)
    print("\nRunning Numerical Parity Verification on Test Cohort (Cell B0018)...")
    
    # Float32 Predictions
    preds_float_norm = model.predict(X_test, verbose=0).flatten()
    preds_float_pct = preds_float_norm * 100.0

    # INT8 TFLite Predictions
    input_index = input_details["index"]
    output_index = output_details["index"]
    preds_int8_pct = []

    for i in range(len(X_test)):
        # Quantize float input to int8
        sample_norm = X_test[i]
        # Clip BEFORE casting: casting first wraps out-of-range values (200 -> -56).
        sample_int8 = np.clip(np.round(sample_norm / in_scale + in_zero_point), -128, 127).astype(np.int8)
        sample_int8 = np.expand_dims(sample_int8, axis=0)

        interpreter.set_tensor(input_index, sample_int8)
        interpreter.invoke()
        out_int8 = interpreter.get_tensor(output_index)[0, 0]

        # Dequantize int8 output back to percentage SoH
        soh_pred_norm = (float(out_int8) - out_zero_point) * out_scale
        soh_pred_pct = soh_pred_norm * 100.0
        preds_int8_pct.append(soh_pred_pct)

    preds_int8_pct = np.array(preds_int8_pct, dtype=np.float32)
    q_lo, q_hi = (-128 - in_zero_point) * in_scale, (127 - in_zero_point) * in_scale
    n_sat = int(((X_test < q_lo) | (X_test > q_hi)).any(axis=1).sum())
    print(f"  Test samples saturating the INT8 input range: {n_sat}/{len(X_test)}")

    # Compute Quantization Discrepancy
    quant_error = np.abs(preds_float_pct - preds_int8_pct)
    mean_quant_error = float(np.mean(quant_error))
    max_quant_error = float(np.max(quant_error))
    
    # Compute INT8 Model Test MAE on Ground Truth
    int8_test_mae = float(np.mean(np.abs(preds_int8_pct - y_test_pct)))

    print("=" * 65)
    print("QUANTIZATION PARITY & BENCHMARK REPORT:")
    print("=" * 65)
    print(f"  Float32 Test MAE:          {np.mean(np.abs(preds_float_pct - y_test_pct)):.2f}% SoH")
    print(f"  INT8 Quantized Test MAE:   {int8_test_mae:.2f}% SoH")
    print(f"  Mean Quantization Drift:   {mean_quant_error:.3f}% SoH")
    print(f"  Max Quantization Drift:    {max_quant_error:.3f}% SoH")
    print("=" * 65)

    # Assertion Gates
    assert mean_quant_error < 0.50, f"ERROR: Quantization drift too high ({mean_quant_error:.3f}%)."
    assert int8_test_mae < 4.0, f"ERROR: INT8 model MAE ({int8_test_mae:.2f}%) exceeds 4.0% tolerance."
    print(" [PASS] Quantization drift is minimal (< 0.5% SoH).")
    print(" [PASS] INT8 model maintains capstone performance criteria (MAE < 4.0%).")

    # 9. Plot Float32 vs INT8 Parity Curve
    cycles = data["cycle_test"]
    plt.figure(figsize=(10, 4.8))
    plt.plot(cycles, y_test_pct, label="Ground Truth (Cell B0018)", color="black", linewidth=1.5, alpha=0.7)
    plt.plot(cycles, preds_float_pct, label="Float32 Model", color="#1f77b4", linewidth=2.0)
    plt.plot(cycles, preds_int8_pct, label="INT8 Quantized Model", color="#d62728", linestyle="--", linewidth=1.8)
    plt.title("Float32 vs. INT8 Quantization Parity (Cell B0018)", fontsize=11, fontweight="bold")
    plt.xlabel("Discharge cycle index")
    plt.ylabel("State-of-Health (%)")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    plt.savefig(PARITY_PLOT_PATH, dpi=200)
    plt.close()
    assert PARITY_PLOT_PATH.exists(), f"ERROR: Failed to save {PARITY_PLOT_PATH}"
    print(f" [OUTPUT] Parity comparison chart saved to: {PARITY_PLOT_PATH}")

    print("\n" + "=" * 65)
    print("ALL ML-8 SANITY CHECKS PASSED: Model is ready for C header export.")
    print("=" * 65)


if __name__ == "__main__":
    run_quantization()