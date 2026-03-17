import numpy as np

# Round5 candidate A: simplified Round3 winner without tanh correction
# y = a * x^2 / (1 + g * t^2) + b * cos(c*t + d) + e
# params used: a, b, c, d, e, g (6) but evaluator passes 10; we safely slice

def func(x, params):
    a, b, c, d, e, g = params[:6]
    xv = x[:, 0]
    tv = x[:, 1]
    denom_x = 1.0 + np.abs(g) * (tv ** 2)
    y = a * (xv ** 2) / denom_x + b * np.cos(c * tv + d) + e
    return y.astype(float)


def run_search():
    return func
