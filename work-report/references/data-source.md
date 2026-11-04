# 数据源

只支持一种格式：agenttrail 导出的目录包（`agenttrail-YYYYMMDD-HHMMSS/`）。

```
sessions.csv   session_id, external_id, project, cwd, title, started_at, ended_at, ...
events.csv     event_id, session_id, timestamp, role, content, fingerprint, ...
summary.json   包级统计
manifest.json  导出参数与时间窗
data_dictionary.md  字段说明
```

## 硬性注意

- **必须用 Python `csv` 模块读**。`events.content` 里有换行，`split("\n")` 会把一条事件切碎。
- **必须抬高字段上限**：`csv.field_size_limit(min(sys.maxsize, 2**31-1))`。十月包里存在超过 128KB 的单字段，不设会直接抛 `field larger than field limit`。
- `events.session_id` 对应 `sessions.external_id`，不是 `session_id`。
- 时间是 UTC（`Z` 结尾），一律转到 `+08:00` 再判断日期归属。
- 多个包可以一起给：`collect.py a/ b/ c/`。按 `external_id` 去重会话、按 `fingerprint` 去重事件。

## 子代理会话

opencode / codex 会把子代理记成独立会话，会让「一次全项目审查」变成十几条。两种合并信号，命中任一即并入母会话：

1. `sessions.project == "subagents"`
2. 首条 user 消息以 `You are a subagent spawned by another session` 开头

## 消息粒度

导出包只含 `user_message` / `assistant_message`，工具调用与工具结果在采集端已剔除。

本技能**不做二次过滤**：全量读入，按会话写全文到 `_素材/<周>/`，再从助手消息里挑结论候选。
实测十月两包 134 会话，工作类 49 条，47 条能挑出候选，平均 12.6 条/会话。

候选的取舍标准（`collect.py` 的 `_usable`）：句长 12–220 字、含中文、非问句、非代码行、
带数字单位或判定动词。这是**读的时候的排序**，不是入库过滤——原文都在 `_素材` 里。

## 数据量参考

十月包：127 会话 / 8685 事件 / 时间窗 2026-09-30T16:00Z ~ 2026-10-31T15:59Z / events.csv 约 22MB / 268k 物理行。
