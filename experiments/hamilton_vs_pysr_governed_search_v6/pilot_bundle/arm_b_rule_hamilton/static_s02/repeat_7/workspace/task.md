# Frozen v6 three-arm ablation pilot

Task `static_s02`, pair `repeat_7`, seed `8407`, arm `arm_b_rule_hamilton`. Use only the governed
runner and `input/data.csv`; never read raw rows, hidden truth, VIV, sealed/OOD data,
or identify the source. The feature columns (x1, x2, x3, x4) are opaque predictors and y is the target. t is a deterministic ordering index and is not a scientific input.

Run 3 persistent warm rounds of 1500 requested evaluations. The frozen
controller owns budgets, retention, and rollback. Arm A always continues; arm B uses a
deterministic rule intervention; arm C calls exactly one compressed planner per
intervention round and the controller adopts or rejects its atomic action.
