# ADR-0003：只从 AgentTrail 导出包取数

- 状态：已采纳（2026-11-05）
- 相关决策：D1（不保留备选，只打算用包）、D4/D5（旧 history 与旧数据源都不再使用）

## 背景

旧版 insights 直接扫描本机客户端的私有数据：ZCode 的 SQLite、Claude Code 的
`~/.claude/projects/**/*.jsonl`、Codex 的 `~/.codex/sessions` 与 `archived_sessions`。

问题有三个：

1. **不可移植。** 换个用户、换台机器、多台机器汇总，都要重写采集器。
2. **口径不可控。** 每个客户端的落盘格式不一样，字段缺失时只能猜，报告里说不清哪些是推算的。
3. **和「汇总分析」的需求冲突。** 用户要的是「一台机器导出、另一台机器分析」，直读做不到。

AgentTrail 导出包把「采集」和「分析」拆开：采集器负责把各 Agent 的原始记录规范化成
`sessions.csv` + `events.csv`，insights 只做分析。

## 决策

- insights **只**读 `agenttrail-*.zip` 或解压目录，不再直读任何客户端私有目录。
- 本机直读适配器（zcode / claude / codex）全部删除，不留「以后可能用得上」的分支。
- 探针 / 采集失败不再由 insights 负责排查；数据问题回到 AgentTrail 修。

## 影响

- 数据源契约收敛到 `docs/data-source.md` 一个文件，适配器只需实现 `Bundle`。
- 报告必须显式披露导出包的完整度（截断、token 覆盖、伪用户消息），不能把「导出没带」
  写成「没有发生」。这部分由 `warnings` 承载，原样进报告。
- 加新数据源的成本 = 写一个适配器，产出同一个 `Bundle`；analytics 层不再改。
