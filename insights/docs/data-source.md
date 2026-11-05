# 数据源契约：AgentTrail 导出包

insights 只读一种数据源：AgentTrail 导出的`agenttrail-*.zip`（或解压后的同名目录）。
不再读取任何本机客户端的私有目录（`~/.zcode`、`~/.claude`、`~/.codex` 等），
原因见 ADR-0003。

## 1. 包内文件

| 文件 | 必需 | 作用 |
|---|---|---|
| `manifest.json` | 是 | 导出元信息：`export_version`、`generated_at`、`filters.from/to`（UTC）、`counts`、`filters.agents` |
| `sessions.csv` | 是 | 会话级聚合，一行一个会话 |
| `events.csv` | 是 | 事件明细，一行一条消息 / 工具调用 / 工具结果 |
| `summary.json` | 否 | 给人看的导出摘要，程序不依赖 |
| `data_dictionary.md` | 否 | 字段说明，程序不依赖 |

导出包可能是 zip，也可能是解压目录；两种都按同样方式流式读取（zip 不整包解压）。

## 2. 字段

### sessions.csv（会话级）

必需列：`agent_key`、`external_id`、`started_at`。

程序使用的列：

| 列 | 用途 |
|---|---|
| `agent_key` | Agent 维度（`deepseekharness` / `workbuddy` / `opencode` / `codex` / `claudecode`） |
| `external_id` | 会话唯一 ID，事件按它归并 |
| `title` / `project` / `cwd` / `model` | 展示与项目归并 |
| `started_at` / `ended_at` | UTC 时间；缺失时按事件时间补 |
| `message_count` / `user_message_count` / `tool_call_count` / `tokens_input` / `tokens_output` | 会话级合计，仅用于对账与 token 统计 |

会话级合计**不**作为报告的消息量 / 工具量口径（见第 4 节）。

### events.csv（事件级）

必需列：`agent`、`session_id`、`event_type`、`timestamp`。

| 列 | 用途 |
|---|---|
| `event_type` | `user_message` / `assistant_message` / `tool_call` / `tool_result` |
| `timestamp` | UTC ISO 时间戳 |
| `content` | 消息正文或工具结果正文 |
| `tool_name` / `tool_call_id` / `tool_status` | 工具维度；结果缺工具名时按 `tool_call_id` 回填 |
| `tool_input_json` | 工具入参（路径、语言、git 命令都从这里取） |
| `fingerprint` | 跨导出包的稳定指纹，用于去重 |
| `model` / `tokens_input` / `tokens_output` | 模型与 token |

所有时间字段都是 UTC，展示层统一换算到 UTC+8 自然日。

## 3. 窗口语义

- 导出包的窗口取自 `manifest.filters.from/to`，换算成本地自然日后作为报告的**默认窗口**。
- 报告窗口默认与导出窗口一致；用户指定更窄的窗口时取交集并打 `clamped` 标记。
- 会话只要有**一条真实用户消息**落在窗口内就整会话纳入统计，时长按事件时间跨度计算
  （不按会话级 `ended_at - started_at`，避免跨窗口会话被算成 7 天）。

## 4. 完整度与口径（会写进报告）

1. **事件表是主口径。** 消息量、工具量、代码行、文件、报错全部按 `events.csv` 统计；
   `sessions.csv` 的会话级合计只用于对账。
2. **导出可能截断事件。** 导出窗口开始前就已开始的会话，其窗口内事件不全：
   `sessions.csv` 的合计会比事件表多。程序按会话逐一对账，发现差异就写进 `warnings`，
   报告中以「数据说明」形式展示，不静默。
3. **伪用户消息会被剔除。** 部分客户端把系统提示写进 `user_message`：
   - `Time sampled while preparing turn …`（每轮时间采样说明）
   - `<path>…</path><type>…</type>`（图片回显）
   - `The approval policy changed from …`（审批策略变更通知）

   这些不计入消息量、活跃小时、实质会话判定，剔除条数写进 `warnings`。
4. **token 只有部分会话上报。** 各 Agent 统计口径不同（有的只报输出、有的完全不报），
   合计值仅作量级参考，报告里始终带覆盖率说明。
5. **去重。** 有 `fingerprint` 时按它去重；无 `fingerprint` 时按
   `(agent, session_id, event_type, timestamp, tool_call_id, content 前 120 字)` 去重。
6. **坏行不致命。** 缺时间戳 / 缺会话 ID 的行跳过并计数，写入 `warnings`。

## 5. 加上新数据源时

新增导出格式（比如别的工具导出同类数据）时：

1. 在 `scripts/insights_core/sources/` 下加适配器，产出同一个 `Bundle`（见 `base.py`）；
2. 在 `load_bundle()` 里按扩展名 / 目录特征分派；
3. 适配器负责把字段名与时间格式翻译成 `Event` / `SessionMeta`，**不要**把差异带进 `metrics` / `stats`；
4. 在 `docs/data-source.md` 补一节字段映射，并在 `warnings` 里说明该源的已知缺口。
