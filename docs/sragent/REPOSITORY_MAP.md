# SR Agent repository map

Chinese translation: [`REPOSITORY_MAP.zh-CN.md`](REPOSITORY_MAP.zh-CN.md).

This map answers one question: where should a collaborator look or make a change?
It is navigation, not a replacement for the runtime or research contracts linked below.

## Authoritative entry points

| Need | Authoritative path |
|---|---|
| Fork and branch workflow | [`../../WORKSPACE.md`](../../WORKSPACE.md) |
| Hamilton architecture and usage | [`../../playground/hamilton/README.md`](../../playground/hamilton/README.md) |
| Hamilton development workflow | [`../../playground/hamilton/DEVELOPMENT.md`](../../playground/hamilton/DEVELOPMENT.md) |
| Current implementation backlog | [`../../playground/hamilton/TODO.md`](../../playground/hamilton/TODO.md) |
| Scientific and isolation protocol | [`RESEARCH_PROTOCOL.md`](RESEARCH_PROTOCOL.md) |
| Current development configuration | [`../../configs/hamilton/config.yaml`](../../configs/hamilton/config.yaml) |
| Configuration lifecycle and history | [`../../configs/hamilton/README.md`](../../configs/hamilton/README.md) |
| Versioned experiment index | [`../../experiments/README.md`](../../experiments/README.md) |
| Governed-Hamilton comparison | [`../../experiments/hamilton_vs_pysr_governed_search/README.md`](../../experiments/hamilton_vs_pysr_governed_search/README.md) |

## Directory ownership

```text
Self-Evolving-Agents-for-Scientific-Laws/
├── evomaster/                 reusable upstream agent framework and SR skills
├── playground/hamilton/       Hamilton controller, prompts, tests, public template
├── configs/hamilton/          current, diagnostic, frozen historical, experiment configs
├── docs/sragent/              current research contracts and dated historical snapshots
├── experiments/               versioned experiment protocols, adapters, tests, reports
├── runs/                      ignored generated run evidence; never source code
├── paper/                     inherited papers, data, notebooks, and reproduction assets
├── WORKSPACE*.md              fork, remote, branch, and collaboration navigation
└── README*.md                 inherited EvoMaster project overview
```

Framework directories such as `evomaster/`, `examples/`, and the general documents under
`docs/` are inherited from upstream. Hamilton-specific framework changes are allowed only
when required and covered by focused tests.

## Hamilton asset classes

| Class | Location | Policy |
|---|---|---|
| Controller implementation | `playground/hamilton/core/` | Reusable source; behavior changes require tests |
| Runtime prompts | `playground/hamilton/prompts/` | Sole prompt source of truth |
| Public run template | `playground/hamilton/workspace/` | Only task and public training inputs are versioned |
| Current config | `configs/hamilton/config.yaml` | Only integrated development entry |
| Diagnostic config | `configs/hamilton/config_no_pysr.yaml` | Protocol plumbing only; not a scientific baseline |
| Historical configs | Other documented `config_*.yaml` files | Frozen context; do not reuse or silently edit |
| Formal experiment config | Descriptive config linked from an experiment manifest | Permission-gated and frozen per experiment |
| Research protocol | `docs/sragent/RESEARCH_PROTOCOL.md` | Authoritative science and isolation rules |
| Dated reports | Dated files in `docs/sragent/` or an experiment directory | Historical evidence, not current runtime contracts |

Root-level `task_plan.md`, `progress.md`, `findings.md`, and `design.md` are inherited or
historical project notes. They are not Hamilton's runtime L2 memory. Runtime L2 memory is
created inside a run workspace as `plan.md` and `findings.md`.

## Generated and large assets

Generated evidence is intentionally separated from versioned source:

- `runs/` contains complete local run workspaces and logs and is ignored;
- experiment-local `data_cache/`, `prepared_data/`, and `launch_bundle/` are ignored;
- Python, Julia, PySR, checkpoint, and model caches are ignored by the root policy;
- compact reports, manifests, hashes, schemas, and final figures may be versioned;
- controller-private test/OOD assets remain outside Agent workspaces and ignored.

Do not delete local evidence as part of repository cleanup. Archive or remove it only as a
separate, explicitly authorized artifact-management task.

## Safe change rule

Prefer adding an index or correcting a link over moving a frozen config, dated report, or
experiment artifact. A path migration must update imports, manifests, hashes, docs, and
tests together, and must be treated as a separate compatibility change.
