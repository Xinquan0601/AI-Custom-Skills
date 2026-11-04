# work-report

把 agenttrail 导出的聊天记录包写成周报和月报的 DSH 技能。周报是一手产出，月报由当月周报合并，
最后统一生成一个 `索引.html` 浏览壳（`file://` 直开，连一次文件夹就能读写 md）。

本目录就是技能本体；安装位置是 `<工作区>/.dsh/skills/work-report/`，仓库根的 `link-skills.ps1` 用目录 junction 挂过去，改完立即可用。

## 目录

```
work-report/
  SKILL.md              技能说明（DSH 加载入口）
  config/               系列、客户组、字数线、分类规则
  scripts/collect.py    数据包 -> digest.json + _素材/<周>/<会话>.txt
  scripts/render.py     报告目录 -> 索引.html（含 8 类校验）
  scripts/monthly.py    周报 -> 月报草稿 + 漏写会话清单
  scripts/selfcheck.py  全链路自检
  references/           format.md 文体 / data-source.md 数据包 / taxonomy.md 分类
  templates/hub.html    索引壳模板
  demo/                 四份周报 + 一份月报 + 索引.html 样例
```

## 三步流程

```bash
python scripts/collect.py <数据包> --json digest.json --transcripts _素材
#   按 references/format.md 手写 周报/20261027-周报.md
python scripts/render.py <报告目录> --profile work      # 或 --profile nonwork
python scripts/monthly.py <报告目录> --month 2026-10 --digest digest.json
```

周次口径是 **周二 ~ 周一**，文件名用周起始日 `20261027-周报.md`；月报 `202610-月报.md`。

## 校验与自检

```bash
python scripts/selfcheck.py          # 造最小数据包，跑通 collect -> render -> monthly
python scripts/render.py <目录> --check   # 只校验不写文件，有 error 退出码 1
```

`render.py` 的 8 类检查：标题格式、系列/客户组白名单、状态词、条目字数（60–120 目标，<40 或 >120 报警）、
文件路径、裸提交号、AI 腔词、跨文件重复条目。`error` 跳过该份生成，`warn` 只提示。

## 已知限制

- 条目只写素材里有的东西。素材里没有的内容（例如 `bug23` 只出现在旧月报里）会保留短条，
  不靠推测补参数。
- DV436 的部分数字来自用户早先手贴的月报，不是数据包里的，复现时要认这条来源差异。
- 月报核对只做提示：`monthly.py` 会把「有素材但周报里没写」的会话列出来，是否真漏由写作者判断。
- 非工作目录里的「其他」组包含一次性问答和环境配置，不是全部有价值。

## 版本

当前 1.0.0，见 `CHANGELOG.md`。
