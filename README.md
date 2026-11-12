# Fault-Tolerant Active BMS (ENG 4000 Capstone)

This repository holds the software side of a fault-tolerant active battery management system (BMS) for a 4-cell series (4S) lithium-ion pack (~14.8 V nominal). The control board (Board 2) uses an ESP32-S3-WROOM-1 microcontroller.

## What's in the repository

| Folder | What it is | Status |
| --- | --- | --- |
| [`ml/`](ml/README.md) | TinyML State-of-Health (SoH) model: NASA PCoE data pipeline, cell-wise cross-validation, INT8 quantization and C header export for TensorFlow Lite Micro | Done (Steps ML-1 to ML-9). On-device testing (ML-10) not started |
| [`dashboard/`](dashboard/README.md) | Receive-only telemetry dashboard: FastAPI backend with SQLite logging, React web UI, CSV export | Runs on mock telemetry. Not yet tested with the ESP32-S3 |

## Headline results (ML)

- 193-parameter MLP, 2.64 KB of flash after INT8 quantization
- 2.42% MAE on an unseen test cell (B0018), 2.70 ± 0.66% over 10 training seeds
- 2.02% mean and 2.27% worst-cell MAE in leave-one-cell-out cross-validation
- 0.124% SoH drift between the Float32 and INT8 models

See [`ml/README.md`](ml/README.md) for the full scorecard, method and limitations.

## Quick start

```bash
git clone https://github.com/NRhaman2000/eng-4k-project-ml.git
cd eng-4k-project-ml
```

- **ML pipeline:** `cd ml`, then follow [`ml/README.md`](ml/README.md).
- **Dashboard:** follow [`dashboard/README.md`](dashboard/README.md).

## Safety boundary

The SoH model is advisory only. All protection decisions (cell isolation, bypass and shutdown) are made by deterministic firmware on the ESP32-S3, never by the ML model. The dashboard only monitors and sends no commands to the microcontroller.
