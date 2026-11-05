# facets 契约（语义层）

facets 是「会话 → 结构化判断」的中间层，只在报告需要洞察时使用。它**不改动**
`stats.json` 里的任何事实数字：会话数、消息数、工具调用、代码行仍以事件表为准，
facets 只是给叙事提供可追溯的骨架。

> 原则：事实层可复算，语义层可追溯。两层在报告里分开标注，不混写。

## 分类表（`goal_category`，单选）

分类按真实数据长出来，不是通用编程分类。

| key | 名称 | 典型信号 |
|---|---|---|
| `fw_defect` | 固件缺陷排查 | BUG 现象、报警/蜂鸣/刷卡异常、日志追踪 |
| `hw_interface` | 硬件接口与设备树 | DTS、SATA/USB/PCIe、引脚复用、原理图核对 |
| `comm_protocol` | 通信协议调试 | RS232/485、CAN、数据包、CRC、波特率、转发 |
| `arch_review` | 架构审查与调研 | 影响面、API 变更、只读审查、兼容性评估 |
| `design_doc` | 设计与技术文档 | 架构图/数据流图/状态图/时序图、说明书、导出 PDF |
| `customer_delivery` | 客户交付与汇报材料 | 客户说明书、述职/答辩、PPT、对外交付物 |
| `vision_analysis` | 视觉与视频分析 | 视频抽帧、截图理解、户型还原、图像批处理 |
| `tooling_env` | 工具链与环境 | 模型接入、PATH/配置、worktree、脚本与自动化 |
| `req_clarify` | 需求澄清与方案 | 需求边界、方案对比、可行性讨论 |
| `data_curation` | 数据整理与沉淀 | AGENTS.md/规范沉淀、聊天记录采集、资料归档 |

## outcome（单选）

| key | 含义 | 判定线索 |
|---|---|---|
| `closed` | 闭环 | 末段有验证/提交/确认，用户明确认可 |
| `mostly` | 基本闭环 | 主题完成，遗留小事或未收尾 |
| `partial` | 部分达成 | 只解决一部分，或结果被指出不完整 |
| `open` | 未达成 | 停在半路、换方案、明确失败 |

## friction（0–3 个）

| key | 含义 | 数据里的对应信号 |
|---|---|---|
| `silent_error` | 报错无正文 | `errors_without_text`、只有状态没有内容 |
| `incomplete` | 结果未完成 | 工具状态 incomplete、会话无收尾 |
| `drift` | 长任务跑偏/遗忘约束 | 长会话反复纠正、重述需求 |
| `structure` | 生成物结构或格式不对 | 文档/图/PPT 被指不完整、格式返工 |
| `edit_conflict` | 改动冲突/覆盖 | 反复回滚、恢复内容 |
| `overstep` | 超出授权范围 | 用户要求「只改这一处」「不许提交」 |
| `other` | 其他 | — |

## digest（喂给模型的上下文）

每份任务只带必要上下文，不带整段对话：

| 字段 | 说明 |
|---|---|
| `session_id` / `agent` / `project` / `title` | 定位 |
| `started_local` / `ended_local` / `duration_minutes` | 本地时间（UTC+8） |
| `user_messages` / `assistant_messages` / `tool_calls` | 规模 |
| `files` | 触及文件（去掉用户名，最多 8 个） |
| `lines` / `git_commits` | 代码产出 |
| `errors` / `incomplete` / `error_categories` / `error_samples` | 失败信号（错误正文已去 banner） |
| `user_messages_text` | 首 3 条 + 末 2 条真实消息，去重、去伪消息、每条 ≤320 字 |
| `turns` | 与上面一一对应：每条用户消息 + 该轮 Agent 最后一条回复（≤180 字） |
| `final_assistant` / `final_assistant_at` | 会话最后一条有效回复与其本地时间（≤240 字） |
| `tools` | 工具名×次数（大小写合并，最多 6 个） |
| `signals` | 满意度信号计数（中文词表，可审计） |

伪消息（摘要续写、`请继续执行任务`、`<conversation_history_summary>`、工具回填）在 digest
里被剔除；这不改变统计口径，只影响喂给模型的内容。

**为什么必须带回复**：只看用户发言，无法区分「说完就结束了」和「跑偏后用户又来纠正」，
结果与摩擦只能靠猜。注意两个数据特性：

1. 同一条用户消息/回复在导出包里可能重复（相隔几十毫秒），digest 按内容去重；
2. 部分客户端把「思考过程」也导出成 assistant 消息。digest 取该轮**最后**一条并过滤
   明显的英文思考前缀（`The user…`、`Let's…`），仍可能有残留——所以 outcome 以
   用户后续反应与客观信号为主，Agent 自述只作佐证。

## 缓存

`cache_key = sha256(schema_version | session_id | 消息数 | 工具数 | content_hash | 分类表 keys)[:16]`，
`content_hash` 覆盖全部真实消息。内容不变 → 不重新提取；分类表变 → 全部失效（预期行为）。

## tasks.json（plan 产出）

见 `insights_report.py facet plan`。

- `schema_version`、`categories`、`outcomes`、`frictions`：提示词与校验共用同一份枚举；
- `totals`：会话 / 实质 / 快速 / 任务数；
- `warnings`：超过 200 个会话时说明未覆盖数量；
- `tasks[]`：`session_id`、`cache_key`、`digest`、`prompt.system`、`prompt.user`。

## results.json（模型产出）

```json
{
  "results": [
    {
      "session_id": "…",
      "goal_category": "fw_defect",
      "outcome": "mostly",
      "friction": ["silent_error"],
      "helpfulness": 3,
      "satisfaction": "neutral",
      "summary": "不超过 60 字",
      "evidence": ["逐字出现在 digest 里的片段"],
      "instructions": ["用户明确给出的约束"]
    }
  ]
}
```

## merge 校验（`facet merge`）

1. `session_id` 必须在任务列表里，重复只留第一条；
2. `goal_category` / `outcome` / `friction` 必须在枚举里；
3. 必需字段：`session_id`、`goal_category`、`outcome`、`summary`、`evidence`；
4. `evidence` 每条必须在 digest 的 `title + project + user_messages_text + turns[].reply + final_assistant` 中**逐字出现**
   （空白折叠、大小写不敏感）；改写或转述会被拒；
5. `summary` ≤80 字、`instructions` ≤3 条；
6. 坏记录逐条进 `warnings`，不会静默丢弃；
7. 同一场对话被多个客户端重复导出（`opencode-local:` 前缀版与原始 id 版）时，按
   `project + 用户发言序列` 认亲，只保留 id 最短的一条，`coverage.duplicates_merged` 记合并数。

## 覆盖率与报告

- 只对实质会话提取；快速问答不提取；
- 超过 200 个会话按最近活跃取前 200，并在 `warnings` 披露；
- `facets.json` 的 `coverage` 必须写进报告：`accepted / unique_tasks` 是真实覆盖率，
  `duplicates_merged` 要注明「N 条任务来自重复导出」；
- 报告语义层章节（`render --facets`）展示目标分布、结果达成、摩擦类型与反复出现的约束，
  只做分布与证据，不改写 stats 的任何数字；
- 没有 facets 时报告照常生成，只是少了语义层章节——**不要**用 0 填充。
