# narratives.json 契约

LLM 撰写、`render` 消费。结构由 `narrative.assert_schema()` 强校验，内容由
`narrative.validate_content()` 给警告（不阻断渲染）。

`schema_version` 必须为 `2`。

## 顶层字段

| 字段 | 类型 | 渲染位置 |
|---|---|---|
| `overview` | obj | 总览「这次复盘最值得看的四件事」 |
| `project_areas` | obj | 项目条形图下方的说明 |
| `interaction_style` | obj | 「你怎么和 AI 配合」 |
| `what_works` | obj | 「做得漂亮的地方」 |
| `friction_analysis` | obj | 「问题出在哪」 |
| `suggestions` | obj | 「马上能用的改进」 |
| `on_the_horizon` | obj | 「再往前一步」 |
| `fun_ending` | obj | 「一个有趣的观察」 |
| `comparison_narrative` | str | 环比区（没有上期时不显示） |

## 各区块

### overview

`whats_working` / `whats_hindering` / `quick_wins` / `ambitious_workflows`，四条都要写，
每条 2–3 句。**不要重复图表里已有的数字**，写模式与具体证据。

### project_areas

`areas: [{name, session_count, description}]`。`name` 必须与 `stats.projects[].name` 一致，
否则说明不会出现在项目图下方。`description` 一到两句，写「做了什么 + AI 在哪一环」。

### interaction_style

`{narrative, key_pattern}`。`narrative` 两到三段，第二人称，分析模式而不是复述事件；
`key_pattern` 一句话，用冒号或破折号引出例子。

### what_works

`{intro, impressive_workflows: [{title, description, source}]}`，3–4 条。
每条写清「你做了什么 → AI 做了什么 → 结果」，**必须带 `source`**。

### friction_analysis

`{intro, categories: [{category, description, examples: [str], source}]}`，3–6 条。
`category` 建议带次数（如 `文件读写失败（25 次）`）；`examples` 给 1–2 条真实片段；
**必须带 `source`**。

### suggestions

`{agents_md_additions: [{addition, why, source}], features_to_try: [{feature, one_liner, why_for_you}]}`。
`addition` 是可以直接粘进 `AGENTS.md` 的一行规则；`why` 说明它消掉哪类摩擦。

### on_the_horizon

`{intro, opportunities: [{title, description}]}`，3 条，可以想得比现在大一点。

### fun_ending

`{headline, detail}`。`headline` 一句定性观察，`detail` 一两句补充；尽量别写成纯统计句。

## source 规则

`source` 是证据定位串，渲染时会校验：取前 8 位能在会话 ID 里找到，或整串是某个会话标题 /
真实用户消息的子串，才算通过；否则打印 `[warn] 疑似编造的引用`。

推荐写法：

- 会话标题的片段，如 `对前端项目所有页面进行布局优化`；
- 真实用户消息的片段，如 `先不要移植和修改代码`；
- 会话 ID 前缀（至少 8 位）。

不要为了消警告把 `source` 写成空串——空串等于放弃可追溯性，本项目的底线是「每条判断都能回到数据」。

## 写作纪律

1. 所有数字必须能在 `stats.json`（或有 facets 时的 `facets.json`）找到；写之前先看
   `narrative_material`。`validate` 会抽查 ≥100 的整数、带「万/亿」的量级和百分比：
   整数必须出现在 stats/facets 的数值或文本里，百分比按任意两项的比值校验（如 9/77≈11.7%）。
2. 归纳（「你经常…」）必须有 ≥2 个会话支撑；单个案例写成案例，不要写成模式。
3. 数据缺失与数据为零是两件事：导出没带 token 就说「只有 N/M 个会话有记录」，不要写「token 很少」。
4. 不评价用户本人，只评价工作方式；建议要能落地成本周就能改的一个动作。
