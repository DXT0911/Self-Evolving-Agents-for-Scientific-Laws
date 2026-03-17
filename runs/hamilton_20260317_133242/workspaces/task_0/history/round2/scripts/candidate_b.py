import numpy as np

# Candidate B (round2): add weak sin(x/t) and safety for division
# y = a*x^2 + b*cos(c*t + d) + e - f*sin( x / (1 + g*|t|) )
# Parameters: a,b,c,d,e,f,g used; others placeholders

def func(x, params):
    a, b, c, d, e, f, g = params[:7]
    xv = x[:, 0]
    tv = x[:, 1]
    denom = 1.0 + np.abs(g) * np.abs(tv)
    ratio = xv / denom
    y = a * (xv ** 2) + b * np.cos(c * tv + d) + e - f * np.sin(ratio)
    return y.astype(float)


def run_search():
    return func
