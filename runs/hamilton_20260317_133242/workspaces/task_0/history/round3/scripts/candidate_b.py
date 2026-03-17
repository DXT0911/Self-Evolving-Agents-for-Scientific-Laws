import numpy as np

# Round3 candidate B: multiplicative modulation x^2 * (1 + alpha*cos(omega t + phi)) + bias
# y = a * x^2 * (1 + b * cos(c*t + d)) + e
# params: a, b, c, d, e used (5)

def func(x, params):
    a, b, c, d, e = params[:5]
    xv = x[:, 0]
    tv = x[:, 1]
    mod = 1.0 + b * np.cos(c * tv + d)
    y = a * (xv ** 2) * mod + e
    return y.astype(float)


def run_search():
    return func
