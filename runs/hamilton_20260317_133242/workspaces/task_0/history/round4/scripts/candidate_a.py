import numpy as np

# Round4 candidate A: add damping on cosine amplitude in addition to x^2 damping
# y = a * x^2 / (1 + g * t^2) + (b / (1 + k * t^2)) * cos(c*t + d) + e
# params used: a, b, c, d, e, g, k (7 of 10)

def func(x, params):
    a, b, c, d, e, g, k = params[:7]
    xv = x[:, 0]
    tv = x[:, 1]
    denom_x = 1.0 + np.abs(g) * (tv ** 2)
    denom_cos = 1.0 + np.abs(k) * (tv ** 2)
    y = a * (xv ** 2) / denom_x + (b / denom_cos) * np.cos(c * tv + d) + e
    return y.astype(float)


def run_search():
    return func
