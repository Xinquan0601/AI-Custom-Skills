"""HTML 区块组装：视图模型进，HTML 片段出。

只做排版与转义，不做业务判断；数据为空的区块由 render_body 统一跳过或降级。
"""
from __future__ import annotations

import re

from .charts import bar_list, chips, column_chart, esc, histogram, hour_grid, stacked_shares


def md(text) -> str:
    """极简 Markdown：段落、**加粗**、行内代码、无序列表。"""
    if not text:
        return ''
    paragraphs = []
    for block in str(text).split('\n\n'):
        lines = [line.rstrip() for line in block.strip().split('\n') if line.strip()]
        if not lines:
            continue
        if all(line.lstrip().startswith(('- ', '* ')) for line in lines):
            items = ''.join(f'<li>{_inline(line.lstrip()[2:])}</li>' for line in lines)
            paragraphs.append(f'<ul>{items}</ul>')
        else:
            paragraphs.append(f'<p>{_inline("<br>".join(lines))}</p>')
    return '\n'.join(paragraphs)


def _inline(text: str) -> str:
    escaped = esc(text)
    escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    escaped = re.sub(r'`([^`]+)`', r'<code>\1</code>', escaped)
    return escaped


def render_body(view: dict) -> str:
    parts = [
        _hero(view),
        _stats(view),
        _overview(view),
        _comparison(view),
        _agents(view),
        _projects(view),
        _tools(view),
        _code(view),
        _rhythm(view),
        _friction(view),
        _facets(view),
        _interaction(view),
        _wins(view),
        _friction_text(view),
        _suggestions(view),
        _horizon(view),
        _fun(view),
        _footer(view),
    ]
    return '\n'.join(part for part in parts if part)


def _section(anchor: str, eyebrow: str, title: str, body: str,
             note: str = '') -> str:
    if not body.strip():
        return ''
    note_html = f'<div class="section-note">{md(note)}</div>' if note else ''
    return (f'<section class="card" id="{anchor}">'
            f'<div class="eyebrow">{esc(eyebrow)}</div>'
            f'<h2>{esc(title)}</h2>{note_html}{body}</section>')


def _hero(view: dict) -> str:
    chips_html = chips(view['chips'])
    quality = ''
    if view['quality']:
        items = ''.join(f'<li>{esc(item)}</li>' for item in view['quality'])
        quality = f'<details class="quality"><summary>数据说明 {len(view["quality"])} 条</summary><ul>{items}</ul></details>'
    return (f'<header class="hero">'
            f'<div class="eyebrow">AI 使用洞察报告</div>'
            f'<h1>{esc(view["window_label"])}</h1>'
            f'<p class="sub">{esc(view["source_label"])}</p>'
            f'<div class="chips">{chips_html}</div>{quality}</header>')


def _stats(view: dict) -> str:
    cards = ''.join(
        f'<div class="stat"><div class="stat-label">{esc(card["label"])}</div>'
        f'<div class="stat-value">{esc(card["value"])}</div>'
        f'<div class="stat-hint">{esc(card["hint"])}</div></div>'
        for card in view['stat_cards'])
    return f'<div class="stat-grid">{cards}</div>'


def _overview(view: dict) -> str:
    items = view['sections']['overview']
    if not items:
        return ''
    cards = ''.join(
        f'<a class="overview-card" href="{esc(item["href"])}">'
        f'<span class="overview-prefix">{esc(item["prefix"])}</span>'
        f'<span class="overview-text">{_inline(str(item["text"]))}</span></a>'
        for item in items)
    return (f'<section class="card" id="sec-overview"><div class="eyebrow">总览</div>'
            f'<h2>这次复盘最值得看的四件事</h2><div class="overview-grid">{cards}</div></section>')


def _comparison(view: dict) -> str:
    comparison = view.get('comparison')
    if not comparison:
        return ''
    body = ''
    if comparison['available']:
        rows = ''.join(_comparison_row(row) for row in comparison['rows'])
        body = (f'<p class="muted">上期：{esc(comparison["prev_window"])}</p>'
                f'<table class="table"><thead><tr><th>指标</th><th>本期</th><th>上期</th>'
                f'<th>变化</th></tr></thead><tbody>{rows}</tbody></table>')
    else:
        body = ''.join(f'<p class="muted">{esc(note)}</p>' for note in comparison['notes'])
    text = comparison.get('text') or {}
    narrative = ''
    if text.get('summary'):
        wins = ''.join(f'<li>{md(item)}</li>' for item in text.get('wins') or [])
        concerns = ''.join(f'<li>{md(item)}</li>' for item in text.get('concerns') or [])
        narrative = (f'<div class="prose">{md(text["summary"])}</div>'
                     + (f'<div class="two-col"><div><h4>变好的地方</h4><ul>{wins}</ul></div>'
                        f'<div><h4>要留意的</h4><ul>{concerns}</ul></div></div>'
                        if wins or concerns else ''))
    extra = ''
    if comparison['available']:
        extra = ''.join(f'<p class="muted small">{esc(note)}</p>' for note in comparison['notes'])
    return _section('sec-compare', '环比', '本期 vs 上期', body + narrative + extra)


def _comparison_row(row: dict) -> str:
    delta = row['delta']
    if delta > 0:
        arrow, cls = f'▲ {delta:g}', 'up'
    elif delta < 0:
        arrow, cls = f'▼ {abs(delta):g}', 'down'
    else:
        arrow, cls = '持平', 'flat'
    if row.get('good') is True:
        cls += ' good'
    elif row.get('good') is False:
        cls += ' bad'
    percent = f'（{row["percent"]:+g}%）' if row.get('percent') is not None else ''
    return (f'<tr><td>{esc(row["label"])}</td><td>{esc(_num(row["current"]))}</td>'
            f'<td>{esc(_num(row["previous"]))}</td>'
            f'<td class="delta {cls}">{esc(arrow)}{esc(percent)}</td></tr>')


def _num(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _agents(view: dict) -> str:
    if not view['agents']:
        return ''
    cards = []
    for agent in view['agents']:
        tools = ''.join(
            f'<span class="tag">{esc(tool["name"])} <b>{tool["count"]}</b></span>'
            for tool in agent['top_tools'])
        cards.append(
            f'<div class="agent-card">'
            f'<div class="agent-head"><span class="dot" style="background:{agent["color"]}"></span>'
            f'<h3>{esc(agent["label"])}</h3><span class="agent-share">{agent["messages_share"]}%</span></div>'
            f'<div class="agent-metrics">'
            f'<span><b>{agent["sessions"]}</b> 会话</span>'
            f'<span><b>{agent["messages"]}</b> 条消息</span>'
            f'<span><b>{agent["tool_calls"]}</b> 次工具</span>'
            f'<span><b>{agent["error_rate"]}%</b> 报错</span></div>'
            f'<div class="agent-tools">{tools}</div></div>')
    note = '占比按用户消息数计算；同一件事可能在多个 Agent 里各开一次会话，跨 Agent 的会话数不能直接相加当任务数。'
    heading = f'{len(view["agents"])} 个 Agent 各自在干什么'
    return _section('sec-agents', '分工', heading,
                    f'<div class="agent-grid">{"".join(cards)}</div>', note)


def _projects(view: dict) -> str:
    if not view['projects']:
        return ''
    items = [{'label': p['name'], 'value': p['messages'],
              'note': f'{p["sessions"]} 会话'} for p in view['projects'][:12]]
    body = bar_list(items, color='#0ea5e9')
    noted = [p for p in view['projects'][:12] if p.get('summary')]
    if noted:
        body += '<ul class="project-notes">' + ''.join(
            f'<li><b>{esc(p["name"])}</b>{esc(p["summary"])}</li>' for p in noted) + '</ul>'
    return _section('sec-projects', '项目', '时间花在哪几个项目上', body)


def _tools(view: dict) -> str:
    families = view['tools']['families']
    if not families:
        return ''
    family_html = stacked_shares([
        {'label': item['label'], 'value': item['value'], 'color': item['color']}
        for item in families])
    top_rows = ''.join(
        f'<tr><td>{esc(tool["name"])}</td><td>{esc(tool["family"])}</td>'
        f'<td class="num">{tool["count"]}</td></tr>'
        for tool in view['tools']['top'])
    top_html = (f'<table class="table compact"><thead><tr><th>工具</th><th>能力族</th>'
                f'<th class="num">调用</th></tr></thead><tbody>{top_rows}</tbody></table>')
    family_tools = ''.join(
        f'<li><b>{esc(row["label"])}</b>{esc(" · ".join(row["names"]))}</li>'
        for row in view['tools'].get('by_family') or [])
    left_html = family_html
    if family_tools:
        left_html += f'<ul class="family-tools">{family_tools}</ul>'
    body = (f'<div class="two-col wide-left"><div>{left_html}</div>'
            f'<div>{top_html}</div></div>')
    return _section('sec-tools', '工具', '你实际在用哪些能力', body)


def _code(view: dict) -> str:
    code = view['code']
    if not code['languages'] and code['added'] == '0' and code['files'] == '0':
        return ''
    tiles = (f'<div class="tile-row">'
             f'<div class="tile"><b>{code["files"]}</b><span>涉及文件</span></div>'
             f'<div class="tile"><b class="pos">+{code["added"]}</b><span>新增行</span></div>'
             f'<div class="tile"><b class="neg">-{code["removed"]}</b><span>删除行</span></div>'
             f'<div class="tile"><b>{code["commits"]}</b><span>git commit</span></div>'
             f'<div class="tile"><b>{code["pushes"]}</b><span>git push</span></div>'
             f'</div>')
    languages = bar_list(code['languages'], color='#10b981')
    return _section('sec-code', '产出', '代码改动落在哪些语言上',
                    tiles + languages)


def _rhythm(view: dict) -> str:
    daily = column_chart(view['rhythm']['daily'], color='#6366f1')
    hours = hour_grid(view['rhythm']['hours'])
    response = histogram(view['rhythm']['response'], color='#f59e0b')
    parallel = view['parallel']
    parallel_note = ''
    if parallel['pairs']:
        parallel_note = (f'<p class="muted">有 <b>{parallel["pairs"]}</b> 组会话出现过 30 分钟内的并行使用，'
                         f'涉及 {parallel["sessions"]} 个会话、{parallel["messages"]} 条消息'
                         f'（占 {parallel["share"] * 100:.1f}%）。</p>')
    if not parallel_note:
        parallel_note = '<p class="muted">没有检测到并行会话。</p>'
    body = (f'<h4>每天的消息量</h4>{daily}'
            f'<h4>消息落在一天里的哪个时段</h4>{hours}'
            f'<div class="two-col"><div><h4>从发出到首次回复</h4>{response}'
            f'<p class="muted small">中位数 {esc(view["rhythm"]["median"])}，'
            f'平均 {esc(view["rhythm"]["avg"])}</p></div>'
            f'<div><h4>多会话并行</h4>{parallel_note}'
            f'</div></div>')
    return _section('sec-rhythm', '节奏', '你把 AI 用成了什么节奏', body)


def _friction(view: dict) -> str:
    friction = view['friction']
    tiles = (f'<div class="tile-row">'
             f'<div class="tile"><b>{friction["errors"]}</b><span>工具报错</span></div>'
             f'<div class="tile"><b>{friction["rate"]}%</b><span>报错率</span></div>'
             f'<div class="tile"><b>{friction["incomplete"]}</b><span>未完成结果</span></div>'
             f'</div>')
    categories = bar_list([
        {'label': item['label'], 'value': item['value']} for item in friction['categories']],
        color='#ef4444')
    tools = bar_list([
        {'label': item['label'], 'value': item['value']} for item in friction['tools']],
        color='#f97316')
    examples = ''.join(
        f'<li><code>{esc(item.get("tool") or "工具")}</code> '
        f'<span class="tag">{esc(item.get("category") or "报错")}</span> '
        f'<span class="muted">{esc(item.get("agent"))}</span><br>'
        f'{esc(item.get("text") or "（无错误正文）")}</li>'
        for item in friction['examples'][:8])
    examples_html = f'<h4>真实报错样本</h4><ul class="examples">{examples}</ul>' if examples else ''
    empty_note = ''
    if friction['empty_text'] and friction['errors']:
        empty_note = (f'<p class="muted small">其中 {friction["empty_text"]} 次导出包只留了失败状态、'
                      f'没有错误正文，按「未提供错误详情」计，不猜类型。</p>')
    body = (tiles + empty_note +
            f'<div class="two-col"><div><h4>错误类型</h4>{categories}</div>'
            f'<div><h4>报错最多的工具</h4>{tools}</div></div>{examples_html}')
    return _section('sec-friction', '摩擦', '哪里在漏时间', body)


def _facets(view: dict) -> str:
    data = view.get('facets')
    if not data:
        return ''
    coverage = data['coverage']
    tile_hint = (f'场会话已提取（原始 {coverage["raw_tasks"]} 条任务）'
                 if coverage.get('duplicates')
                 else f'/{coverage["tasks"]} 场会话（{coverage["ratio"]}%）')
    tiles = (f'<div class="tile-row">'
             f'<div class="tile"><b>{coverage["accepted"]}</b>'
             f'<span>{tile_hint}</span></div>'
             f'<div class="tile"><b>{coverage["evidence_pass"]}</b><span>证据逐字通过</span></div>'
             f'<div class="tile"><b>{data["closed_share"]}%</b><span>闭环率</span></div>'
             f'</div>')
    categories = bar_list(data['categories'], color='#0ea5e9')
    outcome_colors = {'closed': '#10b981', 'mostly': '#22d3ee',
                      'partial': '#f59e0b', 'open': '#ef4444'}
    outcomes = stacked_shares([
        {'label': row['label'], 'value': row['value'],
         'color': outcome_colors.get(row['label'], '#94a3b8')}
        for row in data['outcomes']])
    frictions = bar_list(data['frictions'], color='#ef4444') if data['frictions'] else ''
    instructions = ''.join(
        f'<li>{esc(item.get("text") or "")} <span class="muted">'
        f'{int(item.get("sessions") or 0)} 个会话</span></li>'
        for item in data['instructions'])
    instructions_html = (f'<h4>用户明确给过的约束（示例）</h4><ul class="project-notes">{instructions}</ul>'
                         if instructions else '')
    body = (tiles +
            f'<div class="two-col"><div><h4>目标分布</h4>{categories}</div>'
            f'<div><h4>结果达成</h4>{outcomes}'
            f'<p class="muted small">闭环 {data["closed_share"]}%：只统计明确被验证、'
            f'提交或用户认可的会话；自称完成但没有验证的不计入。</p></div></div>')
    if frictions:
        body += f'<h4>语义层看到的摩擦</h4>{frictions}'
    body += instructions_html
    dup_note = (f'另有 {coverage["duplicates"]} 条任务来自同一场对话的多客户端重复导出，已合并。'
                if coverage.get('duplicates') else '')
    note = (f'语义层只覆盖实质会话：已提取 {coverage["accepted"]}/{coverage["tasks"]} 场（{coverage["ratio"]}%），'
            f'{dup_note}证据逐字校验通过 {coverage["evidence_pass"]} 条。未提取的会话不代表没有问题。')
    return _section('sec-facets', '语义层', '这些会话最终做成了什么', body, note)


def _interaction(view: dict) -> str:
    interaction = view['sections']['interaction']
    if not interaction.get('narrative'):
        return ''
    pattern = interaction.get('key_pattern')
    body = md(interaction['narrative'])
    if pattern:
        body += f'<div class="callout">{md(pattern)}</div>'
    return _section('sec-interaction', '风格', '你怎么和 AI 配合', body)


def _wins(view: dict) -> str:
    data = view['sections']['what_works']
    items = data.get('impressive_workflows') or []
    if not items:
        return ''
    body = md(data.get('intro') or '')
    cards = ''.join(
        f'<div class="win"><h3>{esc(item.get("title") or "")}</h3>'
        f'{md(item.get("description") or "")}'
        + (f'<p class="source">来源：{esc(item["source"])}</p>' if item.get('source') else '')
        + '</div>'
        for item in items)
    return _section('sec-wins', '亮点', '做得漂亮的地方', body + cards)


def _friction_text(view: dict) -> str:
    data = view['sections']['friction']
    items = data.get('categories') or []
    if not items:
        return ''
    body = md(data.get('intro') or '')
    cards = ''.join(
        f'<div class="friction-item"><h3>{esc(item.get("category") or "")}</h3>'
        f'{md(item.get("description") or "")}'
        + ('<ul class="examples">'
           + ''.join(f'<li>{esc(example)}</li>' for example in item.get('examples') or [])
           + '</ul>' if item.get('examples') else '')
        + (f'<p class="source">来源：{esc(item["source"])}</p>' if item.get('source') else '')
        + '</div>'
        for item in items)
    return _section('sec-friction-text', '复盘', '问题出在哪',
                    body + f'<div class="friction-grid">{cards}</div>')


def _suggestions(view: dict) -> str:
    data = view['sections']['suggestions']
    features = data.get('features_to_try') or []
    additions = data.get('agents_md_additions') or []
    if not features and not additions:
        return ''
    feature_html = ''.join(
        f'<div class="suggestion"><h3>{esc(item.get("feature") or "")}</h3>'
        f'<div class="feature">{md(item.get("one_liner") or "")}'
        + (f'<div class="why">{md(item.get("why_for_you") or "")}</div>' if item.get('why_for_you') else '')
        + '</div>'
        + '</div>'
        for item in features)
    addition_html = ''.join(
        f'<div class="addition"><p class="rule">{esc(item.get("addition") or "")}</p>'
        + (f'<div class="why">{md(item.get("why") or "")}</div>' if item.get('why') else '')
        + (f'<p class="source">来源：{esc(item["source"])}</p>' if item.get('source') else '')
        + '</div>'
        for item in additions)
    body = ''
    if feature_html:
        body += f'<h3 class="sub">下一次可以试的能力</h3><div class="suggestion-grid">{feature_html}</div>'
    if addition_html:
        body += f'<h3 class="sub">写进 AGENTS.md 的规则</h3>{addition_html}'
    return _section('sec-suggestions', '建议', '马上能用的改进', body)


def _horizon(view: dict) -> str:
    data = view['sections']['horizon']
    items = data.get('opportunities') or []
    if not items:
        return ''
    body = md(data.get('intro') or '')
    cards = ''.join(
        f'<div class="horizon"><h3>{esc(item.get("title") or "")}</h3>'
        f'{md(item.get("description") or "")}</div>' for item in items)
    return _section('sec-horizon', '展望', '再往前一步', body + cards)


def _fun(view: dict) -> str:
    data = view['sections']['fun']
    if not data.get('headline'):
        return ''
    body = (f'<p class="fun-headline">{esc(data["headline"])}</p>'
            f'<div class="prose">{md(data.get("detail") or "")}</div>')
    return _section('sec-fun', '结尾', '一个有趣的观察', body)


def _footer(view: dict) -> str:
    notes = view.get('quality') or []
    quality_html = ''
    if notes:
        quality_html = ('<h4>数据说明与口径提示</h4><ul class="quality-list">'
                        + ''.join(f'<li>{esc(note)}</li>' for note in notes) + '</ul>')
    timezone = view.get('timezone') or ''
    tz_text = f'展示时区 {esc(timezone)}；' if timezone else ''
    return (f'<footer class="footer"><div class="prose">'
            f'<p>口径：实质会话 = 用户消息 ≥2 条且时长 ≥1 分钟；快速问答单独计数，'
            f'不混入主口径。工具调用、报错、代码行、token 均来自导出包，'
            f'{tz_text}窗口与导出窗口不对齐时以交集为准。</p>{quality_html}'
            f'<p class="muted small">报告由 insights 技能生成；叙事由 LLM 基于统计与真实消息撰写，'
            f'所有引用可在 stats.json 中回溯。</p></div></footer>')
