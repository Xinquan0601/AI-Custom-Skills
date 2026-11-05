# insights · AI 使用洞察报告

把 AgentTrail 导出包（`agenttrail-*.zip`）变成一份可离线打开的单文件 HTML 复盘报告。

- **数据源只有一个**：AgentTrail 导出包，不读任何客户端私有目录（ADR-0003）。
- **脚本只算事实**：`collect` 产出 `stats.json`；LLM 只写叙事 `narratives.json`；`render` 只组装 HTML。
- **可追溯**：叙事里的每条判断都要带 `source`，指向真实会话或原话，渲染时校验。
- **语义层可选**：`facet plan/merge` 为实质会话产出结构化判断，证据须逐字出自会话，
  覆盖率写进报告；不跑也照常出统计报告。
- **诚实**：导出包的截断、token 覆盖、伪用户消息，都会写进报告而不是藏起来。

## 快速开始

```bash
# 0) 先看时间锚点与导出窗口（供判断「本周 / 最近」）
python insights/scripts/insights_report.py now \
  --source insights/data/agenttrail-20261105-102525.zip

# 1) 统计
python insights/scripts/insights_report.py collect \
  --source insights/data/agenttrail-20261105-102525.zip \
  --out insights/tmp/stats.json
#    展示时区默认 UTC+8，跨时区用 --utc-offset 0 或 INSIGHTS_UTC_OFFSET

# 2) 可选：语义层（先 plan，再按提示词提取，最后 merge）
python insights/scripts/insights_report.py facet plan \
  --source insights/data/agenttrail-20261105-102525.zip \
  --out insights/tmp/facets-tasks.json
#    产出 insights/tmp/facets-results.json 后：
python insights/scripts/insights_report.py facet merge \
  --tasks insights/tmp/facets-tasks.json \
  --results insights/tmp/facets-results.json \
  --out insights/tmp/facets.json

# 3) 写叙事（LLM 完成，见 docs/narratives-schema.md）
#    产出 insights/tmp/narratives.json

# 4) 渲染
python insights/scripts/insights_report.py render \
  --facets insights/tmp/facets.json \
  --stats insights/tmp/stats.json \
  --narratives insights/tmp/narratives.json \
  --out insights/reports

# 5) 可选：只做契约自检
python insights/scripts/insights_report.py validate \
  --stats insights/tmp/stats.json --narratives insights/tmp/narratives.json \
  --facets insights/tmp/facets.json
```

产物：`insights/reports/AI使用洞察报告-<since>-<until>.html`，按覆盖窗口命名（如
`AI使用洞察报告-20261001-20261031.html`），永不覆盖已有文件。

## 目录

```
insights/
  SKILL.md                    # 给 LLM 的执行流程与写作纪律
  README.md  CHANGELOG.md  CONTEXT.md
  docs/
    data-source.md            # 导出包契约（字段、窗口、完整度）
    stats-schema.md           # stats.json 字段与口径
    narratives-schema.md      # narratives.json 契约与 source 规则
    facets-schema.md          # 语义层：分类表、digest、tasks/results、校验
    adr/                      # 0001 实质会话 · 0002 环比 · 0003 单一数据源 · 0004 报告重排 · 0005 语义层
    REFS.md  maintenance-plan.md
  scripts/
    insights_report.py        # 薄 CLI：now / collect / facet / render / validate
    insights_core/
      constants.py            # 阈值、标签、能力族、错误分类
      model.py                # Event / SessionMeta / SessionMetrics / 归并规则
      window.py               # 窗口解析与裁剪
      sources/                # base.Bundle + agenttrail 适配器
      metrics.py              # 会话级指标
      stats.py                # 全局聚合 → stats.json
      compare.py              # 环比（按周期类型找上期）
      facets.py               # 语义层：digest、分类表、tasks/merge 校验与聚合
      narrative.py            # narratives 契约与证据校验
      render/                 # view_model / sections / charts / templates
    tests/                    # pytest
```

本地目录（不入库，删掉也能重建）：

- `data/` 放 AgentTrail 导出包；`tmp/` 放 stats.json、facets、narratives；
- `reports/` 放生成的 HTML 报告，按覆盖窗口命名。

## 质量门

仅开发时需要，运行只需要 Python 3.10+ 标准库：

```bash
python -m pytest insights/scripts/tests -q
ruff check insights/scripts
```

- 运行期 **零第三方依赖**（标准库 only），报告 **零外部资源**（CSS/JS/图表全部内联）。
- 单文件尽量 ≤400 行；超过就拆模块，而不是继续堆。
- 改口径必须同步 `docs/stats-schema.md` 并升 `schema_version`。

## 已知边界

- 代码行统计依赖工具入参里的 diff/patch，通过 `run_code` 写文件的改动只能在文件级体现。
- token 只有部分会话上报，合计值仅作量级参考。
- 导出窗口开始前就已开始的会话，事件可能被截断；程序对账后会在报告里说明。
- 语义层只覆盖实质会话（默认最多 200 个），覆盖率会写进报告，不会把未提取当成「没问题」。
