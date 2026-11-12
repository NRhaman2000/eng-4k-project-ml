# Fault-Tolerant Active BMS: Embedded TinyML State-of-Health (SoH) Inference Pipeline

An ultra-lightweight, deterministic machine learning inference pipeline designed for deployment on the ESP32-S3-WROOM-1 microcontroller (dual-core Xtensa LX7) on the project's control board (Board 2). This subsystem estimates the State-of-Health (SoH) of each cell in a 4-cell series (4S) lithium-ion pack (~14.8 V nominal). It is trained on the NASA Ames Prognostics Center of Excellence (PCoE) battery aging dataset.

---

## 1. Project Overview & System Architecture

This repository hosts the offline machine learning development track (Steps ML-1 through ML-9) of the capstone project. The pipeline ingests raw laboratory cycling logs, extracts low-compute physical degradation features, trains a microcontroller-compatible Multi-Layer Perceptron (MLP), applies full integer post-training quantization (INT8), and exports the model as memory-aligned C header files for on-device execution with TensorFlow Lite for Microcontrollers (TFLM). Model and feature choices are made with leave-one-cell-out cross-validation; see [`CHANGES.md`](CHANGES.md) for what changed from the first version and why.

### Performance & Hardware Footprint Scorecard

| Metric | Target Specification | Achieved Result | Status |
| --- | --- | --- | --- |
| **Model Parameters** | $< 1,000$ weights | **193 parameters** | **PASSED** |
| **Compiled Flash Footprint** | $< 10.0\text{ KB}$ | **2,704 bytes (2.64 KB)** | **PASSED** |
| **Runtime SRAM Tensor Arena** | $< 10.0\text{ KB}$ | **$\approx 3.5\text{ KB}$ (estimated)** | Confirm on target (ML-10) |
| **Leave-one-cell-out CV MAE (B0005/6/7)** | $< 4.00\%\text{ SoH}$ | **2.02% mean, 2.27% worst cell** | **PASSED** |
| **Holdout Test MAE (Unseen Cell B0018)** | $< 4.00\%\text{ SoH}$ | **2.42% (exported model); 2.70 ± 0.66% over 10 seeds** | **PASSED** |
| **Holdout Max Error (B0018)** | reference | 4.05% SoH | Reported |
| **Linear baseline on B0018** | reference | 2.30% MAE | Reported |
| **Quantization Parity Drift (Float32 vs. INT8)** | $< 0.50\%\text{ SoH}$ | **0.124% SoH** (INT8 test MAE 2.36%) | **PASSED** |
| **Target Controller** | Embedded MCU, TFLM-compatible | ESP32-S3-WROOM-1 (TFLM + ESP-NN) | On-target profiling scheduled (ML-10) |

> **Controller note:** the STM32G474RE was evaluated as an alternative; the ESP32-S3-WROOM-1 was selected for Board 2 (see Trade Study C in Progress Report 1).

> **Limitations:** the model is trained on only 3 laboratory cells under a fixed 2 A constant-current discharge at about 24 °C. On B0018 it over-predicts SoH by a fairly steady 2 to 4%, which points to a cell-to-cell offset that more training cells would reduce. The features are only valid when measured under the same test conditions (see Section 2).

---

## 2. Physics-Informed Feature Engineering

To avoid storing thousands of raw ADC samples on the microcontroller, the model uses **2 low-compute physical features**, measured during a diagnostic discharge: rest, then about 2 A constant current for at least 1000 s. Time is measured from load-on, the first sample with $\vert{}I\vert{} \ge 1.5\text{ A}$.

1. **Partial Discharge Window Sag ($\Delta V_{\text{window}}$):** $V(100\text{ s}) - V(1000\text{ s})$
   Captures electrochemical depletion and polarization sag across 900 s of constant discharge.
2. **Temperature Rise ($\Delta T$):** $T(1000\text{ s}) - T(0\text{ s})$
   Captures Joule self-heating ($I^2 R$) during discharge. Using a difference cancels out fixed temperature-sensor offsets.

**Feature selection:** ML-4 also computes the ohmic voltage drop ($V_{\text{OCV}} - V_{\text{loaded}}$ at load-on), discharge slope, mean temperature and mean current. The ohmic drop was left out of the model for two reasons. Leave-one-cell-out cross-validation gave a lower worst-cell error without it (2.27% vs. 3.14%). Also, the NASA logs sample only every 10 to 19 s around load-on, so the recorded "ohmic" drop includes polarization and would not match measurements from a faster-sampling microcontroller.

---

## 3. Repository Directory Structure

```text
eng-4k-project-ml/
├── data/
│   ├── raw/                        # Extracted NASA PCoE MAT files (B0005, B0006, B0007, B0018)
│   └── processed/                  # Structured NumPy archives (.npz) and CSV feature matrices
├── models/
│   ├── saved/                      # Native Keras floating-point model (soh_model.keras)
│   ├── tflite/                     # Full INT8 quantized FlatBuffer (soh_model_int8.tflite)
│   ├── c_headers/                  # Microcontroller deployment headers:
│   │   ├── scaling_params.h        # Feature normalization constants
│   │   ├── quantization_params.h   # INT8 quantize / dequantize routines
│   │   └── model_data.h            # 4-byte aligned model byte array
│   ├── scaling_params.json         # Normalization metadata
│   ├── quantization_params.json    # Affine scale & zero-point parameters
│   ├── cv_results.csv              # Leave-one-cell-out cross-validation results
│   ├── evaluation_metrics.csv      # Holdout scorecard (incl. seed spread and linear baseline)
│   ├── training_curves.png         # Training loss / MAE curves
│   ├── test_benchmark_b0018.png    # Ground truth vs. predicted degradation curve
│   └── quantization_parity.png     # Float32 vs. INT8 parity comparison
├── src/
│   ├── config.py                   # Shared settings: features, cells, epochs, seeds
│   ├── download_data.py            # ML-2: Dataset ingestion & integrity gate
│   ├── parse_raw_data.py           # ML-3: Discharge cycle isolation & SoH labelling
│   ├── extract_features.py         # ML-4: Event-synchronized physical feature extraction
│   ├── prepare_dataset.py          # ML-5: Cell-wise partitioning & standard scaling
│   ├── cross_validate.py           # ML-5b: Leave-one-cell-out model & feature selection
│   ├── train_model.py              # ML-6: TFLM-compatible neural network training
│   ├── evaluate_model.py           # ML-7: Unseen test cell benchmarking
│   ├── quantize_model.py           # ML-8: Post-training INT8 quantization & verification
│   └── export_c_header.py          # ML-9: Static C array export & SHA-256 parity verification
├── dashboard/                      # Telemetry dashboard (see the last section)
├── CHANGES.md                      # What changed in the improved pipeline, with before/after results
├── requirements.txt                # Locked dependencies (Python 3.11, TF 2.15, NumPy 1.26)
├── verify_env.py                   # Step ML-1 environment sanity checker
├── .gitignore                      # Git exclusion rules for large datasets and binaries
└── README.md
```

---

## 4. Pipeline Execution: Step ML-1 to ML-9

All scripts include assertion gates that halt execution if data corruption, numerical instability, or metric threshold violations occur.

### Step ML-1: Environment Verification

Validates the Python runtime, ABI-compatible NumPy constraints, and directory layout.

```bash
python verify_env.py
```

### Step ML-2: Dataset Ingestion

Downloads the official NASA Ames PCoE Battery Aging Dataset archive over HTTPS, extracts the target cells (B0005, B0006, B0007, B0018), and checks MATLAB struct integrity.

```bash
python src/download_data.py
```

### Step ML-3: Cycle Isolation & Ground-Truth Labelling

Filters out charge and impedance tests, extracts 636 constant-current discharge cycles, and computes ground-truth SoH labels from the rated cell capacity ($C_{\text{rated}} = 2.0\text{ Ah}$).

```bash
python src/parse_raw_data.py
```

### Step ML-4: Feature Extraction

Synchronizes each cycle to the moment the load engages ($\vert{}I\vert{} \ge 1.5\text{ A}$) and computes the candidate degradation features. Raises an error if a discharge is shorter than the 1000 s window.

```bash
python src/extract_features.py
```

### Step ML-5: Normalization & Cell-wise Partitioning

Splits by physical cell. All 504 cycles of B0005, B0006 and B0007 are used for training; cell B0018 (132 cycles) is the untouched test cell. The scaler is fitted on the training cells only. Exports `models/c_headers/scaling_params.h`.

```bash
python src/prepare_dataset.py
```

### Step ML-5b: Leave-One-Cell-Out Cross-Validation

Compares 8 configurations (linear regression and MLP, each with 4 feature sets) by training on two training cells and testing on the third, over several seeds. The configuration with the lowest worst-cell MAE is selected. B0018 is never used here. Writes `models/cv_results.csv`.

```bash
python src/cross_validate.py
```

### Step ML-6: Model Architecture & Training

Trains an ultra-compact MLP (`Input(2)` $\to$ `Dense(16, ReLU)` $\to$ `Dense(8, ReLU)` $\to$ `Dense(1, Linear)`) with L2 regularization for a fixed 150 epochs (chosen by cross-validation) on all three training cells. TensorFlow op determinism is enabled, so results are reproducible across machines.

```bash
python src/train_model.py
```

### Step ML-7: Unseen Cell Benchmarking

Evaluates the exported model on cell B0018, and also reports the MAE spread over 10 training seeds and a linear baseline trained on the same data.

```bash
python src/evaluate_model.py
```

### Step ML-8: Post-Training INT8 Quantization

Applies full integer quantization to inputs, weights and activations, calibrated on the training data. Checks that quantization drift stays below $0.50\%\text{ SoH}$ and reports any inputs that saturate the INT8 range. Exports `models/c_headers/quantization_params.h`.

```bash
python src/quantize_model.py
```

### Step ML-9: Static C Header Export

Converts the `.tflite` flatbuffer into an aligned C byte array (`models/c_headers/model_data.h`) with 4-byte alignment (`DATA_ALIGN(4)`), as TFLM requires for the model buffer. The arrays are `static const`, so the header can be included safely. Re-verifies SHA-256 bit parity and runtime deserialization.

```bash
python src/export_c_header.py
```

---

## 5. How to Reproduce from Scratch

### Prerequisites

* macOS (Apple Silicon supported) or Linux
* Python 3.11.9
* Git

### Installation & Execution

```bash
# 1. Clone the repository
git clone https://github.com/NRhaman2000/eng-4k-project-ml.git
cd eng-4k-project-ml

# 2. Create a Python 3.11 virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install locked dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Run the full pipeline in order
python verify_env.py
python src/download_data.py
python src/parse_raw_data.py
python src/extract_features.py
python src/prepare_dataset.py
python src/cross_validate.py
python src/train_model.py
python src/evaluate_model.py
python src/quantize_model.py
python src/export_c_header.py
```

---

## 6. Next Steps: Hardware Deployment (Step ML-10, not started)

* **Target hardware:** ESP32-S3-DevKitC-1 for early testing, then the ESP32-S3-WROOM-1 on Board 2.
* **Task:** integrate the headers in `models/c_headers/` into an ESP-IDF project with `esp-tflite-micro`, then measure inference latency, the real tensor arena size, and CPU load on the diagnostics core.
* **Measurement requirement:** the firmware must reproduce the diagnostic discharge the model was trained on (rest, then about 2 A constant current for at least 1000 s, per cell) to produce valid inputs.
* **Safety boundary:** the SoH estimate is advisory only. It will not be used in any protection or shutdown decision.

---

## Telemetry Dashboard (Software Engineering)

The `dashboard/` folder contains the receive-only host software for the BMS testbed: a Python FastAPI backend that ingests telemetry, validates it and logs it to SQLite, and a React web dashboard that shows live cell voltages, temperatures, pack voltage and current, balancing, fault and isolation state, history, and CSV export. The dashboard only monitors. It sends no commands to the MCU, and all protection decisions remain in the ESP32-S3 firmware.

- **Setup, architecture, usage and testing:** see [`dashboard/README.md`](dashboard/README.md).
- **Current status:** the dashboard runs on synthetic (mock) telemetry and supports a provisional serial interface (JSON frames over UART at 115,200 baud, see [`dashboard/tools/README.md`](dashboard/tools/README.md)), which has been tested only with a pseudo-terminal loopback and synthetic data.
- **Physical ESP32-S3 integration has not yet been verified.** The serial packet format is still provisional until it is confirmed with the firmware team.
