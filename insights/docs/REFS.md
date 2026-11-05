# 重构前的参考清单

> 结论：**看 3 个，各看 1 个点，总共不超过 1 小时。看完就动手，别逛第 4 个。**
>
> 2026-11-05 补记：三个参考已看完，结论采纳为「抄结构、抄阈值设计、抄纪律，不抄 schema」。
> 数据源最终定为 AgentTrail 导出包（ADR-0003），报告按 ADR-0004 重排；
> 本文件保留当时的调研原文，作为判断依据而不是现状描述。

理由：你的数据格式是私有的——导出包字段（会话级 + 事件级）+ 中文工作流 + 嵌入式项目（DV436/DV435/RK3576 这类）。**没有任何开源项目能给你 schema。** 参考只能给你结构和纪律，schema 必须从你自己的会话里长出来。

---

## 一、codex-session-insights — 看 SKILL 怎么写约束

**仓库**：`Undertone0809/zee-skills` 里的 `codex-insights` skill（5★，小项目，但 SKILL.md 写得比多数大项目严谨）

**只看一段**：SKILL.md 的 `Analysis discipline`，5 条：

| 原文 | 价值 |
|---|---|
| `Build a real cohort before judging patterns` | 先建真实队列再判断，别拿最像的 10 个凑数 |
| `Collapse obvious child/reviewer/subagent sessions under a parent workflow when spawn-edge metadata is available. If it is unavailable, say so and avoid overclaiming` | 有子代理元数据就折叠，没有就**明说没有**，别过度声称 |
| `Separate raw session counts from root workflow counts. A fanout-heavy review task can create many sessions without meaning the user needs a new skill` | **最值钱的一条**。55 个会话不等于 55 件事。一个 review 任务 fanout 出 8 个子会话，那是 1 件事 |
| `Prefer current local evidence over memory summaries` | 记忆推断出来的事实必须标注来源，不能和实测混排 |
| `Do not infer "latest 30" from filenames alone if sqlite or index metadata is available` | 别拿文件名排序当时间序 |

**抄**：这 5 条直接进你的 SKILL.md 当作叙事纪律。尤其第 3 条，能直接修掉你现在"会话数"这个口径的语义问题。

**别抄**：它的三档模型分工（facet / fast-section / insight 各用一个模型）。你不需要，你是单人复盘不是批量跑。

---

## 二、claude-doctor — 看信号怎么定义

**仓库**：`millionco/claude-doctor`（619★）

**只看两个文件**：`suggestions.ts`（产出规则）+ `constants.ts`（信号表和阈值）

**关键设计——双阈值**：

```
检测阈值：edit-thrashing >= 5   (同一文件被改 5 次 → 记为一次命中)
建议阈值：同一信号在 >= 2 个项目出现  (才产出一条规则)
```

这个设计解决的是：**一次偶发不该写成永久规则。** 你今天手滑改了 5 次同一个文件，不代表你需要一条"先读完再改"的规则。

**抄**：双阈值 + **所有信号和阈值外置到单一 constants 文件**。你现在信号逻辑散在 `stats.py` 的 aggregate 里，改一个阈值要读 200 行。

**别抄**：它的规则文案。硬编码英文，而且有硬伤——`keep-going-loop` 建议"更自主别老问"，`high-turn-ratio` 建议"少问"，两条规则方向冲突却可能同时产出。你抄结构，文案自己写。

**另记一个教训**：它只给"Based on analysis of N sessions"这一个事实锚点，同一条信号出现 2 次和 200 次输出同一句话。**你的信号必须带 `count` 和 `evidence[]`**，否则用户无法判断建议的分量。

---

## 三、session-retrospective — 看闭环怎么做

**仓库**：`svetlovtech/skills_and_agents` 里的 `session-retrospective` skill

**只看一个机制**：`cmd_feedback.py --apply`

**关键设计**：

1. **建议是持久化对象，不是一次性输出**。存进库、有状态（未处理/已应用）、可追溯
2. **有质量分**：`avg_quality` 1-5，配合 `agent_hits/misses`（agent 选对没）、`skill_hits/misses`（skill 加载对没）
3. **批处理脚本由用户自己跑**：`generate_reflect_sh.py` 只生成 bash 脚本，不执行。避免 skill 内长时间阻塞

**抄**：建议的持久化 + 状态追踪。你现在 `narratives.json` 每次重写，上周说"要加 CLAUDE.md 规则"这周没人记得做没做。**没有状态就没闭环。**

**别抄**：它的 7 个脚本切分（db_stats / cmd_review / cmd_feedback / session_metrics / session_filter / generate_reflect_sh / save_reflection / reflection_report）。对你的规模是过度工程，4 个文件够了。

---

## 四、三个判断

1. **抄结构，不抄 schema。** 他们的 `goal_categories`（13 类）是给 Claude Code 通用场景设计的，套到"DV436 摄像头驱动调试"上语义立刻散掉。你的 taxonomy 得从自己的会话里长。
2. **抄阈值设计，不抄阈值数字。** 5 次 edit 是他们的经验值。你的工作流里 3 次就该报警，或者 8 次才算——得看你自己数据。
3. **抄纪律，不抄文案。** SKILL.md 里那些"禁止编造""素材不足别硬编""区分数据缺失和数据为零"的约束，比代码值钱十倍。

---

## 五、但真正的参考不在这三个里

**花 30 分钟做这件事，比看十个项目有用：**

从 `history/` 里挑 **10 个会话**（5 个你觉得干得漂亮的、5 个卡住的），逐个回答三个问题：

1. **这个会话实际干了"几件事"？**
   如果一个会话里干了 5 件不相干的事，说明 `Session` 这个模型从一开始就是错的——你需要的是 topic segmentation，不是 session 聚合。

2. **卡住的是哪一轮？是工具失败、理解错、还是方向错？**
   这三类要三种不同的处方。工具失败 → 改命令；理解错 → 补规则；方向错 → 改工作流。

3. **如果只能改一个动作，改哪个？**

写成 10 条，你的信号清单自己就出来了，**而且是你自己的**，不是别人那 13 个枚举。

**这一步做不完就别动手。** 否则重构出来只是把别人的信号表套在你的数据上，一个月后还得推翻。

---

## 六、动手顺序

```
1. 30 分钟：标注 10 个会话（上面第五节）        ← 不可跳过
2. 1 小时：看上面三个参考的对应对应段落          ← 只看指定段落
3. 半天：写 events.py + 一个 adapter（zcode）   ← 先跑通一个源
4. 验证：fact 层跑两次，JSON 必须完全一致        ← 试金石
5. 再扩 claude / codex adapter
```

第 3 步只做一个源。三个源一起上，出问题分不清是 schema 错还是 adapter 错。
