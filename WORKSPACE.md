# Personal Research Workspace

[English](./WORKSPACE.md) | [简体中文](./WORKSPACE.zh-CN.md)

This fork is the canonical working repository for DXT0911's SR Agent research.

## Repository roles

- `origin`: personal GitHub fork, `DXT0911/Self-Evolving-Agents-for-Scientific-Laws`
- `upstream`: collaborator repository, `HyNlity/Self-Evolving-Agents-for-Scientific-Laws`
- `main`: clean mirror/integration branch; do not develop directly on it
- `sragent/summer-2026`: current SR Agent research branch

## SR Agent entry points

| Path | Purpose |
|---|---|
| `playground/hamilton/` | Hamilton SR Agent implementation |
| `playground/hamilton/DEVELOPMENT.md` | Collaborator guide and directory ownership |
| `playground/hamilton/core/` | Multi-round orchestration and experiment execution |
| `playground/hamilton/prompts/` | Agent prompts |
| `playground/hamilton/workspace/task.md` | Current VIV equation-family task |
| `playground/hamilton/workspace/input/` | Versioned public VIV training inputs only |
| `playground/hamilton/benchmarks/*/private/` | Ignored controller-only test/OOD assets; never commit |
| `evomaster/skills/pysr/` | PySR knowledge and execution guidance |
| `configs/hamilton/` | Hamilton runtime configuration |
| `docs/sragent/RESEARCH_PROTOCOL.md` | Research scope, data split, experiment and reporting rules |
| `docs/sragent/README.md` | Current contracts versus historical experiment documents |
| `playground/hamilton/TODO.md` | Required implementation progress log |

## Upstream framework paths

The following directories are primarily inherited framework or reference material. Avoid
unrelated changes so that upstream synchronization remains manageable:

- `evomaster/`
- `examples/`
- `docs/`
- `paper/`
- `ml-master-skills/`
- `planning-with-files/`

Changes to framework code are allowed when required by the SR Agent, but each such change
must be covered by a focused test and explained in the commit message.

## Daily workflow

Start:

```powershell
git status -sb
git switch sragent/summer-2026
```

Before editing:

```powershell
git fetch --all --prune
```

After a coherent, tested change:

```powershell
git add <specific-files>
git diff --cached
git commit -m "feat(sragent): <short description>"
git push -u origin sragent/summer-2026
```

Do not commit API keys, `.env`, virtual environments, Julia/PySR caches, raw run
directories, private benchmark assets, or large intermediate artifacts.

## Synchronizing with the collaborator

`upstream` is fetch-only to prevent accidental direct pushes. Keep `main` aligned with it:

```powershell
git switch main
git pull --ff-only upstream main
git push origin main
git switch sragent/summer-2026
git rebase main
```

If the research branch is already shared with others, merge `main` into it instead of
rebasing.
