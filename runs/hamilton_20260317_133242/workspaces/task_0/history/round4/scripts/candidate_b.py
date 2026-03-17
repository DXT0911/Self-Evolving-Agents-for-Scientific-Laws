import numpy as np

# Round4 candidate B: multiplicative coupling between x^2 and cos term with gentle t damping
# y = a * x^2 / (1 + g * t^2) + b * cos(c*t + d) * (1 + k / (1 + h * t^2)) + e
# params used: a, b, c, d, e, g, k, h (8)

def func(x, params):
    a, b, c, d, e, g, k, h = params[:8]
    xv = x[:, 0]
    tv = x[:, 1]
    denom_x = 1.0 + np.abs(g) * (tv ** 2)
    mod_t = 1.0 + (k / (1.0 + np.abs(h) * (tv ** 2)))
    y = a * (xv ** 2) / denom_x + b * np.cos(c * tv + d) * mod_t + e
    return y.astype(float)


def run_search():
    return func
