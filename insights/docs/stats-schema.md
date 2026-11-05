# stats.json 契约

`collect` 的唯一产物，也是 `render` 的唯一数据输入。render **不做任何再计算**，
只把这里的事实组织成 HTML。契约由 `stats.check_stats()` 强制，缺字段直接报错。

`schema_version` 当前为 `2`。字段只增不改；删字段必须升版本并同步本文档。

## 顶层

| 键 | 类型 | 说明 |
|---|---|---|
| `schema_version` | int | 结构版本 |
| `generated_at` | str | 生成时间（本机时区，ISO） |
| `source` | obj | 数据源：`kind` / `path` / `export_version` / `exported_at` / `export_window` / `counts` / `agents` / `warnings` |
| `window` | obj | `since` / `until`（本地日期）/ `days` / `description` / `period`（`week`、`month` 或 null）/ `source`（`bundle`、`requested`、`requested-clamped`、`all`）/ `clamped` / `timezone` |
| `totals` | obj | 全局合计，见下 |
| `agents` | array | 每个 Agent 一行 |
| `projects` | array | 每个项目一行（已归并别名） |
| `tools` | obj | `families` / `by_agent` / `top_tools` / `by_family` |
| `code` | obj | `files` / `languages` / `lines_added` / `lines_removed` / `git_commits` / `git_pushes` / `sessions_with_files` |
| `rhythm` | obj | `hours`（24 格）/ `daily`（`date`、`messages`、`sessions`）/ `response_times` / 两个中位数均值 |
| `parallel` | obj | `overlap_pairs` / `sessions_involved` / `messages_involved` / `messages_total` / `message_share` |
| `friction` | obj | `tool_errors` / `error_rate` / `incomplete_results` / `empty_text` / `categories` / `by_agent` / `by_tool` / `examples` |
| `sessions` | array | 会话明细，见下 |
| `narrative_material` | obj | 给 LLM 的证据集：`repeated_projects` / `tool_combos` / `error_categories` / `session_samples` |
| `warnings` | array | 数据质量说明，原样进报告的「数据说明」 |
| `duplicates` | obj | 多客户端重复导出：`groups` / `extra_sessions` / `extra_substantive` / `clients`（如 `opencode-local`）。按「项目 + 去掉客户端前缀的会话 id」认亲；**不改写 totals**，只披露 |
| `comparison` | obj | 环比：`available` / `period` / `prev_path` / `prev_window` / `rows` / `notes` |

## totals

| 键 | 说明 |
|---|---|
| `sessions` / `substantive_sessions` / `quick_sessions` | 会话总数与 ADR-0001 口径的拆分 |
| `scanned_sessions` / `excluded_sessions` | 导出包里的会话数 / 窗口内没有任何真实用户消息而被排除的会话数 |
| `user_messages` / `assistant_messages` | **事件表**统计的真实消息数（已剔除伪用户消息） |
| `tool_calls` / `tool_errors` / `incomplete_results` | 工具调用、报错结果、未完成结果 |
| `duration_minutes` | 各会话时长之和（会话时长按事件时间跨度，跨窗口会话以窗口为界） |
| `tokens_input` / `tokens_output` / `token_sessions` | token 合计与有 token 记录的会话数（合计仅作量级参考） |
| `files_touched` / `lines_added` / `lines_removed` | 去重文件数与代码行增减 |
| `git_commits` / `git_pushes` | 从工具入参里识别出的提交 / 推送次数 |
| `days_active` / `active_hours` | 有用户消息的自然日数 / 出现用户消息的「日期+小时」格数 |
| `messages_per_day` | `user_messages / days_active` |
| `median_response_seconds` / `avg_response_seconds` | 用户消息到紧随其后的助手消息的间隔 |
| `error_rate` | `tool_errors / tool_calls` |

## agents / projects / sessions

`agents[]`：`key`、`label`、`sessions`、`substantive`、`quick`、`user_messages`、
`assistant_messages`、`tool_calls`、`errors`、`incomplete`、token 两项、
`duration_minutes`、`files_touched`、`lines_added`、`lines_removed`、
`tool_families`（能力族 → 次数）、`top_tools`、`projects`（项目 → 会话数）。

`projects[]`：`name`、`sessions`、`substantive`、`quick`、`user_messages`、`tool_calls`、
`errors`、`lines_added`、`lines_removed`、`agents`（key → 会话数）、`duration_minutes`、
`agent_labels`。

`sessions[]`（一行一会话）：

`id`、`agent`、`agent_label`、`title`、`project`、`started_at`、`ended_at`、
`duration_minutes`、`substantive`、`user_messages`、`tool_calls`、`errors`、
`tokens_input`、`tokens_output`、`files`、`lines_added`、`lines_removed`、`tools`、`model`。

会话 `title` 若本身就是伪用户消息（如审批策略通知），会被替换为第一条真实用户消息。

## tools

- `families`：能力族 → 次数。族固定为 `exec` / `edit` / `read` / `search` / `web` / `agent` / `other`，
  映射规则在 `constants.TOOL_FAMILY_BY_NAME`，未知工具按名字里的关键词兜底。
- `top_tools`：`[{name, count, family}]`。
- `by_family`：族 → 该族最常用的两个工具。
- `by_agent`：Agent → 能力族计数。

## code

`languages` 按**去重后的文件**统计（一个文件被改多次只算一次），因此各项之和 ≤ `files`；
无法识别扩展名的文件不计入 `languages`。

## friction

- `categories`：错误类型 → 次数。类型枚举见 `constants.ERROR_CATEGORY_ORDER`，
  顺序即判定优先级；判定前会剥掉导出包附加的 `File sandbox: …` 尾巴。
- `by_tool`：工具 → 报错次数（结果缺工具名时按 `tool_call_id` 回填）。
- `examples`：真实样本，已剥沙箱尾巴、按类型去重，同类最多两条，最多 12 条。
- `empty_text`：报错结果里正文为空（剥掉沙箱尾巴后）的条数。这类记录一律记
  `unclassified`（「未提供错误详情」），**不按工具名猜类型**；占比过半时 `warnings` 会写明。
- `error_rate` 为小数（0.013），展示层乘 100。

## narrative_material

- `repeated_projects`：出现 ≥2 个会话的项目。
- `tool_combos`：同一会话里同时出现的工具能力族组合。
- `error_categories`：错误类型汇总。
- `session_samples`：每个会话的 ID / Agent / 项目 / 标题 / 用到的工具 / 前两条真实用户消息
  （截断到 `NARRATIVE_MESSAGE_CHARS`）。

## 不要做的事

- 不要把 `sessions.csv` 的会话级合计写进 `totals`——那是另一个口径，差异已在 `warnings` 说明。
- 重复导出的会话记在 `duplicates`，并按原值计入 `totals`；报告里若引用「实质会话数」，
  必须同时说明其中有多少条属于重复导出（`duplicates.extra_substantive`），否则读者会以为是独立会话。
- `window.timezone` 跟随 `--utc-offset` / `INSIGHTS_UTC_OFFSET`（默认 `UTC+8`）；换时区重新 collect，
  不要拿旧 stats 改字段。
- 不要在 render 里重算占比、Top 榜或错误分类；需要新指标就在 `stats.py` 加，并更新本文档。
