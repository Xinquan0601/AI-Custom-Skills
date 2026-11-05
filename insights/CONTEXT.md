# Insights（AI 使用洞察报告）

把 AgentTrail 导出包变成一份单文件 HTML 复盘报告：脚本算事实，LLM 写叙事，脚本再渲染。
本文件只定义术语，不写流程（流程见 SKILL.md，字段见 docs/）。

## Language

**导出包（bundle）**：
AgentTrail 导出的 `agenttrail-*.zip` 或解压目录，含 `manifest.json`、`sessions.csv`、`events.csv`。
它是本项目**唯一**的数据源（ADR-0003）。
_Avoid_: 数据源目录、原始库

**窗口（window）**：
报告覆盖的本地自然日区间，默认等于导出包窗口；用户指定时取交集并裁剪。
_Avoid_: 时间范围、时间段

**实质会话**：
真实用户消息 ≥2 条且时长 ≥1 分钟的会话，统计主口径（ADR-0001）。
_Avoid_: 有效会话、主要会话

**快速问答**：
有用户消息但不够实质会话条件的会话，单独计数，不混入主口径。
_Avoid_: 轻会话、次会话

**伪用户消息**：
客户端以 `user_message` 写进事件表的系统内容：每轮的时间采样说明、图片回显
（`<path>…</path>`）、审批策略变更通知。统计前剔除，剔除条数写进 warnings。
_Avoid_: 系统消息、噪音（它影响口径，不只是噪音）

**事件计数口径**：
消息量、工具量、代码行、文件、报错一律按 `events.csv` 统计；`sessions.csv` 的
会话级合计只用于对账，差异写进 warnings。
_Avoid_: 会话口径、汇总口径

**数据说明（warnings）**：
导出包的已知缺口（截断、token 覆盖、去重、伪消息剔除）。原样出现在报告页脚，
不允许在叙事里被省略或改写。
_Avoid_: 备注、提示

**上期（环比对象）**：
按报告类型定位的上一窗口 stats：周报找上一自然周，月报找上一自然月（ADR-0002）。
_Avoid_: 上一份报告、最近一次

**周期标记（period）**：
`week` / `month`，决定环比去哪找上期、history 存档怎么命名；任意窗口为 null。
_Avoid_: 报告类型、窗口标签

**能力族（tool family）**：
把工具名归成 exec / edit / read / search / web / agent / other 七类，用于跨 Agent 比较。
_Avoid_: 工具分类、工具组

**叙事素材（narrative_material）**：
collect 输出的证据集：重复项目、工具组合、错误类型、每个会话的前两条真实用户消息。
LLM 写叙事前先看它，不要凭印象归纳。
_Avoid_: 素材池、候选数据

**证据字段（source）**：
narratives 里关键条目携带的定位串，必须是会话标题 / 真实用户消息的子串或会话 ID 前缀。
render 校验存在性，仅警告不阻断。
_Avoid_: 引用、出处

**报告三件套**：
`stats.json`（脚本统计）、`narratives.json`（LLM 叙事）、最终 HTML。前两者是 render 的输入。
_Avoid_: 中间文件、临时文件
