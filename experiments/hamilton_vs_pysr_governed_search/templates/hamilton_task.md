# Frozen governed-search comparison task

This file is a safety fallback. A launch workspace must replace it with a generated,
task-specific `task.md` whose SHA-256 appears in the launch bundle.

Do not start Discovery from this fallback file.

The runtime task must provide:

- one opaque public input and its allowed columns;
- the exact round-1 baseline runner JSON;
- a three-round, 12,000-evaluation cumulative contract;
- deterministic Promotion and continuation requirements;
- no reference equation, source dataset name, private test, or OOD information.
