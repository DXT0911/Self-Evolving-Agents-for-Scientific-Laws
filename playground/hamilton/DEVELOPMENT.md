# Hamilton collaborative development guide

This document defines the supported entry points and ownership boundaries for Hamilton.
Read it before changing orchestration, prompts, experiment governance, or runner schemas.

## Start here

1. Read `docs/sragent/RESEARCH_PROTOCOL.md`.
2. Read `playground/hamilton/README.md` for the runtime architecture.
3. Read `playground/hamilton/TODO.md` for completed and pending research work.
4. Use `configs/hamilton/config.yaml` for current development.
5. Create a new named configuration for a formal experiment; never repurpose a frozen
   historical configuration.

## Directory ownership

| Path | Responsibility |
|---|---|
| `playground/hamilton/core/` | Multi-round controller, Promotion, closure, OOD and search-control logic |
| `playground/hamilton/prompts/` | Single source of truth for all Hamilton runtime prompts |
| `playground/hamilton/workspace/` | Clean public template copied into a run workspace |
| `configs/hamilton/` | Runtime configuration catalog and small reproducibility inputs |
| `evomaster/skills/run-sr-experiment/` | Deterministic SR runner and its machine-readable contract |
| `docs/sragent/` | Protocol, current handoff, experiment specifications and historical audits |
| `runs/` | Generated evidence; normally ignored and never used as source code |

Private test/OOD assets belong outside the Agent workspace under
`playground/hamilton/benchmarks/<name>/private/`. They must remain ignored and must never
be committed.

## Configuration policy

- `config.yaml` is the only supported integrated development entry.
- `config_no_pysr.yaml` checks protocol plumbing only. It is not a scientific baseline.
- Other `config_*.yaml` files are frozen records of earlier smoke, long-run, or recovery
  workflows. Some contain workspace-relative resume state and are not portable.
- A formal experiment gets a new descriptive config, a frozen total budget, a task
  specification in `docs/sragent/`, and a fresh run directory.
- Credentials are supplied only through `HAMILTON_API_KEY`; never commit literal keys.

Relative prompt paths in Hamilton configs are resolved to
`playground/hamilton/prompts/`. Do not add a second prompt tree under `configs/`.

## Controller boundaries

The LLM proposes one machine-readable PySR configuration for the next round from L2
memory. The deterministic controller remains responsible for:

- schema and path validation;
- cumulative evaluation accounting and dynamic allowance;
- trust-region checks, incumbent persistence, and rollback;
- result freezing and Promotion recovery;
- search-advancement gates versus final scientific-success gates;
- residual/OOD evidence release and closure audits.

The LLM may interpret released evidence and form a falsifiable next-round contract, but it
must not bypass those controller checks.

## Change workflow

Keep each change focused and update the closest contract:

- controller behavior: add or update a focused test in `playground/hamilton/core/`;
- runner schema: update the runner reference and its contract tests together;
- prompt behavior: update the runtime prompt and any affected closure test;
- experiment protocol: update `docs/sragent/RESEARCH_PROTOCOL.md` and create a new task
  specification when necessary.

Run the offline Hamilton tests before committing:

```powershell
python -m unittest playground.hamilton.core.test_config_catalog `
  playground.hamilton.core.test_pysr_preflight `
  playground.hamilton.core.test_standard_runner
```

These tests must not call DeepSeek, run PySR/Julia, or access private test/OOD data.
Before sharing a commit, inspect `git status -sb` and `git diff --check`, stage only the
intended files, and record generated evidence separately from implementation changes.
