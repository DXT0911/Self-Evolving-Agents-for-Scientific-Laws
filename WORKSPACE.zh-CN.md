# 个人研究工作区

[English](./WORKSPACE.md) | [简体中文](./WORKSPACE.zh-CN.md)

这个 fork 是 DXT0911 开展 SR Agent 研究的主要工作仓库。

## 仓库与分支的用途

- `origin`：个人 GitHub fork，即 `DXT0911/Self-Evolving-Agents-for-Scientific-Laws`
- `upstream`：协作者仓库，即 `HyNlity/Self-Evolving-Agents-for-Scientific-Laws`
- `main`：保持整洁的镜像与集成分支，不要直接在此分支开发
- `sragent/summer-2026`：当前开展 SR Agent 研究的分支

## SR Agent 主要入口

| 路径 | 用途 |
|---|---|
| `playground/hamilton/` | Hamilton SR Agent 的实现 |
| `playground/hamilton/core/` | 多轮智能体编排与实验执行 |
| `playground/hamilton/prompts/` | 智能体提示词 |
| `playground/hamilton/workspace/task.md` | 当前的 VIV 方程族发现任务 |
| `playground/hamilton/workspace/input/` | 纳入版本控制的公开 VIV 训练输入，仅限训练集 |
| `playground/hamilton/benchmarks/*/private/` | Git 忽略的 controller 私有 test/OOD 资产，禁止提交 |
| `evomaster/skills/pysr/` | PySR 相关知识与执行指南 |
| `configs/hamilton/` | Hamilton 运行配置 |
| `docs/sragent/RESEARCH_PROTOCOL.md` | 研究范围、数据划分、实验与报告规范 |
| `playground/hamilton/TODO.md` | 必须维护的实现进度记录 |

## 上游框架目录

以下目录主要是从上游继承的框架代码或参考资料。应避免无关改动，以便后续能够顺利同步上游：

- `evomaster/`
- `examples/`
- `docs/`
- `paper/`
- `ml-master-skills/`
- `planning-with-files/`

如果 SR Agent 的实现确实需要修改框架代码，可以进行修改，但每一项修改都必须配有针对性的测试，并在提交信息中说明原因。

## 日常工作流程

开始工作：

```powershell
git status -sb
git switch sragent/summer-2026
```

编辑前：

```powershell
git fetch --all --prune
```

完成一组逻辑完整且经过测试的改动后：

```powershell
git add <具体文件>
git diff --cached
git commit -m "feat(sragent): <简短说明>"
git push -u origin sragent/summer-2026
```

不要提交 API 密钥、`.env` 文件、虚拟环境、Julia/PySR 缓存、原始运行目录、私有 benchmark
资产或体积较大的中间产物。

## 与协作者仓库同步

`upstream` 被设置为只能拉取，以防误将内容直接推送到协作者仓库。应按以下方式让 `main` 与上游保持一致：

```powershell
git switch main
git pull --ff-only upstream main
git push origin main
git switch sragent/summer-2026
git rebase main
```

如果研究分支已经与其他人共享，则不要对它执行 rebase；应改为把 `main` 合并到研究分支中。
