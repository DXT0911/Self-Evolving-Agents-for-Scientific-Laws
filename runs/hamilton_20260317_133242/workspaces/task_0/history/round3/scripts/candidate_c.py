import numpy as np

# Round3 candidate C: replace sin(x/(1+g|t|)) with limited tanh of ratio to reduce sensitivity, plus cos term and bias
# y = a*x^2 + b*cos(c*t + d) + e - f*tanh( x / (1 + g*t^2) )
# params: a,b,c,d,e,f,g used (7)

def func(x, params):
    a, b, c, d, e, f, g = params[:7]
    xv = x[:, 0]
    tv = x[:, 1]
    denom = 1.0 + np.abs(g) * (tv ** 2)
    ratio = xv / denom
    y = a * (xv ** 2) + b * np.cos(c * tv + d) + e - f * np.tanh(ratio)
    return y.astype(float)


def run_search():
    return func
