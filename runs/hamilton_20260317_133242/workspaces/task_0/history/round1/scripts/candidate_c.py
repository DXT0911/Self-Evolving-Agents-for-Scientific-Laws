import numpy as np

# Candidate C: Multiplicative structure combining x^2 and cos(t)
# y ≈ (k0*x^2 + k1) + k2*cos(k3*t) + k4*cos(k5*t + k6)


def func(x, params):
    k0, k1, k2, k3, k4, k5, k6 = params[:7]
    xv = x[:, 0]
    tv = x[:, 1]
    y = k0 * xv**2 + k1 + k2 * np.cos(k3 * tv) + k4 * np.cos(k5 * tv + k6)
    return y.astype(float)


def run_search():
    return func
