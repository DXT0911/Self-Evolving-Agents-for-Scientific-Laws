"""
Evaluator for a symbolic regression model.
It assesses a model program based on its performance on training data.
The model's `func` is expected to take a matrix X of inputs.
"""
import concurrent.futures
import importlib.util
import os
import sys
import numpy as np
from scipy.optimize import minimize

NUM_INPUT_FEATURES_EXPECTED = 2
MODEL_NUM_PARAMS_EXPECTED = 10

X_TRAIN_EVAL_PATH = r'./problems/phys_osc/PO10/X_train_for_eval.npy'
Y_TRAIN_EVAL_PATH = r'./problems/phys_osc/PO10/y_train_for_eval.npy'


def run_with_timeout(func, args=(), kwargs={}, timeout_seconds=5):
    if timeout_seconds is None or timeout_seconds <= 0:
        return func(*args, **kwargs)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            func_name = getattr(func, '__name__', 'Unnamed function')
            raise TimeoutError(f"Function {func_name} timed out after {timeout_seconds} seconds")


def filter_and_convert_metrics(current_metrics_dict):
    filtered_dict = {}
    float_metric_keys = ['combined_score', 'negative_mse']

    for key in float_metric_keys:
        if key in current_metrics_dict:
            value = current_metrics_dict[key]
            if value is None:
                continue
            if isinstance(value, (int, float, np.integer, np.floating, bool)):
                try:
                    filtered_dict[key] = float(value)
                except (ValueError, TypeError):
                    pass
    return filtered_dict


def objective_function(params, model_func, X_matrix, y_true_vector):
    if not callable(model_func):
        return float('inf')
    try:
        predictions = model_func(X_matrix, params)
        if not isinstance(predictions, np.ndarray) or predictions.shape != y_true_vector.shape:
            return float('inf')
    except Exception:
        return float('inf')
    if np.any(np.isnan(predictions)) or np.any(np.isinf(predictions)):
        return float('inf')
    return float(np.mean((predictions - y_true_vector) ** 2))


def evaluate(program_path):
    metrics = {
        'can_run': 0.0,
        'negative_mse': -1e09,
        'raw_mse_train': float('inf'),
        'mse_train_score': 0.0,
        'num_params': MODEL_NUM_PARAMS_EXPECTED,
        'combined_score': -1e09,
        'error_message': None,
        'optimization_success': False,
        'optimized_params': None,
    }

    try:
        X_train = np.load(X_TRAIN_EVAL_PATH)
        y_train = np.load(Y_TRAIN_EVAL_PATH)
        if X_train.shape[1] != NUM_INPUT_FEATURES_EXPECTED:
            metrics['error_message'] = f"Loaded X_train has {X_train.shape[1]} features, expected {NUM_INPUT_FEATURES_EXPECTED}."
            return filter_and_convert_metrics(metrics)
        if X_train.shape[0] != y_train.shape[0]:
            metrics['error_message'] = f"X_train has {X_train.shape[0]} samples, y_train has {y_train.shape[0]}."
            return filter_and_convert_metrics(metrics)
    except Exception as exc:
        metrics['error_message'] = f"Failed to load training data: {exc}. Paths: X:{X_TRAIN_EVAL_PATH}, Y:{Y_TRAIN_EVAL_PATH}"
        return filter_and_convert_metrics(metrics)

    try:
        spec = importlib.util.spec_from_file_location("model_program", program_path)
        if spec is None or spec.loader is None:
            metrics['error_message'] = f"Could not create spec for module at {program_path}"
            return filter_and_convert_metrics(metrics)
        model_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model_module)
        metrics['can_run'] = 0.2

        if not hasattr(model_module, 'run_search') or not callable(model_module.run_search):
            metrics['error_message'] = "Model program missing callable 'run_search'."
            return filter_and_convert_metrics(metrics)
        func_to_eval = model_module.run_search()
        if not callable(func_to_eval):
            metrics['error_message'] = "'run_search' did not return a callable function."
            return filter_and_convert_metrics(metrics)

        num_dummy_samples = 5
        dummy_x = np.random.rand(num_dummy_samples, NUM_INPUT_FEATURES_EXPECTED)
        if NUM_INPUT_FEATURES_EXPECTED == 0:
            dummy_x = np.empty((num_dummy_samples, 0))
        dummy_params = np.random.rand(MODEL_NUM_PARAMS_EXPECTED)
        pred_test = run_with_timeout(func_to_eval, args=(dummy_x, dummy_params), timeout_seconds=5)
        if not isinstance(pred_test, np.ndarray) or pred_test.shape != (num_dummy_samples,):
            metrics['can_run'] = 0.5
            metrics['error_message'] = f"Func test: output shape mismatch. Got {pred_test.shape if isinstance(pred_test, np.ndarray) else type(pred_test)}, expected ({num_dummy_samples},)."
            return filter_and_convert_metrics(metrics)
        metrics['can_run'] = 1.0
    except TimeoutError as exc:
        metrics['can_run'] = 0.5
        metrics['error_message'] = f"Func execution test timed out: {exc}"
        return filter_and_convert_metrics(metrics)
    except FileNotFoundError:
        metrics['error_message'] = f"Model program file not found: {program_path}"
        return filter_and_convert_metrics(metrics)
    except Exception as exc:
        metrics['can_run'] = 0.5
        metrics['error_message'] = f"Failed to load or test model function: {exc}"
        return filter_and_convert_metrics(metrics)

    if metrics['can_run'] < 1.0:
        return filter_and_convert_metrics(metrics)

    initial_params = np.random.rand(MODEL_NUM_PARAMS_EXPECTED)
    optimized_params = None
    try:
        opt_result = minimize(
            objective_function,
            initial_params,
            args=(func_to_eval, X_train, y_train),
            method='BFGS',
        )
        metrics['raw_mse_train'] = opt_result.fun if np.isfinite(opt_result.fun) else float('inf')
        metrics['optimization_success'] = opt_result.success
        optimized_params = opt_result.x if opt_result.success or hasattr(opt_result, 'x') else initial_params
        if not opt_result.success and metrics['error_message'] is None:
            metrics['error_message'] = f"Optimization did not converge: {getattr(opt_result, 'message', 'Unknown reason')}"
    except Exception as exc:
        metrics['raw_mse_train'] = float('inf')
        metrics['error_message'] = f"Error during optimization: {exc}"

    metrics['optimized_params'] = optimized_params.tolist() if optimized_params is not None else None
    if np.isfinite(metrics['raw_mse_train']):
        metrics['negative_mse'] = -metrics['raw_mse_train']
        metrics['mse_train_score'] = -np.log10(metrics['raw_mse_train'] + 1e-9)
    else:
        metrics['mse_train_score'] = 0.0
    metrics['combined_score'] = metrics['mse_train_score']
    return filter_and_convert_metrics(metrics)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python evaluator.py <path_to_model_program.py>")
        sys.exit(1)

    program_to_evaluate = sys.argv[1]
    if not os.path.exists(program_to_evaluate):
        print(f"Error: Program file '{program_to_evaluate}' not found.")
        sys.exit(1)

    print(f"Evaluating model: {program_to_evaluate}")
    print(f"Using NUM_INPUT_FEATURES_EXPECTED = {NUM_INPUT_FEATURES_EXPECTED}")
    print(f"Using MODEL_NUM_PARAMS_EXPECTED = {MODEL_NUM_PARAMS_EXPECTED}")
    print(f"Loading X_train from: {X_TRAIN_EVAL_PATH}")
    print(f"Loading y_train from: {Y_TRAIN_EVAL_PATH}")

    if not os.path.exists(X_TRAIN_EVAL_PATH):
        print(f"Error: X_train data file '{X_TRAIN_EVAL_PATH}' not found.")
        sys.exit(1)
    if not os.path.exists(Y_TRAIN_EVAL_PATH):
        print(f"Error: y_train data file '{Y_TRAIN_EVAL_PATH}' not found.")
        sys.exit(1)

    evaluation_results = evaluate(program_to_evaluate)
    print("\nEvaluation Results:")
    for key, value in evaluation_results.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")
