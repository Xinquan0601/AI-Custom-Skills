# insights 维护规划（2026-11-05 更新）

> 上一版是待确认的改造草案；D1–D7 已确认，代码与文档已按新结构落地。
> 本文件现在记录：已完成、刻意不做、下一步。

## 一、已完成

| 事项 | 结果 |
|---|---|
| 数据源改为 AgentTrail 导出包（D1） | 删除 zcode / claude / codex 三个直读适配器；新增 `sources/agenttrail.py`（zip/目录流式读取、fingerprint 去重、完整度对账） |
| 结构重排（D3） | `sources/` + `metrics` + `stats` + `compare` + `narrative` + `render/`（view_model / sections / charts / templates）；CLI 只做编排 |
| 报告重设计（D3/D4） | 按「数据 → 判断 → 行动」重排，删掉语义枚举类图表（ADR-0004） |
| 口径修正 | 事件表为主口径；伪用户消息剔除；项目名归并；语言按去重文件；报错按 `tool_call_id` 回填工具名并剥沙箱尾巴 |
| 质量门（D6） | 运行期标准库 only；开发期 pytest + ruff；`pyproject.toml` 落地 |
| 文档 | 新增 README / CHANGELOG / data-source / stats-schema / narratives-schema / ADR-0003 / 0004，重写 SKILL.md 与 CONTEXT.md |
| 卫生 | 删除 2026-08 的旧 history 存档（D5）；`.gitignore` 覆盖 tmp / history / 导出包 zip / 参考项目嵌套仓库 |
| 语义层（ADR-0005） | 新增 `facet plan / merge`：枚举 + digest 逐字证据 + 覆盖率披露；只做判断，不改事实数字。原「不做语义枚举」据此修订——不是让 LLM 直接猜，而是先提取再校验 |
| 1.0 可信性门禁 | 重复导出只披露不改口径（ADR-0006）；叙事数字抽查；展示时区 `--utc-offset` 可配；语义层与降级路径进渲染测试 |

## 二、刻意不做

- **不做无证据的语义枚举**。目标分类、满意度只在 facets 层出现，必须带 digest 逐字证据与覆盖率；没有证据的结论不进报告。
- **不做本机直读兜底**。多一条路就多一套口径，数据问题应回到 AgentTrail 修。
- **不做模型分布图**。各 Agent 的 model 命名不统一，归一化规则尚无共识。
- **不做自动发报告**。宁可留一个明确的 CLI，也不做后台常驻。

## 三、下一步（按收益排序）

1. **语义层章节深化（1.x）**：1.0 已交付独立的「语义层」章节；下一步让项目领域、摩擦、
   建议三章直接引用 facets 的分布与 evidence 原文（当前只做到并列呈现），保留无 facets 时的降级路径。
2. **固定周报节奏**：每周固定时间 `collect` + 写叙事 + `render`，让 `history/` 自动累积环比数据。
3. **报错清单闭环**：每周只看 `friction.categories` 的前两类，改一次工作流（AGENTS.md 规则 / 权限白名单）。
4. **跨 Agent 效率**：在 stats 里加「同类任务的工具调用数 / 返工率」，用来决定分工（现在只有量，没有效率）。
5. **代码行口径**：`run_code` 写文件无法统计行数，考虑从 git diff 补（需要导出包带 commit 信息）。
6. **多包合并**：目前一次只吃一个导出包；多台机器汇总需要合并去重（fingerprint 已具备条件）。

## 四、维护红线

- 改口径必须同时改 `docs/stats-schema.md` 与 `schema_version`；叙事契约变更同步 `narratives-schema.md`。
- 新增指标一律在 `stats.py` 算，render 不许再计算。
- 单文件 >400 行先拆模块；`sections.py` 已接近上限。
- 报告中任何「缺失」都要显式说明，不允许静默补零。
