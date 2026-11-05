# Fault-Tolerant Active BMS
## Embedded TinyML State-of-Health (SoH) Inference + Real-Time Telemetry Dashboard

This repository contains the software and TinyML development tracks for a **Fault-Tolerant Active Battery Management System (BMS)** for a 4-cell series (4S) lithium-ion pack (~14.8 V nominal).

The project combines:

- **Embedded TinyML SoH estimation** for monitoring battery degradation.
- **Real-time telemetry ingestion** using FastAPI and WebSockets.
- **A React dashboard** for live visualization of cell voltage, temperature, SoH, balancing state, and fault status.
- **SQLite telemetry logging** for historical analysis.
- **Fault simulation** for undervoltage and overcurrent conditions.
- A future **STM32 serial telemetry path** that will replace the current simulator without requiring changes to the frontend.

> **Current development status:** The telemetry dashboard runs end to end on synthetic data (mock simulator, or synthetic frames over a serial loopback). It has not yet been tested with the STM32, and the serial packet format is still provisional. Dashboard SoH values are synthetic and are not yet sourced from the embedded TinyML model. **See [`dashboard/README.md`](dashboard/README.md) for the dashboard's setup, usage and status.**

---

## 1. Project Overview & System Architecture

The repository contains two connected development tracks.

### A. Embedded TinyML Track

The offline machine-learning pipeline ingests raw battery cycling logs, extracts low-compute degradation features, trains a microcontroller-compatible Multi-Layer Perceptron (MLP), applies full-integer INT8 post-training quantization, and exports memory-aligned C headers for deployment on an embedded controller.

### B. Software Telemetry & Dashboard Track

The software track receives BMS telemetry, validates it against a shared data model, streams it to the frontend using WebSockets, stores readings in SQLite, and visualizes both live and historical battery behavior.

### Current software flow

```text
Simulation Mode

simulator.py
    |
    | TelemetryPacket
    v
FastAPI Backend
    |
    +---- WebSocket ----> React Dashboard
    |
    +---- SQLite -------> Historical Telemetry
```

### Planned hardware flow

```text
Sensors + TinyML SoH
        |
        v
      STM32
        |
        | UART / USB Serial
        v
 serial_reader.py
        |
        | TelemetryPacket
        v
 FastAPI Backend
        |
        +---- WebSocket ----> React Dashboard
        |
        +---- SQLite -------> Historical Telemetry
```

The key design decision is that both `simulator.py` and `serial_reader.py` produce the same `TelemetryPacket`. This keeps the frontend independent of the telemetry source and should make the transition from simulation to physical hardware significantly simpler.

---

## 2. TinyML Performance & Hardware Footprint Scorecard

| Metric | Target Specification | Achieved Result | Status |
| --- | --- | --- | --- |
| **Model Parameters** | < 1,000 weights | **209 parameters** | **PASSED** |
| **Compiled Flash Footprint** | < 10.0 KB | **2,720 bytes (2.66 KB)** | **PASSED** |
| **Runtime SRAM Tensor Arena** | < 10.0 KB | **~3.5 KB** | **PASSED** |
| **Holdout Test MAE (Unseen Cell B0018)** | < 4.00% SoH | **3.69% SoH** | **PASSED** |
| **Quantization Parity Drift (Float32 vs. INT8)** | < 0.50% SoH | **0.306% SoH** | **PASSED** |
| **Target Controller Compatibility** | Ultra-low power MCU | STM32G474RE / ESP32-S3 | **PASSED** |

---

## 3. Physics-Informed Feature Engineering

To avoid storing large raw ADC time-series buffers on the microcontroller, the inference engine uses **3 low-compute physical features** from a partial-discharge evaluation window (`t = 0 s` to `1000 s`):

1. **Ohmic Voltage Drop (`ΔV_ohmic`)**  
   `V_OCV - V_loaded`

   Evaluated when load engagement begins (`|I| >= 1.5 A`). This tracks internal DC equivalent series resistance.

2. **Partial Discharge Window Sag (`ΔV_window`)**  
   `V(100 s) - V(1000 s)`

   Measures electrochemical depletion and polarization sag across the discharge window.

3. **Internal Temperature Rise (`ΔT`)**  
   `T(1000 s) - T(0 s)`

   Measures self-heating during active discharge while reducing the effect of ambient temperature offsets.

---

## 4. Repository Directory Structure

```text
eng-4k-project-ml/
|
├── dashboard/                      # Telemetry dashboard: backend, frontend, serial test tools
│                                   #   (structure and usage: dashboard/README.md)
|
├── data/
│   ├── raw/                        # Extracted NASA PCoE MAT files
│   └── processed/                  # NumPy archives and feature matrices
|
├── models/
│   ├── saved/                      # Native Keras floating-point model
│   ├── tflite/                     # Full INT8 TFLite model
│   ├── c_headers/
│   │   ├── scaling_params.h
│   │   ├── quantization_params.h
│   │   └── model_data.h
│   ├── scaling_params.json
│   ├── quantization_params.json
│   ├── evaluation_metrics.csv
│   ├── training_curves.png
│   ├── test_benchmark_b0018.png
│   └── quantization_parity.png
|
├── src/
│   ├── download_data.py
│   ├── parse_raw_data.py
│   ├── extract_features.py
│   ├── prepare_dataset.py
│   ├── train_model.py
│   ├── evaluate_model.py
│   ├── quantize_model.py
│   └── export_c_header.py
|
├── requirements.txt
├── verify_env.py
├── .gitignore
└── README.md
```

`dashboard/backend/telemetry.db` is generated locally at runtime and should remain excluded from Git.

---

## 5–10. Telemetry Dashboard

The dashboard documentation has moved to **[`dashboard/README.md`](dashboard/README.md)**. It covers:

- installation and startup (backend and frontend)
- mock scenarios (NORMAL, BALANCING, FAULT_DETECTED, ISOLATED)
- connecting the STM32 once the serial protocol is confirmed
- transport (MOCK/SERIAL) vs data origin (SYNTHETIC/MEASURED/UNVERIFIED) labelling
- the API, WebSocket messages, SQLite storage and CSV export
- automated tests, known limitations, and the demonstration steps

The provisional serial frame format and the mock serial loopback test are in [`dashboard/tools/README.md`](dashboard/tools/README.md).

---

## 11. TinyML Pipeline Execution: Step ML-1 to ML-9

All scripts include assertion gates intended to halt execution if data corruption, numerical instability, or metric threshold violations occur.

### Step ML-1: Environment Verification

Validates the Python runtime, compatible NumPy constraints, and directory architecture.

```bash
python verify_env.py
```

### Step ML-2: Dataset Ingestion

Downloads/extracts the NASA Ames PCoE Battery Aging Dataset target cells.

```bash
python src/download_data.py
```

### Step ML-3: Cycle Isolation & Ground-Truth Labelling

Filters charge/impedance tests, isolates discharge cycles, and creates SoH labels.

```bash
python src/parse_raw_data.py
```

### Step ML-4: Feature Extraction

Synchronizes discharge cycles to load engagement and computes the 3 physical degradation features.

```bash
python src/extract_features.py
```

### Step ML-5: Dataset Normalization & Group Partitioning

Creates training/validation partitions while keeping B0018 isolated for independent holdout testing.

```bash
python src/prepare_dataset.py
```

### Step ML-6: Model Architecture & Training

Trains the compact MLP:

```text
Input(3)
   |
Dense(16, ReLU)
   |
Dense(8, ReLU)
   |
Dense(1, Linear)
```

```bash
python src/train_model.py
```

### Step ML-7: Unseen Cell Benchmarking

Evaluates generalization on the independent B0018 battery.

```bash
python src/evaluate_model.py
```

### Step ML-8: INT8 Quantization

Applies full integer post-training quantization and checks Float32/INT8 parity.

```bash
python src/quantize_model.py
```

### Step ML-9: Static C Header Export

Exports the quantized model as a memory-aligned C byte array for embedded deployment.

```bash
python src/export_c_header.py
```

---

## 12. Firmware Integration Guide

For embedded inference on STM32G474RE or ESP32-S3, copy the generated contents of:

```text
models/c_headers/
```

into the microcontroller project's include path.

Generated files include:

```text
scaling_params.h
quantization_params.h
model_data.h
```

Typical inference flow:

```text
Physical battery measurements
        |
        v
Feature extraction
        |
        v
Normalization
        |
        v
INT8 quantization
        |
        v
TFLite Micro inference
        |
        v
Output dequantization
        |
        v
Estimated SoH (%)
```

The resulting SoH estimate will eventually be included in the STM32 telemetry packet and displayed by the dashboard.

---

## 13. Reproducing the TinyML Pipeline

### Prerequisites

- macOS (Apple Silicon supported) or Linux
- Python 3.11.9
- Git

### Setup

```bash
git clone <YOUR_GITHUB_REPO_URL>
cd eng-4k-project-ml

python3.11 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### Execute the full ML pipeline

```bash
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

## 14. Current Development Status

### TinyML

- [x] Dataset ingestion
- [x] Raw data parsing
- [x] Physics-informed feature extraction
- [x] Dataset preparation
- [x] MLP training
- [x] Holdout evaluation
- [x] INT8 quantization
- [x] C header export
- [ ] Physical STM32 deployment / profiling

### Software / Telemetry

Details: [`dashboard/README.md`](dashboard/README.md).

- [x] Mock serial loopback test (synthetic data, PTY)
- [x] Shared ingestion loop, WebSocket broadcast, SQLite logging, CSV export
- [x] Deterministic mock fault, isolation and balancing scenarios
- [x] Transport and data-origin labelling (MOCK/SERIAL, SYNTHETIC/MEASURED/UNVERIFIED)
- [x] Automated backend, serial and frontend tests
- [ ] Final STM32 packet protocol
- [ ] Physical serial connection
- [ ] Real embedded SoH values in dashboard
- [ ] Hardware-in-the-loop validation

---

## 15. Next Steps

1. Finalize the STM32 UART/USB serial telemetry packet with the firmware team.
2. Update `dashboard/tools/serial_frame.py` and `frame_to_packet()` in `dashboard/backend/serial_reader.py` to match the final packet format.
3. Run the dashboard against the STM32 with `BMS_TRANSPORT=SERIAL BMS_SERIAL_DATA_ORIGIN=MEASURED`.
4. Connect the STM32 and validate end-to-end serial → FastAPI → WebSocket → dashboard telemetry.
5. Replace simulated SoH values with TinyML inference results from the target MCU.
6. Test serial buffering, malformed packets, disconnects, and reconnection behavior.
7. Benchmark WebSocket and SQLite performance during continuous streaming.
8. Validate dashboard behavior during controlled hardware fault-injection tests.
9. Profile TinyML execution time, Flash use, and SRAM use on the physical controller.

---

## Target Hardware

- **Primary MCU:** STM32 NUCLEO-G474RE
- **Alternative/compatible target:** ESP32-S3
- **Battery topology:** 4S lithium-ion
- **Nominal pack voltage:** ~14.8 V
