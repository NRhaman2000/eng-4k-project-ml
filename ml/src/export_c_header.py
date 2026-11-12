"""
Step ML-9: Static C Header Export & Bit-Level Parity Verification
Project: eng-4k-project-ml
Converts the INT8 TFLite model into an aligned C byte array header (model_data.h)
and verifies bit-for-bit SHA-256 checksum and inference integrity.
"""

import os
import sys
import re
import hashlib
from pathlib import Path
import numpy as np
import tensorflow as tf

MODELS_DIR = Path("models")
TFLITE_PATH = MODELS_DIR / "tflite" / "soh_model_int8.tflite"
C_HEADERS_DIR = MODELS_DIR / "c_headers"
OUTPUT_HEADER_PATH = C_HEADERS_DIR / "model_data.h"


def generate_c_header(tflite_bytes: bytes) -> str:
    """
    Formats binary bytes into an aligned, production-grade C/C++ header file.
    """
    total_len = len(tflite_bytes)
    sha256_hash = hashlib.sha256(tflite_bytes).hexdigest()

    header_lines = [
        "/*",
        " * Auto-generated TinyML Model Byte Array for Embedded Inference",
        " * Project: eng-4k-project-ml (Fault-Tolerant Active BMS)",
        " * Target: ARM Cortex-M4 (STM32G474) / Xtensa LX7 (ESP32-S3)",
        " * Architecture: TensorFlow Lite for Microcontrollers (TFLM)",
        f" * Binary Size: {total_len} bytes",
        f" * SHA-256: {sha256_hash}",
        " */",
        "",
        "#ifndef SOH_MODEL_DATA_H",
        "#define SOH_MODEL_DATA_H",
        "",
        "#include <stdint.h>",
        "",
        "/* static: safe to include from several .c files without duplicate symbols */",
        "/* Align to 4-byte boundary to prevent Cortex-M memory bus faults */",
        "#if defined(__GNUC__) || defined(__clang__)",
        "  #define DATA_ALIGN(x) __attribute__((aligned(x)))",
        "#elif defined(_MSC_VER)",
        "  #define DATA_ALIGN(x) __declspec(align(x))",
        "#else",
        "  #define DATA_ALIGN(x)",
        "#endif",
        "",
        f"static const unsigned int g_soh_model_data_len = {total_len};",
        "",
        "static const unsigned char g_soh_model_data[] DATA_ALIGN(4) = {"
    ]

    # Format bytes in rows of 12 hex values
    bytes_per_row = 12
    for i in range(0, total_len, bytes_per_row):
        chunk = tflite_bytes[i:i + bytes_per_row]
        hex_str = ", ".join([f"0x{b:02x}" for b in chunk])
        comma = "," if (i + bytes_per_row) < total_len else ""
        header_lines.append(f"    {hex_str}{comma}")

    header_lines.extend([
        "};",
        "",
        "#endif /* SOH_MODEL_DATA_H */",
        ""
    ])

    return "\n".join(header_lines)


def run_c_header_export():
    print("=" * 65)
    print("RUNNING STEP ML-9: STATIC C HEADER EXPORT (model_data.h)")
    print("=" * 65)

    if not TFLITE_PATH.exists():
        raise FileNotFoundError(f"Missing {TFLITE_PATH}. Run Step ML-8 first.")

    C_HEADERS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Read binary TFLite flatbuffer
    with open(TFLITE_PATH, "rb") as f_in:
        raw_bytes = f_in.read()

    file_size = len(raw_bytes)
    original_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    print(f"Loaded TFLite Binary:")
    print(f"  Source File: {TFLITE_PATH}")
    print(f"  Size:        {file_size} bytes ({file_size / 1024:.2f} KB)")
    print(f"  SHA-256:     {original_sha256}")

    # 2. Generate C Header Content
    header_content = generate_c_header(raw_bytes)

    # 3. Write to file
    with open(OUTPUT_HEADER_PATH, "w") as f_out:
        f_out.write(header_content)

    assert OUTPUT_HEADER_PATH.exists(), f"ERROR: Failed to save {OUTPUT_HEADER_PATH}"
    print(f"\n [PASS] C header successfully created: {OUTPUT_HEADER_PATH}")

    # 4. Strict Bit-Level Round-Trip Integrity Gate
    print("\nExecuting Bit-Level Parity & Deserialization Gate...")
    with open(OUTPUT_HEADER_PATH, "r") as f_check:
        read_back_text = f_check.read()

    # Extract all hexadecimal tokens (0xXX) from the C array
    hex_tokens = re.findall(r"0x([0-9a-fA-F]{2})", read_back_text)
    reconstructed_bytes = bytes([int(h, 16) for h in hex_tokens])

    reconstructed_sha256 = hashlib.sha256(reconstructed_bytes).hexdigest()

    assert len(reconstructed_bytes) == file_size, (
        f"ERROR: Byte length mismatch. Original {file_size}, parsed {len(reconstructed_bytes)}"
    )
    assert reconstructed_sha256 == original_sha256, (
        f"ERROR: SHA-256 hash mismatch between .tflite and generated header!\n"
        f"Expected: {original_sha256}\nGot:      {reconstructed_sha256}"
    )
    print(" [PASS] Bit-for-bit SHA-256 checksum matches 100%.")

    # 5. Runtime Deserialization Test in TensorFlow Lite
    interpreter = tf.lite.Interpreter(model_content=reconstructed_bytes)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]

    # Test dummy inference vector
    dummy_input = np.zeros(input_details["shape"], dtype=np.int8)
    interpreter.set_tensor(input_details["index"], dummy_input)
    interpreter.invoke()
    dummy_output = interpreter.get_tensor(output_details["index"])

    print(f" [PASS] TFLite successfully parsed model from reconstructed C array.")
    print(f"        Input Tensor Shape:  {input_details['shape']} (INT8)")
    print(f"        Output Tensor Shape: {output_details['shape']} (INT8)")
    print(f"        Verification Output: {dummy_output.flatten()[0]} (Zero-vector response)")

    # 6. Verify Complete C-Header Suite for Microcontroller
    required_firmware_headers = [
        C_HEADERS_DIR / "scaling_params.h",
        C_HEADERS_DIR / "quantization_params.h",
        C_HEADERS_DIR / "model_data.h"
    ]
    print("\nFirmware C Header Suite Status:")
    for h in required_firmware_headers:
        assert h.exists(), f"ERROR: Missing header: {h}"
        print(f" [READY] {h} ({h.stat().st_size} bytes)")

    print("\n" + "=" * 65)
    print("ALL ML-9 SANITY CHECKS PASSED: Model is ready for MCU deployment.")
    print("=" * 65)


if __name__ == "__main__":
    run_c_header_export()