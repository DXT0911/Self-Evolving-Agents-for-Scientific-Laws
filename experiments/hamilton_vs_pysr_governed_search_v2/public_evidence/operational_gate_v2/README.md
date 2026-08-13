# Hamilton vs PySR v2 operational-gate evidence

This is the compact, public, post-run evidence for the two-task, one-repeat
operational gate. It is an engineering and falsification gate, not a
confirmatory benchmark.

- `analysis/operational_gate_summary.csv` is the human-readable endpoint table.
- `analysis/operational_gate_summary.json` also contains controller-only
  challenge-grid equivalence results and engine-measured anytime curves.
- `paired_budget_traces/` proves that all four arms received the same frozen
  requested-evaluation schedule or total.
- `provenance.json` binds the evidence to protocol, controller, runner, and
  result hashes and records the zero-evaluation Julia sandbox startup incident.

Selection is by the frozen `scientific_score`; validation NRMSE is reported
separately. For episodic arms, the best completed episode is the terminal
incumbent. Engine evaluations come from PySR/SymbolicRegression telemetry and
therefore may exceed the requested cap because the engine reports batched
work. No arm recovered the exact registered ground-truth equation.
