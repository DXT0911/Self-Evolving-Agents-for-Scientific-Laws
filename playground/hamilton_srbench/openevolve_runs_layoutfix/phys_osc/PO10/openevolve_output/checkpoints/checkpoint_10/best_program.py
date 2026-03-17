"""
Initial program: A naive linear model for symbolic regression.
This model predicts the output as a linear combination of input variables
or a constant if no input variables are present.
The function is designed for vectorized input (X matrix).

Target output variable: dv_dt (Acceleration in Nonl-linear Harmonic Oscillator)
Input variables (columns of x): x (Position at time t), t (Time)
"""
import numpy as np

# Input variable mapping for x (columns of the input matrix):
#   x[:, 0]: x (Position at time t)
#   x[:, 1]: t (Time)

# Parameters will be optimized by BFGS outside this function.
# Number of parameters expected by this model: 10.
# Example initialization: params = np.random.rand(10)

# EVOLVE-BLOCK-START

def func(x, params):
    """
    Calculates the model output using a linear combination of input variables
    or a constant value if no input variables. Operates on a matrix of samples.

    Args:
        x (np.ndarray): A 2D numpy array of input variable values, shape (n_samples, n_features).
                        n_features is 2.
                        If n_features is 0, x should be shape (n_samples, 0).
                        The order of columns in x must correspond to:
                        (x, t).
        params (np.ndarray): A 1D numpy array of parameters.
                             Expected length: 10.

    Returns:
        np.ndarray: A 1D numpy array of predicted output values, shape (n_samples,).
    """
    # Introduce a non-linear oscillator-inspired model:
    # dv/dt ≈ -k*x - c*x^3 + A*cos(ω*t) + B*sin(ω*t)
    pos = x[:, 0]
    time = x[:, 1]
    k_lin = params[0]
    k_nonlin = params[1]
    A_drive = params[2]
    B_drive = params[3]
    omega = params[4]
    # Include potential damping term proportional to velocity-like effect (approximated via time dependence)
    damping = params[5] * pos * np.exp(-params[6] * time)
    result = (-k_lin * pos
              - k_nonlin * pos**3
              + A_drive * np.cos(omega * time)
              + B_drive * np.sin(omega * time)
              - damping)
    return result

# EVOLVE-BLOCK-END

# This part remains fixed (not evolved)
def run_search():
    return func
