import numpy as np

# Round5 candidate C: couple cos amplitude to the same damping as x^2, reducing params
# y = a * x^2 / (1 + g * t^2) + (b / (1 + g * t^2)) * cos(c*t + d) + e
# params: a, b, c, d, e, g (6)

def func(x, params):
    a, b, c, d, e, g = params[:6]
    xv = x[:, 0]
    tv = x[:, 1]
    damp = 1.0 + np.abs(g) * (tv ** 2)
    y = a * (xv ** 2) / damp + (b / damp) * np.cos(c * tv + d) + e
    return y.astype(float)


def run_search():
    return func
