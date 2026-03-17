import numpy as np

# Candidate C (round2): two cosine components to capture multi-frequency forcing
# y = k0*x^2 + k1 + k2*cos(k3*t + k4) + k5*cos(k6*t + k7)
# Remaining parameter k8, k9 placeholders

def func(x, params):
    k0, k1, k2, k3, k4, k5, k6, k7 = params[:8]
    xv = x[:, 0]
    tv = x[:, 1]
    y = (
        k0 * (xv ** 2)
        + k1
        + k2 * np.cos(k3 * tv + k4)
        + k5 * np.cos(k6 * tv + k7)
    )
    return y.astype(float)


def run_search():
    return func
