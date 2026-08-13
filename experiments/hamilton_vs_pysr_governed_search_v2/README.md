# Hamilton versus PySR governed search v2

Status: `frozen_pre_execution`

This experiment is the versioned successor to the completed v1 operational gate. It
excludes VIV and tests whether residual-guided, governed search control contributes more
than an uninterrupted PySR run, matched restart/seed diversity, or access to the full
operator envelope from the first episode.

The four goals are:

1. lower terminal public validation NRMSE;
2. higher controller-only ground-truth recovery rate and lower catastrophic-failure rate;
3. lower engine-measured evaluations to a fixed quality threshold and lower anytime AUC;
4. bounded and explicitly reported DeepSeek token and wall-clock overhead.

Read `PROTOCOL.md` and `dataset_split.yaml` before changing code. Development tasks may be
used to repair and tune the controller. Validation tasks may select one final policy.
Test-task outcomes are opened only after code, policy, metrics, seeds, and budgets have been
frozen. Test outcomes never feed another v2 search change.

Generated data, launch bundles, full workspaces, checkpoints, and provider logs remain
Git-ignored. Compact result records, environment locks, reports, and final figures are
versioned.
