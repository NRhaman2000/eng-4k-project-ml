/*
 * Auto-generated affine quantization parameters for on-device INT8 inference
 * Project: eng-4k-project-ml
 */

#ifndef QUANTIZATION_PARAMS_H
#define QUANTIZATION_PARAMS_H

#include <stdint.h>
#include <math.h>

#define INPUT_SCALE       0.02059590f
#define INPUT_ZERO_POINT   -20
#define OUTPUT_SCALE      0.00380884f
#define OUTPUT_ZERO_POINT  -128

/* Quantizes a normalized float feature into signed INT8 for the neural network */
static inline int8_t quantize_input(float norm_val) {
    int32_t q = (int32_t)roundf(norm_val / INPUT_SCALE) + INPUT_ZERO_POINT;
    if (q < -128) q = -128;
    if (q > 127)  q = 127;
    return (int8_t)q;
}

/* Dequantizes the neural network's INT8 output back to physical SoH (%) */
static inline float dequantize_output(int8_t q_out) {
    float norm_soh = ((float)q_out - (float)OUTPUT_ZERO_POINT) * OUTPUT_SCALE;
    return norm_soh * 100.0f; /* Convert fraction back to percentage */
}

#endif /* QUANTIZATION_PARAMS_H */
