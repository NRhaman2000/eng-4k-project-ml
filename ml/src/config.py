"""
Shared pipeline configuration (single source of truth for ML-5 .. ML-8).

Feature and hyperparameter choices below were made with leave-one-cell-out
cross-validation on the TRAINING cells only (src/cross_validate.py).
The test cell B0018 is never used to make a choice.
"""

TRAIN_CELLS = ["B0005", "B0006", "B0007"]
TEST_CELL = "B0018"

# Selected by cross-validation (lowest worst-fold MAE and lowest seed spread).
# v_drop_ohmic was dropped: in the NASA logs the sample before load-on is
# 10-19 s earlier, so it measures ohmic + 10-19 s of polarization and would
# not match an ESP32 sampling at a much faster rate.
FEATURE_NAMES = [
    "v_drop_window",   # V(100 s) - V(1000 s) under 2 A load
    "temp_rise",       # T(1000 s) - T(0 s)
]
TARGET_NAME = "soh_percent"

# Candidate feature sets compared in cross-validation
CANDIDATE_FEATURE_SETS = {
    "orig3": ["v_drop_ohmic", "v_drop_window", "temp_rise"],
    "win_only": ["v_drop_window"],
    "win+ohm": ["v_drop_ohmic", "v_drop_window"],
    "win+temp": ["v_drop_window", "temp_rise"],
}

# Training hyperparameters. Epoch count is fixed (no early stopping): the old
# random-shuffle validation set leaked neighbouring cycles, so stopping on it
# was not meaningful. 150 epochs was validated with cell-wise CV.
EPOCHS = 150
BATCH_SIZE = 16
LEARNING_RATE = 0.005
L2 = 1e-4

DEPLOY_SEED = 0               # seed of the model that gets exported
REPORT_SEEDS = list(range(10))  # seeds used to report mean +/- std
CV_SEEDS = list(range(3))

MAE_SPEC_PCT = 4.0
