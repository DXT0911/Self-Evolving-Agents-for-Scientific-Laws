import numpy as np

# Round4 candidate C: add small sin(x) bounded correction with t-damped strength
# y = a * x^2 / (1 + g * t^2) + b * cos(c*t + d) + e + f * tanh( m * np.sin(x) / (1 + h * t^2) )
# params used: a, b, c, d, e, g, f, m, h (9)

def func(x, params):
    a, b, c, d, e, g, f, m, h = params[:9]
    xv = x[:, 0]
    tv = x[:, 1]
    denom_x = 1.0 + np.abs(g) * (tv ** 2)
    y_base = a * (xv ** 2) / denom_x + b * np.cos(c * tv + d) + e
    corr = f * np.tanh( (m * np.sin(xv)) / (1.0 + np.abs(h) * (tv ** 2)) )
    y = y_base + corr
    return y.astype(float)


def run_search():
    return func
