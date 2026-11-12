/*
 * Auto-generated scaling parameters for on-device TinyML inference
 * Project: eng-4k-project-ml
 * Feature order: v_drop_window, temp_rise
 */

#ifndef SCALING_PARAMS_H
#define SCALING_PARAMS_H

#define NUM_FEATURES 2

static const float FEATURE_MEANS[NUM_FEATURES] = {
    0.29503337f, 6.59879446f
};

static const float FEATURE_STDS[NUM_FEATURES] = {
    0.03951088f, 0.74153340f
};

static inline void normalize_features(const float* raw_in, float* norm_out) {
    for (int i = 0; i < NUM_FEATURES; i++) {
        norm_out[i] = (raw_in[i] - FEATURE_MEANS[i]) / FEATURE_STDS[i];
    }
}

#endif /* SCALING_PARAMS_H */
