# Fault-Tolerant Active BMS: Embedded TinyML State-of-Health (SoH) Inference Pipeline

An ultra-lightweight, deterministic Machine Learning inference pipeline designed for bare-metal microcontroller deployment (ARM Cortex-M4 / Xtensa LX7). This subsystem monitors battery degradation and estimates State-of-Health (SoH) on a 4-cell series (4S) Lithium-ion battery pack (~14.8V nominal) using the NASA Ames Prognostics Center of Excellence (PCoE) battery aging cohort.

---

## 1. Project Overview & System Architecture

This repository hosts the offline machine learning development track (Steps ML-1 through ML-9) of the capstone project. The pipeline ingests raw laboratory cycling logs, extracts low-compute physical degradation features, trains a microcontroller-compatible Multi-Layer Perceptron (MLP), applies full integer post-training quantization (INT8), and compiles the model into memory-aligned C header files for on-device execution without an operating system.

### Performance & Hardware Footprint Scorecard

| Metric | Target Specification | Achieved Result | Status |
| --- | --- | --- | --- |
| **Model Parameters** | $< 1,000$ weights | **209 parameters** | **PASSED** |
| **Compiled Flash Footprint** | $< 10.0\text{ KB}$ | **2,720 bytes (2.66 KB)** | **PASSED** |
| **Runtime SRAM Tensor Arena** | $< 10.0\text{ KB}$ | **$\approx 3.5\text{ KB}$** | **PASSED** |
| **Holdout Test MAE (Unseen Cell B0018)** | $< 4.00\%\text{ SoH}$ | **$3.69\%\text{ SoH}$** | **PASSED** |
| **Quantization Parity Drift (Float32 vs. INT8)** | $< 0.50\%\text{ SoH}$ | **$0.306\%\text{ SoH}$** | **PASSED** |
| **Target Controller Compatibility** | Ultra-low power MCU | STM32G474RE / ESP32-S3 | **PASSED**<br> |

---

## 2. Physics-Informed Feature Engineering

To avoid consuming microcontroller memory with thousands of raw ADC time-series buffers, the inference engine extracts **3 low-compute physical features** evaluated strictly from a partial-discharge evaluation window ($t \in [0\text{ s}, 1000\text{ s}]$):

1. **Ohmic Voltage Drop ($\Delta V_{\text{ohmic}}$):** $V_{\text{OCV}} - V_{\text{loaded}}$
Evaluated at the onset of load engagement ($\vert{}I\vert{} \ge 1.5\text{ A}$). Directly tracks internal DC equivalent series resistance ($R_{\text{int}} \approx 105\text{ m}\Omega$).
2. **Partial Discharge Window Sag ($\Delta V_{\text{window}}$):** $V(100\text{ s}) - V(1000\text{ s})$
Evaluates electrochemical depletion and polarization sag across 900 seconds of constant discharge.
3. **Internal Temperature Rise ($\Delta T$):** $T(1000\text{ s}) - T(0\text{ s})$
Measures Joulean self-heating ($I^2 R$) during active discharge, mitigating ambient temperature sensor offsets.

---

## 3. Repository Directory Structure

```text
eng-4k-project-ml/
├── data/
│   ├── raw/                        # Extracted NASA PCoE MAT files (B0005, B0006, B0007, B0018)
│   └── processed/                  # Structured NumPy archives (.npz) and CSV feature matrices
├── models/
│   ├── saved/                      # Native Keras floating-point model (soh_model.keras)
│   ├── tflite/                     # Full INT8 Quantized FlatBuffer (soh_model_int8.tflite)
│   ├── c_headers/                  # Microcontroller deployment suite:
│   │   ├── scaling_params.h        # C float inline ADC feature normalization
│   │   ├── quantization_params.h   # C inline Affine INT8 quantization routines
│   │   └── model_data.h            # 4-byte memory-aligned binary model byte array
│   ├── scaling_params.json         # Normalization metadata
│   ├── quantization_params.json    # Affine scale & zero-point parameters
│   ├── evaluation_metrics.csv      # Unseen battery holdout scorecard
│   ├── training_curves.png         # Convergence MSE/MAE loss plots
│   ├── test_benchmark_b0018.png    # Ground truth vs. predicted degradation curve
│   └── quantization_parity.png     # Float32 vs. INT8 parity comparison
├── src/
│   ├── download_data.py            # ML-2: Automated dataset ingestion & integrity gate
│   ├── parse_raw_data.py           # ML-3: Discharge cycle isolation & SoH labelling
│   ├── extract_features.py         # ML-4: Event-synchronized physical feature extraction
│   ├── prepare_dataset.py          # ML-5: Cell-wise partitioning & standard scaling
│   ├── train_model.py              # ML-6: TFLM-compatible neural network training
│   ├── evaluate_model.py           # ML-7: Unseen test battery holdout benchmarking
│   ├── quantize_model.py           # ML-8: Post-training INT8 quantization & verification
│   └── export_c_header.py          # ML-9: Static C array export & SHA-256 parity verification
├── requirements.txt                # Locked dependencies (Python 3.11, TF 2.15, NumPy 1.26)
├── verify_env.py                   # Step ML-1 environment sanity checker
├── .gitignore                      # Git exclusion rules for large datasets and binaries
└── README.md

```

---

## 4. Pipeline Execution: Step ML-1 to ML-9

All scripts include automated assertion gates that halt execution if data corruption, numerical instability, or metric threshold violations occur.

### Step ML-1: Environment Verification

Validates the Python runtime, ABI-compatible NumPy constraints, and directory architecture.

```bash
python verify_env.py

```

### Step ML-2: Dataset Ingestion

Streams the official NASA Ames PCoE Battery Aging Dataset archive over HTTPS, extracts target cells (B0005, B0006, B0007, B0018), and asserts MATLAB struct integrity.

```bash
python src/download_data.py

```

### Step ML-3: Cycle Isolation & Ground-Truth Labelling

Filters out charge and impedance tests, extracts 636 constant-current discharge cycles, and compiles ground-truth State-of-Health labels based on nominal rated cell capacity ($C_{\text{rated}} = 2.0\text{ Ah}$).

```bash
python src/parse_raw_data.py

```

### Step ML-4: Feature Extraction

Synchronizes time vectors to the exact moment the load engages ($\vert{}I\vert{} \ge 1.5\text{ A}$) and computes the 3 physical degradation features.

```bash
python src/extract_features.py

```

### Step ML-5: Dataset Normalization & Group Partitioning

Splits data cleanly without temporal leakage. Group 1 cells (B0005, B0006, B0007) are split 80/20 for training/validation (504 cycles total), while Cell B0018 (132 cycles) is isolated as an untouched test battery. Exports `models/c_headers/scaling_params.h`.

```bash
python src/prepare_dataset.py

```

### Step ML-6: Model Architecture & Training

Trains an ultra-compact MLP (`Input(3)` $\to$ `Dense(16, ReLU)` $\to$ `Dense(8, ReLU)` $\to$ `Dense(1, Linear)`) with L2 regularization and Early Stopping.

```bash
python src/train_model.py

```

### Step ML-7: Unseen Cell Benchmarking

Performs zero-shot validation against Cell B0018, measuring generalization on an independent physical cell.

```bash
python src/evaluate_model.py

```

### Step ML-8: Post-Training INT8 Quantization

Applies full integer quantization to input tensors, weights, and activations using representative calibration data. Enforces an assertion check that quantization drift does not exceed $0.50\%\text{ SoH}$. Exports `models/c_headers/quantization_params.h`.

```bash
python src/quantize_model.py

```

### Step ML-9: Static C Header Export

Converts the `.tflite` flatbuffer into an aligned C byte array header (`models/c_headers/model_data.h`) with 4-byte boundary alignment (`DATA_ALIGN(4)`) to prevent bus fault exceptions on ARM Cortex-M hardware. Re-verifies SHA-256 bit parity and runtime deserialization.

```bash
python src/export_c_header.py

```

---

## 5. Firmware Integration Guide (C/C++)

To run inference on an embedded target (such as an STM32 Nucleo-G474RE or ESP32-S3), copy the contents of `models/c_headers/` into your microcontroller project's include path.

```c
#include "scaling_params.h"
#include "quantization_params.h"
#include "model_data.h"
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_interpreter.h"

// 1. Allocate Tensor Arena in internal SRAM (< 4 KB)
constexpr int kTensorArenaSize = 4096;
uint8_t tensor_arena[kTensorArenaSize];

void run_battery_soh_inference(float v_ohmic, float v_sag, float temp_rise) {
    // 2. Normalize raw physical ADC inputs using Step ML-5 constants
    float raw_inputs[NUM_FEATURES] = { v_ohmic, v_sag, temp_rise };
    float normalized_inputs[NUM_FEATURES];
    normalize_features(raw_inputs, normalized_inputs);

    // 3. Quantize float features to signed INT8
    int8_t quantized_inputs[NUM_FEATURES];
    for (int i = 0; i < NUM_FEATURES; i++) {
        quantized_inputs[i] = quantize_input(normalized_inputs[i]);
    }

    // 4. Load input tensor into TFLM interpreter
    TfLiteTensor* input_tensor = interpreter->input(0);
    for (int i = 0; i < NUM_FEATURES; i++) {
        input_tensor->data.int8[i] = quantized_inputs[i];
    }

    // 5. Execute on-device neural network inference
    TfLiteStatus invoke_status = interpreter->Invoke();
    if (invoke_status != kTfLiteOk) {
        return; // Handle execution error
    }

    // 6. Dequantize model output back to physical SoH (%)
    int8_t raw_model_output = interpreter->output(0)->data.int8[0];
    float estimated_soh_percent = dequantize_output(raw_model_output);
}

```

---

## 6. How to Reproduce from Scratch

### Prerequisites

* macOS (Apple Silicon M-Series supported) or Linux
* Python 3.11.9
* Git

### Installation & Execution

```bash
# 1. Clone the repository
git clone <YOUR_GITHUB_REPO_URL>
cd eng-4k-project-ml

# 2. Configure Python 3.11 Virtual Environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install Locked Dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Execute Full Pipeline in Sequence
python verify_env.py
python src/download_data.py
python src/parse_raw_data.py
python src/extract_features.py
python src/prepare_dataset.py
python src/train_model.py
python src/evaluate_model.py
python src/quantize_model.py
python src/export_c_header.py

```

---

## 7. Next Steps: Hardware Deployment (Step ML-10)

* **Target Hardware:** STM32G474RE Nucleo / ESP32-S3 DevKit.


* **Task:** Integrate `models/c_headers/` into STM32CubeIDE / ESP-IDF, initialize the hardware DWT cycle counter, and profile exact sub-millisecond execution time and dynamic memory allocation on the physical board.

---

## Telemetry Dashboard (Software Engineering)

The `dashboard/` folder contains the receive-only host software for the BMS testbed: a Python FastAPI backend that ingests telemetry, validates it and logs it to SQLite, and a React web dashboard that shows live cell voltages, temperatures, pack voltage and current, balancing, fault and isolation state, history, and CSV export. The dashboard only monitors. It sends no commands to the MCU, and all protection decisions remain in the STM32 firmware.

- **Setup, architecture, usage and testing:** see [`dashboard/README.md`](dashboard/README.md).
- **Current status:** the dashboard runs on synthetic (mock) telemetry and supports a provisional serial interface (JSON frames over UART at 115,200 baud, see [`dashboard/tools/README.md`](dashboard/tools/README.md)), which has been tested only with a pseudo-terminal loopback and synthetic data.
- **Physical STM32 integration has not yet been verified.** The serial packet format is still provisional until it is confirmed with the firmware team.
