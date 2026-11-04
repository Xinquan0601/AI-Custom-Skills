# AI 自建技能

一个目录一个技能，互不依赖。DSH 从 `.dsh/skills/<skill名>/` 加载，本仓库是它的源码。

```
AI自建技能/
  work-report/     工作报告：agenttrail 数据包 -> 周报/月报 + 索引.html
  .dsh/skills/     安装位置（junction 指回上面的目录，已被 .gitignore 忽略）
  link-skills.ps1  把每个技能目录挂到 .dsh/skills/
```

## 新增一个技能

1. 在仓库根建同名目录：`xxx/`，里面至少 `SKILL.md`（frontmatter 要有 `name: xxx`）
2. 可选子目录沿用同一套：`references/` `scripts/` `config/` `templates/` `demo/`
3. 加 `README.md`（怎么用）和 `CHANGELOG.md`（改了什么）
4. `pwsh link-skills.ps1` —— 技能立即出现在 DSH 里，不需要复制文件

技能目录名 = frontmatter 里的 `name` = `.dsh/skills/` 下的目录名，三者必须一致。

## 安装 / 卸载

```powershell
pwsh link-skills.ps1            # 全部挂上（已存在的跳过）
pwsh link-skills.ps1 work-report # 只挂一个
```

用目录 junction 而不是复制：改完源码立即生效，也不会出现两份内容漂移。指向 `null` 的 junction
说明源目录被移动过，删掉 junction 重跑脚本即可。

## 版本与发布

每个技能独立打标签：`git tag work-report-v1.0.0`，版本号同时写进该技能 `SKILL.md` 的 frontmatter
和 `CHANGELOG.md`。技能之间不共享版本号。

## 分支与 worktree

- **平时工作在 `main`**：每个技能是一个独立目录，本来就互不干扰，不需要靠分支隔离
- 只有大改（重写流程、换数据格式）才开短分支：`git switch -c work-report/rewrite-collect`，合完删掉
- 需要同时保留两份工作区时才用 worktree：`git worktree add ..\wt\work-report-v09 work-report-v0.9.0`
  ——比如线上还在用 1.0，同时验证 1.1 的改法，或者要拿老版本对比输出

## 不进仓库的东西

报告产出（周报/月报）、`_素材/` 原始聊天记录、`.dsh/` 安装副本、`__pycache__`。
这些要么是数据，要么是生成物，见 `.gitignore`。
