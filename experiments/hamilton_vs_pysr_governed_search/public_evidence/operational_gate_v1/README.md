# Public evidence package: operational gate v1

This directory is a compact, path-safe export of the completed three-task,
one-repeat Hamilton-versus-PySR operational gate. It supports review and handoff; it does
not turn the pilot into a formal multi-repeat benchmark.

Included:

- selected-candidate metrics and search configurations at every completed boundary;
- compact residual diagnostics and public short-ODE summaries;
- deterministic Promotion closure decisions;
- paired requested-evaluation budget traces;
- environment versions, data fingerprints, timestamps, and file checksums;
- post-hoc boundary curves and controller-only ground-truth checks in `analysis/`.

Excluded by construction:

- raw public datasets and all private/OOD assets;
- LLM prompts, transcripts, chain-of-thought, and full workspaces;
- absolute paths, API keys, attempt UUIDs, caches, and PySR equation tables.

The package is regenerated from an existing ignored launch bundle with:

```powershell
python -m experiments.hamilton_vs_pysr_governed_search.export_public_evidence `
  --source <path-to-launch_bundle> `
  --output experiments/hamilton_vs_pysr_governed_search/public_evidence/operational_gate_v1
```

`manifest.json` lists every exported record and its SHA-256 checksum. The source scientific
claim remains the one in `OPERATIONAL_GATE_STATUS_2026-07-28.md`: mixed, task-dependent
positive signals from a runtime pilot, not proof that Hamilton generally outperforms PySR.
