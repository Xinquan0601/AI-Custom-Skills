---
name: insights
version: 1.0.0
description: 把一个 AgentTrail 导出包（agenttrail-*.zip 或解压目录）变成一份单文件 HTML「AI 使用洞察报告」：统计会话、消息、工具调用、项目分布、代码产出、使用节奏与报错，再由 LLM 写叙事。适用于用户给出导出包并要求复盘 AI 使用情况、生成使用周报/月报、分析会话模式或工具效率的场景。
---

# AI 使用洞察报告

用户给出 `agenttrail-*` 导出包并要求复盘时执行本 skill。五步：
**确认窗口 → collect →（可选）facet → 写 narratives → render**，最后在对话里给 Markdown 摘要。

脚本在 `$SKILL_DIR/scripts/`，用 `python` 运行（依次尝试 `python`、`python3`、`py`）。
若 `$SKILL_DIR` 不可用，先用 Read / ls 定位本 SKILL.md 所在目录。
中间产物放 `$SKILL_DIR/tmp/`，最终报告放 `$SKILL_DIR/reports/`（或用户指定目录）。

**约定：**
- 数据源只有导出包。不要读 `~/.zcode`、`~/.claude`、`~/.codex` 等客户端目录（ADR-0003）。
- 运行期只用 Python 标准库；报告必须离线可开，不引外部字体/CDN。
- 报告永不覆盖已有文件；不删除、不改名用户以前的报告。

## 第一步：确认窗口

先拿锚点，再决定窗口。**不要凭记忆猜日期。**

```bash
python "$SKILL_DIR/scripts/insights_report.py" now --source "<导出包路径>"
```

输出本机今天、本周一、上周、本月，以及导出包的实际窗口（UTC+8）。
默认窗口 = 导出包窗口；用户说法与导出窗口不一致时，用显式参数收窄：

| 用户说法 | 参数 |
|---|---|
| （没说） | 不加参数，用导出窗口 |
| 本周 / 上周 | `--week this` / `--week last` |
| 本月 | `--month this` |
| 10-30 到 11-02、30 号到 2 号 | `--since 2026-10-30 --until 2026-11-02` |
| 最近 3 天 | `--days 3` |
| 导出包全部 | `--all` |

规则：
- 窗口是**本地自然日**（默认 UTC+8，可用 `--utc-offset` 或环境变量 `INSIGHTS_UTC_OFFSET` 改），
  会话只要有**一条真实用户消息**落在窗口内就整会话纳入。
- 用户要的窗口超出导出范围时，脚本会裁剪到导出窗口并打 `clamped`；**在回复里说明被裁剪了**。
- 动手前用一句话写出你理解的窗口（如「统计 10-30 至 11-02」），再进下一步。

## 第二步：collect

```bash
python "$SKILL_DIR/scripts/insights_report.py" collect \
  --source "<导出包路径>" \
  --out "$SKILL_DIR/tmp/stats.json" \
  [--since/--until/--days/--week/--month/--all] [--utc-offset 8]
```

展示时区默认 UTC+8；跨时区（或想对齐别的报表）时加 `--utc-offset 0` 之类的偏移，
collect、facet plan、render 的日期与小时都会跟随。

跑完逐项核对（不满足就停下）：

1. 第一行 `窗口：…（N 天）` 与第一步一致；
2. `会话 N（实质 A / 快速 B）` 的 A+B = N；
3. 每个 `[warn]` 都读一遍——它们是报告「数据说明」的来源，写叙事时要用到；
4. `stats → …` 路径就是下一步的输入，**不要复用旧的 stats.json**。

`stats.json` 的字段与口径见 `docs/stats-schema.md`。几个必须记住的口径：

- 消息量 / 工具量 / 代码行 / 报错**全部按事件表统计**；`sessions.csv` 的会话级合计只用于对账。
- 实质会话 = 真实用户消息 ≥2 条且时长 ≥1 分钟（ADR-0001）；其余计入「快速问答」。
- 客户端注入的伪用户消息（时间采样说明、图片回显、审批策略通知）已剔除，剔除条数在 `warnings`。
- token 只有部分会话上报，合计值仅作量级参考——**不要**把「只有 54/94 个会话有记录」写成「token 用得少」。
- 代码行来自工具入参里的 diff/patch；通过 `run_code` 写文件的改动只能在文件级体现。
- 同一场对话被多个客户端重复导出时，`stats.duplicates` 给出组数与条数，并以 `[warn]` 提示；
  会话数按原始数据统计、未去重，**不要**自己手算去重后的会话数。

## 第三步（可选）：facet —— 会话语义层

叙事要「每条判断都有会话证据」时先跑语义层；只要纯统计报告可以跳过。

```bash
python "$SKILL_DIR/scripts/insights_report.py" facet plan \
  --source "<导出包路径>" --out "$SKILL_DIR/tmp/facets-tasks.json"

# 按 tasks[i].prompt 逐会话提取，产出 results.json（契约见 docs/facets-schema.md）

python "$SKILL_DIR/scripts/insights_report.py" facet merge \
  --tasks "$SKILL_DIR/tmp/facets-tasks.json" \
  --results "$SKILL_DIR/tmp/facets-results.json" \
  --out "$SKILL_DIR/tmp/facets.json" --summary "$SKILL_DIR/tmp/facets-summary.json"
```

规则：

- 只对**实质会话**提取，快速问答跳过；覆盖率（如 100/165）必须写进报告。
- `goal_category` / `outcome` / `friction` 只能取枚举值；`evidence` 必须逐字出自 digest，
  转述会被 merge 拒掉并进 `warnings`。
- 同一场对话被多个客户端各导出一份时（`opencode-local:` 前缀版与原始 id 版），merge 按
  「项目 + 用户发言序列」合并成一条，`coverage.duplicates_merged` 记录合并数；真实会话数看
  `coverage.unique_tasks`，不要拿任务条数当会话数。
- facets 是判断，不是统计：**不要**用它替换 stats 里的会话数、消息数、代码行。
- 结果按 `cache_key` 缓存，会话内容没变不必重跑；分类表变了才会全部失效。
## 第四步：写 narratives.json

基于 `stats.json`（尤其 `narrative_material` 与 `sessions`）写 `$SKILL_DIR/tmp/narratives.json`；
有 `facets.json` 时，项目领域、摩擦、建议三章以它的分布为骨架，并引用 facet 的 `evidence` 原文。
完整契约见 `docs/narratives-schema.md`，`schema_version` 必须是 `2`。

必填区块：`overview`、`project_areas`、`interaction_style`、`what_works`、
`friction_analysis`、`suggestions`、`on_the_horizon`、`fun_ending`。
`comparison_narrative` 只有周报 / 月报且找到上期时才写。

写作纪律（逐条对照，写完自查）：

1. **数字必须能在 stats.json 找到**：`validate` 会抽查 ≥100 的整数、万/亿、百分比，
   找不到就报「疑似编造的数字」。写「你经常…」之前先看 `narrative_material`，
   至少两个会话支撑才算模式；单个案例就写成案例。
2. **每条判断带 `source`**：会话标题片段、真实用户消息片段或会话 ID 前缀（≥8 位）。
   render 会校验，找不到会打 `[warn] 疑似编造的引用`——被警告就回去改，不要清空 `source`。
3. **不重复图表里的数字**。总览写模式与证据（「你把 AI 当执行者：8632 次调用里 6087 次是跑命令」），
   不写「本周共 345 条消息」。
4. **数据缺失 ≠ 数据为零**。缺就写清「只有 N/M 个会话有记录」。
5. **第二人称、中文、教练口吻**；不评价用户本人，只评价工作方式。
6. **建议要能落地**：`agents_md_additions` 给可直接粘进 `AGENTS.md` 的一行；
   `features_to_try` 只推荐本机确实在用的 Agent 能力。
7. `fun_ending` 写一个具体瞬间（某天只说了 1 句、某个凌晨的连续追问），不要写统计句。

写完可用 `validate` 自检：

```bash
python "$SKILL_DIR/scripts/insights_report.py" validate \
  --stats "$SKILL_DIR/tmp/stats.json" --narratives "$SKILL_DIR/tmp/narratives.json" \
  --facets "$SKILL_DIR/tmp/facets.json"   # 有 facets 时一起给，百分比才能对上来源
```

## 第五步：render

```bash
python "$SKILL_DIR/scripts/insights_report.py" render \
  --stats "$SKILL_DIR/tmp/stats.json" \
  --narratives "$SKILL_DIR/tmp/narratives.json" \
  --facets "$SKILL_DIR/tmp/facets.json" \
  --out "$SKILL_DIR/reports"
```

没有 facets 时去掉 `--facets`，报告照常生成，只是少一个语义层章节。

- 输出按覆盖窗口命名：`AI使用洞察报告-<since>-<until>.html`（如 `AI使用洞察报告-20261001-20261031.html`），
  同名已存在时自动加 `-2`、`-3`，永不覆盖；`--prefix` 可换前缀（如 `周报-20261030-20261105.html`）。
- render 会打印 `[warn]`（空的叙事字段、可疑的 source），按提示修 narratives 后重跑。
- 报告结构：封面与统计卡 → 总览四件事 → 环比 → Agent 分工 → 项目 → 工具 → 产出 →
  节奏 → 摩擦 → 语义层（有 facets 时）→ 规格（风格 / 亮点 / 复盘 / 建议 / 展望 / 趣味）→ 口径页脚。
- 交付前用浏览器（或 headless）打开确认：区块顺序正常、没有横向溢出、页脚在最后。

## 第六步：对话摘要

在对话里用 Markdown 给一份短摘要：窗口、会话与消息量（含实质/快速拆分）、
2–3 个项目在做什么、1–2 条亮点与摩擦（引真实例子）、报告文件链接。
细节留给 HTML，摘要不超过 15 行。
