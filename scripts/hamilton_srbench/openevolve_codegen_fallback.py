#!/usr/bin/env python3
"""SRBENCH_ANCHOR_LOCAL_CODEGEN

Local fallback for generating OpenEvolve-style symbolic regression problem packs.

This keeps the export pipeline usable when the temporary OpenEvolve checkout under
`/tmp/openevolve` is absent. The emitted files follow the same interface contract:
`initial_program.py`, `evaluator.py`, `config.yaml`, and the train/test/OOD arrays.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import numpy as np
import yaml


MODEL_NUM_PARAMS = 10


def _input_output_symbols(problem_data: dict) -> tuple[list[str], list[str]]:
    symbols = list(problem_data["symbols"])
    symbol_properties = list(problem_data["symbol_properties"])
    input_symbols = [symbol for symbol, prop in zip(symbols, symbol_properties) if prop != "O"]
    output_symbols = [symbol for symbol, prop in zip(symbols, symbol_properties) if prop == "O"]
    if len(output_symbols) != 1:
        raise RuntimeError(f"Expected exactly one output symbol, got: {output_symbols}")
    return input_symbols, output_symbols


def _desc_map(problem_data: dict) -> dict[str, str]:
    return {
        str(symbol): str(desc)
        for symbol, desc in zip(problem_data["symbols"], problem_data["symbol_descs"])
    }


def _feature_expression(num_features: int) -> str:
    if num_features == 0:
        return "result = np.full(x.shape[0], params[0])"

    terms = [f"x[:, {idx}] * params[{idx}]" for idx in range(num_features)]
    if len(terms) == 1:
        return f"result = {terms[0]}"
    return "result = " + " + ".join(terms)


def _program_text(problem_data: dict) -> str:
    input_symbols, output_symbols = _input_output_symbols(problem_data)
    output_symbol = output_symbols[0]
    desc_map = _desc_map(problem_data)
    raw_feature_lines = "\n".join(
        f"#   x[:, {idx}]: {symbol} ({desc_map.get(symbol, symbol)})"
        for idx, symbol in enumerate(input_symbols)
    )
    feature_lines = textwrap.indent(
        raw_feature_lines or "#   x has shape (n_samples, 0) for this problem.",
        "        ",
    )
    feature_tuple = ", ".join(input_symbols) if input_symbols else ""
    feature_expr = textwrap.indent(_feature_expression(len(input_symbols)), "            ")
    doc = textwrap.dedent(
        f'''\
        """
        Initial program: A naive linear model for symbolic regression.
        This model predicts the output as a linear combination of input variables
        or a constant if no input variables are present.
        The function is designed for vectorized input (X matrix).

        Target output variable: {output_symbol} ({desc_map.get(output_symbol, output_symbol)})
        Input variables (columns of x): {", ".join(f"{symbol} ({desc_map.get(symbol, symbol)})" for symbol in input_symbols) or "none"}
        """
        import numpy as np

        # Input variable mapping for x (columns of the input matrix):
{feature_lines}

        # Parameters will be optimized by BFGS outside this function.
        # Number of parameters expected by this model: {MODEL_NUM_PARAMS}.
        # Example initialization: params = np.random.rand({MODEL_NUM_PARAMS})

        # EVOLVE-BLOCK-START

        def func(x, params):
            """
            Calculates the model output using a linear combination of input variables
            or a constant value if no input variables. Operates on a matrix of samples.

            Args:
                x (np.ndarray): A 2D numpy array of input variable values, shape (n_samples, n_features).
                                n_features is {len(input_symbols)}.
                                If n_features is 0, x should be shape (n_samples, 0).
                                The order of columns in x must correspond to:
                                ({feature_tuple}).
                params (np.ndarray): A 1D numpy array of parameters.
                                     Expected length: {MODEL_NUM_PARAMS}.

            Returns:
                np.ndarray: A 1D numpy array of predicted output values, shape (n_samples,).
            """
{feature_expr}
            return result

        # EVOLVE-BLOCK-END

        # This part remains fixed (not evolved)
        def run_search():
            return func
        '''
    )
    return doc.strip() + "\n"


def _evaluator_text(problem_data: dict) -> str:
    input_symbols, _ = _input_output_symbols(problem_data)
    dataset_identifier = problem_data["dataset_identifier"]
    equation_idx = problem_data["equation_idx"]
    return textwrap.dedent(
        f"""\
        \"\"\"
        Evaluator for a symbolic regression model.
        It assesses a model program based on its performance on training data.
        The model's `func` is expected to take a matrix X of inputs.
        \"\"\"
        import concurrent.futures
        import importlib.util
        import os
        import sys
        import numpy as np
        from scipy.optimize import minimize

        NUM_INPUT_FEATURES_EXPECTED = {len(input_symbols)}
        MODEL_NUM_PARAMS_EXPECTED = {MODEL_NUM_PARAMS}

        X_TRAIN_EVAL_PATH = r'./problems/{dataset_identifier}/{equation_idx}/X_train_for_eval.npy'
        Y_TRAIN_EVAL_PATH = r'./problems/{dataset_identifier}/{equation_idx}/y_train_for_eval.npy'


        def run_with_timeout(func, args=(), kwargs={{}}, timeout_seconds=5):
            if timeout_seconds is None or timeout_seconds <= 0:
                return func(*args, **kwargs)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=timeout_seconds)
                except concurrent.futures.TimeoutError:
                    func_name = getattr(func, '__name__', 'Unnamed function')
                    raise TimeoutError(f"Function {{func_name}} timed out after {{timeout_seconds}} seconds")


        def filter_and_convert_metrics(current_metrics_dict):
            filtered_dict = {{}}
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
            metrics = {{
                'can_run': 0.0,
                'negative_mse': -1e09,
                'raw_mse_train': float('inf'),
                'mse_train_score': 0.0,
                'num_params': MODEL_NUM_PARAMS_EXPECTED,
                'combined_score': -1e09,
                'error_message': None,
                'optimization_success': False,
                'optimized_params': None,
            }}

            try:
                X_train = np.load(X_TRAIN_EVAL_PATH)
                y_train = np.load(Y_TRAIN_EVAL_PATH)
                if X_train.shape[1] != NUM_INPUT_FEATURES_EXPECTED:
                    metrics['error_message'] = f"Loaded X_train has {{X_train.shape[1]}} features, expected {{NUM_INPUT_FEATURES_EXPECTED}}."
                    return filter_and_convert_metrics(metrics)
                if X_train.shape[0] != y_train.shape[0]:
                    metrics['error_message'] = f"X_train has {{X_train.shape[0]}} samples, y_train has {{y_train.shape[0]}}."
                    return filter_and_convert_metrics(metrics)
            except Exception as exc:
                metrics['error_message'] = f"Failed to load training data: {{exc}}. Paths: X:{{X_TRAIN_EVAL_PATH}}, Y:{{Y_TRAIN_EVAL_PATH}}"
                return filter_and_convert_metrics(metrics)

            try:
                spec = importlib.util.spec_from_file_location("model_program", program_path)
                if spec is None or spec.loader is None:
                    metrics['error_message'] = f"Could not create spec for module at {{program_path}}"
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
                    metrics['error_message'] = f"Func test: output shape mismatch. Got {{pred_test.shape if isinstance(pred_test, np.ndarray) else type(pred_test)}}, expected ({{num_dummy_samples}},)."
                    return filter_and_convert_metrics(metrics)
                metrics['can_run'] = 1.0
            except TimeoutError as exc:
                metrics['can_run'] = 0.5
                metrics['error_message'] = f"Func execution test timed out: {{exc}}"
                return filter_and_convert_metrics(metrics)
            except FileNotFoundError:
                metrics['error_message'] = f"Model program file not found: {{program_path}}"
                return filter_and_convert_metrics(metrics)
            except Exception as exc:
                metrics['can_run'] = 0.5
                metrics['error_message'] = f"Failed to load or test model function: {{exc}}"
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
                    metrics['error_message'] = f"Optimization did not converge: {{getattr(opt_result, 'message', 'Unknown reason')}}"
            except Exception as exc:
                metrics['raw_mse_train'] = float('inf')
                metrics['error_message'] = f"Error during optimization: {{exc}}"

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
                print(f"Error: Program file '{{program_to_evaluate}}' not found.")
                sys.exit(1)

            print(f"Evaluating model: {{program_to_evaluate}}")
            print(f"Using NUM_INPUT_FEATURES_EXPECTED = {{NUM_INPUT_FEATURES_EXPECTED}}")
            print(f"Using MODEL_NUM_PARAMS_EXPECTED = {{MODEL_NUM_PARAMS_EXPECTED}}")
            print(f"Loading X_train from: {{X_TRAIN_EVAL_PATH}}")
            print(f"Loading y_train from: {{Y_TRAIN_EVAL_PATH}}")

            if not os.path.exists(X_TRAIN_EVAL_PATH):
                print(f"Error: X_train data file '{{X_TRAIN_EVAL_PATH}}' not found.")
                sys.exit(1)
            if not os.path.exists(Y_TRAIN_EVAL_PATH):
                print(f"Error: y_train data file '{{Y_TRAIN_EVAL_PATH}}' not found.")
                sys.exit(1)

            evaluation_results = evaluate(program_to_evaluate)
            print("\\nEvaluation Results:")
            for key, value in evaluation_results.items():
                if isinstance(value, float):
                    print(f"  {{key}}: {{value:.4f}}")
                else:
                    print(f"  {{key}}: {{value}}")
        """
    ).strip() + "\n"


def _config_payload(problem_data: dict) -> dict:
    input_symbols, output_symbols = _input_output_symbols(problem_data)
    desc_map = _desc_map(problem_data)
    output_symbol = output_symbols[0]
    dataset_identifier = problem_data["dataset_identifier"]
    equation_idx = problem_data["equation_idx"]
    input_desc = ", ".join(f"{symbol} ({desc_map.get(symbol, symbol)})" for symbol in input_symbols) or "none"
    system_message = textwrap.dedent(
        f"""\
        Your task is to evolve a Python function `func(x, params)` that models a scientific process, considering the physical meaning and relationships of inputs, by predicting output variables based on input variables.

        The function signature is:

        ```python
        def func(x: np.ndarray, params: np.ndarray) -> np.ndarray:
        ```

        - `x` is a 2D NumPy array of shape `(n_samples, {len(input_symbols)})`
        - `params` is a 1D NumPy array of up to {MODEL_NUM_PARAMS} parameters
        - The function should return a 1D NumPy array of predictions with shape `(n_samples,)`

        **Current Problem:**
        Model the {output_symbol} ({desc_map.get(output_symbol, output_symbol)}) using the input features: {input_desc}
        Thus, `x` contains {len(input_symbols)} columns: {input_desc}.

        The initial version of `func` is a simple linear model. Parameters in `params` will be optimized externally using the BFGS algorithm based on unseen training data.

        Your objective is to evolve `func` to improve predictive performance on unseen data. Aim for a balance between:
        - **Accuracy**: Lower mean squared error (MSE) on training data
        - **Simplicity**: Prefer concise, interpretable expressions

        Model performance (score = -log_10(mse)) will be evaluated on a held-out dataset. Ensure the model is free of potential numerical errors (e.g., log0, division by 0).
        """
    ).strip()

    return {
        "# Configuration for Symbolic Regression Task": f"{dataset_identifier}/{equation_idx}",
        "max_iterations": 200,
        "log_level": "INFO",
        "target_score": "combined_score",
        "checkpoint_interval": 10,
        "llm": {
            "primary_model": "gpt-4o",
            "primary_model_weight": 0.8,
            "secondary_model": "o3",
            "secondary_model_weight": 0.2,
            "api_base": "https://api.openai.com/v1",
        },
        "prompt": {
            "system_message": system_message,
            "num_top_programs": 4,
            "use_template_stochasticity": True,
        },
        "database": {
            "population_size": 70,
            "archive_size": 30,
            "num_islands": 4,
            "elite_selection_ratio": 0.3,
            "exploitation_ratio": 0.6,
        },
        "evaluator": {
            "timeout": 90,
            "cascade_evaluation": False,
            "cascade_thresholds": [1.0],
            "parallel_evaluations": 4,
            "use_llm_feedback": False,
        },
        "diff_based_evolution": True,
        "allow_full_rewrites": False,
    }


def materialize_problem_pack(problem_data: dict, export_root: Path) -> Path:
    dataset_identifier = problem_data["dataset_identifier"]
    equation_idx = str(problem_data["equation_idx"])
    problem_dir = export_root / "problems" / dataset_identifier / equation_idx
    problem_dir.mkdir(parents=True, exist_ok=True)

    train = np.asarray(problem_data["train"], dtype=np.float64)
    test = np.asarray(problem_data["test"], dtype=np.float64)
    ood = problem_data.get("ood_test")
    ood = None if ood is None else np.asarray(ood, dtype=np.float64)

    np.save(problem_dir / "X_train_for_eval.npy", train[:, :-1])
    np.save(problem_dir / "y_train_for_eval.npy", train[:, -1])
    np.save(problem_dir / "X_test_for_eval.npy", test[:, :-1])
    np.save(problem_dir / "y_test_for_eval.npy", test[:, -1])
    if ood is not None and ood.size > 0:
        np.save(problem_dir / "X_ood_test_for_eval.npy", ood[:, :-1])
        np.save(problem_dir / "y_ood_test_for_eval.npy", ood[:, -1])

    (problem_dir / "initial_program.py").write_text(_program_text(problem_data), encoding="utf-8")
    (problem_dir / "evaluator.py").write_text(_evaluator_text(problem_data), encoding="utf-8")
    config_text = yaml.safe_dump(_config_payload(problem_data), sort_keys=False, allow_unicode=True)
    (problem_dir / "config.yaml").write_text(config_text, encoding="utf-8")

    metadata = {
        "dataset_identifier": dataset_identifier,
        "equation_idx": equation_idx,
        "symbols": list(problem_data["symbols"]),
        "symbol_properties": list(problem_data["symbol_properties"]),
        "expression": str(problem_data.get("expression", "")),
    }
    (problem_dir / "problem_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return problem_dir
