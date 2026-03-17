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
    amp_cos = params[2]
    amp_sin = params[3]
    omega = params[4]
    damping_lin = params[5]
    damping_quad = params[6]
    phase_shift_cos = params[7]
    phase_shift_sin = params[8]
    eps = 1e-8
    # Approximate velocity as pos/time to include linear velocity damping
    vel_term = -damping_lin * (pos / (time + eps))
    # Include quadratic damping based on position magnitude
    quad_damp_term = -damping_quad * pos**2
    # Add coupling term between displacement and periodic cosine to capture richer dynamics
    coupling_amp = params[9] if len(params) > 9 else 0.0
    coupling_term = coupling_amp * pos * np.cos(omega * time)
    result = (-k_lin * pos
              - k_nonlin * pos**3
              + amp_cos * np.cos(omega * time + phase_shift_cos)
              + amp_sin * np.sin(omega * time + phase_shift_sin)
              + vel_term
              + quad_damp_term
              + coupling_term)
    return result

# EVOLVE-BLOCK-END

# This part remains fixed (not evolved)
def run_search():
    return func
