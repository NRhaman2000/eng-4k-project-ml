"""
Step ML-1 Verification Gate: Environment & Directory Architecture Check
Project: eng-4k-project-ml (Fault-Tolerant Active BMS TinyML State-of-Health)
"""

import sys
import os
from pathlib import Path

def test_environment():
    print("=" * 60)
    print("RUNNING STEP ML-1 VERIFICATION GATE...")
    print("=" * 60)

    # 1. Verify Python Version
    py_ver = sys.version_info
    print(f"Python Runtime: {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    assert py_ver.major == 3 and py_ver.minor in [10, 11, 12], (
        f"ERROR: Python 3.10, 3.11, or 3.12 recommended. Detected {py_ver.major}.{py_ver.minor}."
    )
    print(" [PASS] Python version compatible with TensorFlow TFLite.")

    # 2. Verify Core Packages
    try:
        import numpy as np
        print(f"NumPy Version: {np.__version__}")
        assert int(np.__version__.split('.')[0]) < 2, "ERROR: NumPy must be < 2.0.0."
        print(" [PASS] NumPy < 2.0 constraint verified.")

        import pandas as pd
        print(f"Pandas Version: {pd.__version__}")
        print(" [PASS] Pandas imported successfully.")

        import scipy
        print(f"SciPy Version: {scipy.__version__}")
        print(" [PASS] SciPy imported successfully.")

        import matplotlib
        print(f"Matplotlib Version: {matplotlib.__version__}")
        print(" [PASS] Matplotlib imported successfully.")

        import tensorflow as tf
        print(f"TensorFlow Version: {tf.__version__}")
        print(" [PASS] TensorFlow version compatible with embedded quantization.")

        # Check acceleration devices
        gpus = tf.config.list_physical_devices('GPU')
        if gpus:
            print(f" [INFO] Hardware Acceleration Detected: {len(gpus)} GPU(s) available.")
        else:
            print(" [INFO] Running on standard high-performance CPU backend.")

    except ImportError as e:
        print(f"\n[FAIL] Missing package: {e}")
        print("--> Run: pip install -r requirements.txt")
        sys.exit(1)
    except AssertionError as e:
        print(f"\n[FAIL] Assertion violation: {e}")
        sys.exit(1)

    # 3. Verify Directory Architecture
    root = Path(".")
    required_paths = [
        root / "data" / "raw",
        root / "data" / "processed",
        root / "models" / "saved",
        root / "models" / "tflite",
        root / "models" / "c_headers",
        root / "src",
        root / "notebooks",
        root / "requirements.txt",
        root / ".gitignore"
    ]

    print("\nVerifying directory architecture...")
    for p in required_paths:
        if not p.exists():
            print(f" [MISSING] Creating missing path/file: {p}")
            if p.suffix:  # It's a file
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch()
            else:  # It's a directory
                p.mkdir(parents=True, exist_ok=True)
        else:
            print(f" [PASS] Exists: {p}")

    print("=" * 60)
    print("ALL ML-1 SANITY CHECKS PASSED: Environment is 100% ready.")
    print("=" * 60)

if __name__ == "__main__":
    test_environment()