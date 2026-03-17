import numpy as np

# Candidate A (round2): baseline from round1
# y = p0 * x^2 + p1 * cos(p2 * t + p3) + p4
# Remaining parameters are placeholders to keep param dim = 10

def func(x, params):
    p0, p1, p2, p3, p4 = params[:5]
    xv = x[:, 0]
    tv = x[:, 1]
    y = p0 * (xv ** 2) + p1 * np.cos(p2 * tv + p3) + p4
    return y.astype(float)


def run_search():
    return func
