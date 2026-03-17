import numpy as np

# Round5 candidate B: compress tanh correction into a linearized small-angle form
# y = a * x^2 / (1 + g * t^2) + b * cos(c*t + d) + e + f * sin(x) / (1 + h * t^2)
# params: a, b, c, d, e, g, f, h (8) but evaluator passes 10; we slice

def func(x, params):
    a, b, c, d, e, g, f, h = params[:8]
    xv = x[:, 0]
    tv = x[:, 1]
    denom_x = 1.0 + np.abs(g) * (tv ** 2)
    base = a * (xv ** 2) / denom_x + b * np.cos(c * tv + d) + e
    corr = f * np.sin(xv) / (1.0 + np.abs(h) * (tv ** 2))
    y = base + corr
    return y.astype(float)


def run_search():
    return func
