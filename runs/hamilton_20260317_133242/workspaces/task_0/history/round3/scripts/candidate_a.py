import numpy as np

# Round3 candidate A: damping on x^2 via t^2 in denominator + cosine term + bias
# y = a * x^2 / (1 + g * t^2) + b * cos(c*t + d) + e
# params: a, b, c, d, e, g used (6)

def func(x, params):
    a, b, c, d, e, g = params[:6]
    xv = x[:, 0]
    tv = x[:, 1]
    denom = 1.0 + np.abs(g) * (tv ** 2)
    # Avoid extremely small denom (though 1 + abs(g)*t^2 >= 1)
    y = a * (xv ** 2) / denom + b * np.cos(c * tv + d) + e
    return y.astype(float)


def run_search():
    return func
