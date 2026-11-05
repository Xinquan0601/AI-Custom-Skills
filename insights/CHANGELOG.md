# CHANGELOG

## 1.0.0 — 2026-11-05

### 新增

- **语义层 `facet plan` / `facet merge`**：实质会话 → digest → 结构化判断（目标分类、结果、
  摩擦、逐字证据、用户约束），与事实层分离（ADR-0005）；输出 `facets.json` 与聚合摘要。
- 10 类目标分类（按真实数据定制）、4 档结果、7 类摩擦；枚举是唯一来源，提示词与校验共用。
- `evidence` 逐字校验：改写或转述会被 merge 拒掉并逐条进 `warnings`；覆盖率与缺失条数同样披露。
- digest 为每条用户消息配对 Agent 回复（`turns`）并带末条自述（`final_assistant`），
  过滤英文思考草稿、去重复导出事件——结果与摩擦不再只看用户单边发言。
- 多客户端重复导出的同一场对话按「项目 + 用户发言序列」合并，覆盖率改用 `unique_tasks`。
- 报告新增「语义层」章节（`render --facets`）：目标分布、结果达成、摩擦类型、反复约束，
  并披露覆盖率与合并条数；没有 facets 时整章不出现，其余章节不受影响。
- digest 去伪消息、去近似重复、路径去用户名、工具名大小写合并；缓存键覆盖全部真实消息，
  内容不变不重跑，分类表变更则全部失效。
- CLI 增加 `facet`（plan / merge）；`collect` 与 `facet plan` 共用窗口解析，口径一致。

- **可信性门禁（1.0）**：
  - 重复导出披露：`stats.duplicates` 给出组数/条数/其中实质会话数，`warnings` 与语义层章节
    同时写明两个口径（ADR-0006）；统计层不去重，历史环比不受影响。
  - 叙事数字抽查：`validate` / `render` 检查 ≥100 的整数、万/亿量级与百分比能否在
    stats / facets 找到来源，找不到报「疑似编造的数字」。
  - 展示时区可配：`--utc-offset` 与 `INSIGHTS_UTC_OFFSET` 覆盖默认 UTC+8，
    collect / facet plan / render 的日期与小时一致跟随；页脚标出展示时区。
  - 语义层进渲染测试：有 facets 出章节与数值、无 facets 整章不出现、重复导出提示可见。

### 变更

- `SKILL.md` 流程改为五步（facet 可选）；叙事里项目领域、摩擦、建议三章以 facets 为骨架。
- 新增 `docs/facets-schema.md`、`docs/adr/0006-duplicate-export-disclosure.md`、ADR-0005；
  README 目录、快速开始与已知边界同步。

### 测试

- 新增 `test_facets.py`：枚举完整性、digest 确定性与去噪、计划覆盖、缓存失效、merge 校验与聚合。
- 新增重复导出检测、叙事数字校验、时区参数化与语义层渲染的用例（共 123 个）。
## 0.2.0 — 2026-11-05

### 破坏性变更

- **数据源只保留 AgentTrail 导出包**（ADR-0003）。删除 zcode / claude / codex 三个本机直读适配器，
  删除 `--project`、`--output` 等旧参数；`--source` 现在接受 `.zip` 或解压目录。
- `stats.json` `schema_version` 升到 2；`narratives.json` 契约重写（去掉语义枚举，保留 `source`）。
- 报告按「数据 → 判断 → 行动」重排（ADR-0004），不再生成目标分类 / 满意度 / 会话结果等图表。

### 新增

- `now` 子命令：打印本机时间锚点与导出窗口。
- `validate` 子命令：`stats` / `narratives` 契约自检。
- 数据质量 `warnings`：导出窗口前已开始的会话、token 覆盖率、伪用户消息剔除条数，全部进报告。
- 伪用户消息过滤：客户端注入的时间采样说明、图片回显、审批策略通知不计入消息量。
- 工具能力族（exec / edit / read / search / web / agent / other）与每族最常用工具。
- 项目名归并：目录 slug、时间戳目录、`Default Project` 统一成可读名字。
- 报错样本：剥掉导出包附加的 `File sandbox: …` 尾巴，按类型去重取真实样本。
- 报告改为单文件离线 HTML：内联 CSS / JS，图表用 CSS 与 SVG 绘制，无外部字体。
- 报告文件名按覆盖窗口命名（`AI使用洞察报告-20261001-20261031.html`），不再用生成时间戳；
  `--prefix` 可换前缀。
- `friction.empty_text`：统计没有错误正文的报错条数，报告在摩擦区与口径里披露。

### 修复

- 报错类型判定被沙箱尾巴污染（97/112 全归为「权限」）的问题。
- `friction.by_tool` 出现「未知工具」：改为按 `tool_call_id` 回填工具名。
- 语言分布按调用次数累加导致合计超过文件数：改为按去重文件统计。
- 会话标题是伪用户消息时显示为系统提示：改为回填第一条真实用户消息。
- 浮点时长 / 中位数文案精度问题。
- 报错正文为空时不再按工具名猜类型（曾把 32 次空 grep 记成「文件读写失败」），统一记
  「未提供错误详情」。
- 月度报告 Token 卡显示原始 9 位数字：改为 `1.50 亿` 这类缩写。

### 文档

- 新增 `docs/data-source.md`、`docs/stats-schema.md`、`docs/narratives-schema.md`、ADR-0003 / 0004。
- 重写 `SKILL.md`（新 CLI、输出策略、写作纪律），新增 `README.md` 与本文件。
- `CONTEXT.md` 术语表更新，`docs/maintenance-plan.md` 改为状态 + 路线图。

## 0.1.0

- 初版：三源直读（ZCode / Claude Code / Codex）、12 图表报告、SQLite + JSONL 采集。
