# Frozen v6 three-arm ablation pilot

Task `dynamic_d01`, pair `repeat_8`, seed `8408`, arm `arm_b_rule_hamilton`. Use only the governed
runner and `input/data.csv`; never read raw rows, hidden truth, VIV, sealed/OOD data,
or identify the source. The feature columns (x1, x2) are state variables and y is one state derivative. t preserves source-row order; it is not evidence for a physical-time rollout.

Run 3 persistent warm rounds of 1500 requested evaluations. The frozen
controller owns budgets, retention, and rollback. Arm A always continues; arm B uses a
deterministic rule intervention; arm C calls exactly one compressed planner per
intervention round and the controller adopts or rejects its atomic action.
