import numpy as np

# Candidate B: Include a sin(x/t) term hinted by PySR, with damping by cos(t)
# y ≈ a*x^2 + b*cos(t) + c - d*sin(x/t)

def func(x, params):
    a, b, c, d, e = params[:5]
    xv = x[:, 0]
    tv = x[:, 1]
    # Guard division by small t
    denom = np.where(np.abs(tv) < 1e-6, 1e-6, tv)
    term = np.sin(xv / denom)
    y = a * xv**2 + b * np.cos(tv) + c - d * term + e
    return y.astype(float)


def run_search():
    return func
