# Public Tier-0 VIV Long-Horizon Calibration — 2026-08-12

This report records post-hoc calibration of the deterministic long-horizon verifier. It is
not preregistered evidence and does not authorize a new Hamilton, PySR/Julia, LLM, or
private/OOD run.

## Scope

- Public data only: `playground/hamilton/workspace/input/U248_train.csv`.
- Frozen candidates: the seven completed U248 checkpoints from the public operational gate
  (`governed_hamilton` rounds 1--3, ordinary PySR endpoint, and fixed-schedule episodes 1--3).
- Unique equations: five; all are near-linear position-only restoring laws.
- Public split: first 80% discovery, final 20% contiguous validation.
- Validation interval: approximately 239.70--299.49 seconds.
- No LLM, PySR, Julia, private test, or OOD access.

The ignored machine-readable report is generated at
`launch_bundle/offline_analysis/viv_long_horizon_replay.json` by:

```powershell
python -m experiments.hamilton_vs_pysr_governed_search.viv_long_horizon_replay
```

## Calibration profiles

The primary profile uses a 60-second DOP853 integration, 3,000 output points, the final 40%
as the steady window, at least three cycles, exact-zero initial state as `report_only`, and a
large initial state equal to twice the discovery-block robust state scale. Sensitivity profiles
change one dimension at a time:

- steady window 30%;
- steady window 50%;
- 6,000 output points with the 40% window.

Scientific tolerances are held fixed across profiles. Long-horizon evidence remains diagnostic;
this calibration does not freeze a non-zero ranking weight.

Numerically successful candidates receive a continuous penalty equal to the mean of reference
amplitude/frequency, required-rollout stationarity, and attractor amplitude/frequency components.
The hard failure penalty is reserved for catastrophic integration failure, so stable but
scientifically incomplete candidates retain a useful search gradient.

## Synthetic calibration

Offline tests cover:

- a stable damped equilibrium reached from multiple initial states;
- a Van der Pol limit cycle reached from distinct non-zero initial states while exact zero is
  reported separately;
- an unstable candidate exceeding deterministic integration limits;
- slow drift rejection;
- insufficient-cycle frequency rejection;
- non-uniform public time-grid resampling;
- harmonic amplitude/frequency extraction and structured attractor mismatch.

## Historical U248 replay

All seven checkpoints produced the same categorical verdict under every calibration profile:

| Property | Result |
|---|---|
| Integration | 7/7 passed |
| Steady-window stability | 7/7 passed |
| Public validation amplitude/frequency match | 7/7 passed |
| Attractor consistency from observed versus large initial state | 0/7 passed |
| Overall long-horizon gate | 0/7 passed |

Under the primary profile, amplitude relative error ranged from about 0.7% to 1.2%, and dominant
frequency relative error ranged from about 0.4% to 2.4%. Every candidate failed only with
`attractor_mismatch`.

The continuous primary-profile penalties ranged from approximately 0.1071 to 0.1104 rather than
collapsing every failed gate to the same hard penalty. Window/resolution sensitivity changed each
candidate's penalty by at most about 0.0039 and did not change any categorical verdict.

This is the expected diagnostic signature of the discovered near-linear conservative oscillators:
they can reproduce the amplitude and frequency of one observed periodic trajectory, but their
long-term amplitude depends on the initial energy. They do not recover a self-excited amplitude
selection mechanism or a common attracting limit cycle.

## Interpretation and limitations

The replay demonstrates that the new verifier detects a scientifically important failure that
pointwise validation and the previous short rollout did not expose. It does not demonstrate that
dynamics-aware Hamilton will discover a better equation. The seven checkpoints are correlated,
post-hoc, and derived from one public operating condition. No private/OOD claim is supported.

Before a new comparison run, create a new versioned experiment rather than reusing the consumed
pilot manifest. Freeze direct PySR, fit-only Hamilton, and dynamics-aware Hamilton configurations;
the public task/repeat scope and seeds; cumulative evaluation and LLM token budgets; the long-
horizon profile and score weight; failure penalties; actual-evaluation/AUC measurement; persistent
background logging; and the statistical analysis plan.
