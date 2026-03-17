import numpy as np

# Candidate A: Inspired by PySR trend y ≈ x^2 + A*cos(t) + B
# Use 10 parameters; core ones: p0 (x^2 coeff), p1 (cos amplitude), p2 (t scale), p3 (t phase), p4 (bias)
# Remaining params are unused placeholders for compatibility.

def func(x, params):
    # x[:,0] = x (position), x[:,1] = t (time)
    p0, p1, p2, p3, p4 = params[:5]
    xv = x[:, 0]
    tv = x[:, 1]
    # Safe cos with scaled/shifted t
    y = p0 * (xv ** 2) + p1 * np.cos(p2 * tv + p3) + p4
    return y.astype(float)


def run_search():
    return func
