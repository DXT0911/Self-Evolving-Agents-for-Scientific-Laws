# Hamilton vs PySR v3 development protocol

V3 addresses the principal v2 failure mode: every Hamilton round restarted PySR and
discarded its population and backend state. One workspace-local worker now owns a single
`PySRRegressor(warm_start=True)` for the full task/repeat.

`continuation_schedule_pysr` is not a formal arm. An unchanged segmented warm-start run is
only an implementation-equivalence smoke test against ordinary continuous PySR. If the
two paths are not operationally equivalent, the discrepancy is reported as a runner
property rather than promoted to another scientific treatment.

The four v2 arms remain unchanged. In governed Hamilton, the next action may be:

- `continue`: preserve every scientific config leaf and spend the next allowance on the
  existing population;
- `modify`: change exactly one warm-start-compatible field.

The initially compatible field is `search.parsimony`. `search.maxsize` stays fixed for
the whole session because PySR sizes its saved hall-of-fame state at initialization.
The seed, data, operators, populations, population size, validation, and run directory
remain frozen. A lost worker after round 1 is a hard execution failure; Windows
cross-process state loading is not treated as validated recovery.

Requested evaluations remain per-round ledger reservations. The worker converts their
sum to the cumulative PySR stopping limit and records both cumulative and incremental
engine-measured evaluations. No validation or sealed-test task may run until the
development smoke, no-op closure, parameter-transition tests, and crash behavior pass.
