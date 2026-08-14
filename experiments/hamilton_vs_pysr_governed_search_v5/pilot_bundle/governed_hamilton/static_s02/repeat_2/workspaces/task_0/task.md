# Frozen full Hamilton v5 pilot

Task `static_s02`, pair `repeat_2`, seed `8302`. Use only the governed runner and
`input/data.csv`; never read raw rows, hidden truth, VIV, sealed/OOD data, or identify
the source. The feature columns (x1, x2, x3, x4) are opaque predictors and y is the target. t is a deterministic ordering index and is not a scientific input.

Run three persistent warm rounds of 1500 requested evaluations. One compressed
DeepSeek-V4-Flash planner call follows each completed round. Its proposal is advisory;
the frozen controller owns actions, patches, budget, retention, and rollback.
