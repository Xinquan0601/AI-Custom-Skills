---
name: work-report
version: 1.0.0
description: 把 agenttrail 导出包写成 DV454 / DV456 / DV460 / DV436 的周报和月报。当用户给出一份 `agenttrail-*` 数据包（含 sessions.csv、events.csv）并要求「写周报」「写月报」「整理这周工作」时使用。产出为 .md 正文加一个 `索引.html` 浏览壳。
---

# 工作报告

三件事：把数据包读成素材、按固定文体写成 .md、生成浏览壳。

## 流程：先周后月

周报是唯一的一手产出。月报不重新读日志，由当月周报合并出草稿，再用聊天记录核对补漏。

```
python scripts/collect.py <数据包...> --json digest.json --transcripts _素材
#   读全部用户消息与助手消息，逐会话产出 digest 记录 + _素材/<周>/<会话>.txt 全文
#   按 references/format.md 的文体手写 周报/*.md 月报/*.md
python scripts/render.py <报告目录> --profile work
#   校验 + 生成 索引.html
python scripts/monthly.py <报告目录> --month 2026-10 --digest digest.json
#   月报草稿 = 当月周报合并去重；同时列出「有素材但周报里没写」的会话
```

`collect.py` 不过滤任何消息：用户消息和助手消息全量进 `_素材`，每条会话再从助手消息里挑
14 条结论候选写进 `digest.sessions[].conclusions`（原文照抄，只做取舍不改写）。

写某一周时读那个周的 `_素材` 全文；挑条目时先看 `conclusions`，找不到再回全文。
**素材是原料，句子仍由写作者组织**——`conclusions` 只保证数字和术语来自数据本身。

## 归类规则

1. 标题出现板卡记号 → 对应系列/客户组
2. 仓库目录命中 `projects.work` → 对应系列/客户组
3. 命中 `projects.ignore` → 忽略
4. **剩下的一律算非工作**，产出写到非工作目录：命中 `projects.nonwork` 归到「工具链」「个人项目」，
   都认不出来的兜底进「其他」组

第 4 条是兜底：宁可不准确别漏，工作目录和标题都认不出来的内容不进工作周报。

## 目录约定

```
工作报告/
  周报/20261008-周报.md      文件名 = 周起始日（周二）
  月报/202610-月报.md        文件名 = 年月
  数据源/agenttrail-*/       原始包，render 时跳过
  索引.html                  浏览壳，连一次文件夹后可读写 md
```

## 排序与长度

- 系列顺序固定 `DV460` → `DV454` → `DV456` → `DV436`，没内容就整段省略，不许换位
- 客户组按首字母，拉丁在前中文在后；**周报月报必须同序**
- 一条 60–120 字为目标区间（config 里 min_chars 40 / *_item_chars 120 是报警线）
- 40–60 算偏薄，能补参数、现象、判据就补；素材真的没有就保持短条，不要编数字
- 密度是优点，别为了短砍细节
- 只有「两件互不相干的事」或「完成+未完成混在一条」才拆；同一件事的两个阶段不拆
- 一条里没有任何参数或实测现象，等于没写，要补
- 客户组不编号，月报条目在组内自动编号

## 硬约束

- 周次是 **周二 ~ 周一**，不是周一到周日。首周从当月第一条记录起。
- 系列名大写：`DV454` `DV456` `DV460` `DV436`，不带「系列」「通用平台」后缀。
- 条目必须以 `完成` / `未完成` / `进行中` 开头，否则侧边栏计数不准。
- 正文里不出现文件路径、不出现裸提交号。
- 不写「值得注意的是」「综上」「赋能」「抓手」「助力」「闭环」这类词。

## digest 字段

```
sessions[].sid/bucket/series/group/title/agent/project/cwd
           start/week/days/events/user_msgs/asks[]/subagents[]
           conclusions[]   助手消息里的结论候选，最多 14 条
```

`bucket` 四档：`work` / `nonwork` / `ignore` / `unassigned`。`unassigned` 需要裁决后补规则到 config，不要硬塞。

## 参考

- `references/format.md` —— 文体规格，含真实样例的正误对照。**动笔前先读。**
- `references/data-source.md` —— 数据包结构、CSV 陷阱、时间归属。
- `references/taxonomy.md` —— 系列与客户组的划分、分类优先级。

## 校验

`monthly.py` 的核对只做提示：它把每个会话标题和结论里的数字跟草稿全文比，命中不到就单列出来，由写作者判断是真漏还是换个说法写了。

`scripts/selfcheck.py` 会造一个最小数据包，跑通 collect → 手写周报 → render → monthly 全链路，改完脚本先跑它。

`render.py --check` 会跑：系列白名单、客户组白名单、条目状态词、长度上限、路径、裸提交号、AI 腔词、跨文件重复条目。
`error` 会让该份跳过生成，`warn` 只提示。校验通过不等于写得好，只是没犯硬错。
