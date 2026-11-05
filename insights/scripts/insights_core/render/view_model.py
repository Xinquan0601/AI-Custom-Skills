"""视图模型：stats + narratives + comparison → 渲染所需的纯数据。

这里不做 HTML 字符串拼接（那是 sections.py 的事），也不做业务口径判断
（那是 stats.py 的事）；只负责排版需要的派生值：占比、排序、格式化文本。
"""
from __future__ import annotations

from ..constants import (
    ERROR_CATEGORY_LABELS,
    ERROR_CATEGORY_SHORT,
    LABEL_MAP,
    TOOL_FAMILY_COLORS,
    TOOL_FAMILY_LABELS,
    TOOL_FAMILY_ORDER,
    TOP_ERROR_CATEGORIES,
    agent_color,
    agent_label,
)


def _label(key: str) -> str:
    return LABEL_MAP.get(key, key)


def _pct(part: float, total: float) -> float:
    return round(part / total * 100, 1) if total else 0.0


def _fmt_int(value) -> str:
    try:
        return f'{int(value):,}'
    except (TypeError, ValueError):
        return '—'


def _fmt_tokens(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return '—'
    if number >= 1e8:
        return f'{number / 1e8:.2f} 亿'
    if number >= 1e6:
        return f'{number / 1e6:.1f}M'
    return _fmt_int(number)


def _fmt_duration(minutes: float) -> str:
    if not minutes:
        return '0 分钟'
    if minutes < 60:
        return f'{minutes:.0f} 分钟'
    hours = minutes / 60
    return f'{hours:.1f} 小时'


def _fmt_seconds(seconds: float) -> str:
    if not seconds:
        return '—'
    if seconds < 60:
        return f'{seconds:.0f} 秒'
    return f'{seconds / 60:.1f} 分钟'


def _facets_view(doc: dict | None) -> dict | None:
    """语义层聚合结果 → 渲染用数据；没有提取结果时整块不出现。"""
    if not doc:
        return None
    coverage = doc.get('coverage') or {}
    summary = doc.get('summary') or {}
    accepted = int(coverage.get('accepted') or 0)
    if not accepted:
        return None
    from ..facets import FRICTION_TYPES, GOAL_CATEGORIES, OUTCOMES

    def rows(counts: dict, labels: dict) -> list[dict]:
        total = sum(counts.values()) or 1
        return [{'label': labels.get(key, key), 'value': value,
                 'share': round(value / total * 100, 1)}
                for key, value in sorted(counts.items(), key=lambda item: -item[1]) if value]

    outcomes = rows(summary.get('by_outcome') or {}, OUTCOMES)
    closed = (summary.get('by_outcome') or {}).get('closed', 0)
    tasks = int(coverage.get('unique_tasks') or coverage.get('tasks') or 0)
    return {
        'coverage': {
            'accepted': accepted,
            'tasks': tasks,
            'raw_tasks': int(coverage.get('tasks') or tasks),
            'duplicates': int(coverage.get('duplicates_merged') or 0),
            'ratio': round(accepted / tasks * 100, 1) if tasks else 0.0,
            'evidence_pass': int(coverage.get('evidence_pass') or 0),
        },
        'categories': rows(summary.get('by_category') or {}, GOAL_CATEGORIES),
        'outcomes': outcomes,
        'frictions': rows(summary.get('by_friction') or {}, FRICTION_TYPES),
        'instructions': (summary.get('instructions') or [])[:6],
        'closed_share': round(closed / accepted * 100, 1),
    }


def build(stats: dict, narratives: dict, comparison, facets_doc: dict | None = None) -> dict:
    totals = stats.get('totals') or {}
    window = stats.get('window') or {}
    source = stats.get('source') or {}
    agents = stats.get('agents') or []
    projects = stats.get('projects') or []
    tools = stats.get('tools') or {}
    code = stats.get('code') or {}
    rhythm = stats.get('rhythm') or {}
    friction = stats.get('friction') or {}
    parallel = stats.get('parallel') or {}

    messages_total = totals.get('user_messages') or 0
    sessions_total = totals.get('sessions') or 0

    agent_rows = []
    for agent in agents:
        agent_rows.append({
            'key': agent['key'],
            'label': agent['label'],
            'color': agent_color(agent['key']),
            'sessions': agent['sessions'],
            'substantive': agent['substantive'],
            'quick': agent['quick'],
            'messages': agent['user_messages'],
            'messages_share': _pct(agent['user_messages'], messages_total),
            'tool_calls': agent['tool_calls'],
            'errors': agent['errors'],
            'error_rate': _pct(agent['errors'], agent['tool_calls']),
            'duration': _fmt_duration(agent['duration_minutes']),
            'top_tools': [{'name': tool['name'],
                           'count': tool['count'],
                           'family': TOOL_FAMILY_LABELS.get(tool['family'], tool['family'])}
                          for tool in agent.get('top_tools') or []],
        })

    area_notes = {
        str(area.get('name') or ''): str(area.get('description') or '').strip()
        for area in ((narratives.get('project_areas') or {}).get('areas') or [])
    }
    project_rows = []
    for project in projects:
        project_rows.append({
            'name': project['name'],
            'summary': area_notes.get(project['name'], ''),
            'sessions': project['sessions'],
            'messages': project['user_messages'],
            'share': _pct(project['user_messages'], messages_total),
            'tool_calls': project['tool_calls'],
            'errors': project['errors'],
            'agents': [agent_label(key) for key in (project.get('agents') or {})],
        })

    family_values = tools.get('families') or {}
    family_rows = [
        {'key': family,
         'label': TOOL_FAMILY_LABELS[family],
         'value': family_values.get(family, 0),
         'color': TOOL_FAMILY_COLORS[family]}
        for family in TOOL_FAMILY_ORDER if family_values.get(family, 0)
    ]
    family_tools = []
    for family in TOOL_FAMILY_ORDER:
        names = (tools.get('by_family') or {}).get(family) or []
        if names:
            family_tools.append({
                'label': TOOL_FAMILY_LABELS[family],
                'names': [f'{item["name"]} {item["count"]}' for item in names],
            })
    tool_rows = [
        {'name': tool['name'],
         'count': tool['count'],
         'family': TOOL_FAMILY_LABELS.get(tool['family'], tool['family'])}
        for tool in tools.get('top_tools') or []
    ]

    language_rows = [
        {'label': language, 'value': count}
        for language, count in (code.get('languages') or {}).items()
    ]

    daily_rows = []
    for day in rhythm.get('daily') or []:
        daily_rows.append({
            'label': day['date'][5:],
            'value': day['messages'],
            'title': f'{day["date"]}：{day["messages"]} 条消息 / {day["sessions"]} 个会话',
        })

    response_buckets = _response_buckets(rhythm.get('response_times') or [])

    error_category_rows = [
        {'label': ERROR_CATEGORY_SHORT.get(category,
                                            ERROR_CATEGORY_LABELS.get(category, category)),
         'value': count}
        for category, count in (friction.get('categories') or {}).items()
    ][:TOP_ERROR_CATEGORIES]
    error_tool_rows = [
        {'label': item['name'], 'value': item['count']}
        for item in (friction.get('by_tool') or [])
    ]

    sessions = stats.get('sessions') or []
    heavy_sessions = sorted(sessions, key=lambda s: -s.get('tool_calls', 0))[:5]

    overview = narratives.get('overview') or {}
    sections = {
        'overview': [
            ('做得好的地方', overview.get('whats_working'), '#sec-wins'),
            ('拖后腿的地方', overview.get('whats_hindering'), '#sec-friction'),
            ('可以立刻试的改进', overview.get('quick_wins'), '#sec-suggestions'),
            ('进阶工作流', overview.get('ambitious_workflows'), '#sec-horizon'),
        ],
        'interaction': narratives.get('interaction_style') or {},
        'areas': ((narratives.get('project_areas') or {}).get('areas') or []),
        'what_works': narratives.get('what_works') or {},
        'friction': narratives.get('friction_analysis') or {},
        'suggestions': narratives.get('suggestions') or {},
        'horizon': narratives.get('on_the_horizon') or {},
        'fun': narratives.get('fun_ending') or {},
        'comparison': narratives.get('comparison_narrative') or {},
    }
    sections['overview'] = [
        {'prefix': prefix, 'text': text, 'href': href}
        for prefix, text, href in sections['overview'] if str(text or '').strip()
    ]

    source_label = 'AgentTrail 导出包'
    if source.get('exported_at'):
        source_label += f' · 导出于 {source["exported_at"][:16].replace("T", " ")} UTC'

    stat_cards = [
        {'label': '实质会话', 'value': _fmt_int(totals.get('substantive_sessions')),
         'hint': f'另 {_fmt_int(totals.get("quick_sessions"))} 个快速问答'},
        {'label': '用户消息', 'value': _fmt_int(totals.get('user_messages')),
         'hint': f'{_fmt_int(totals.get("assistant_messages"))} 条助手回复'},
        {'label': '工具调用', 'value': _fmt_int(totals.get('tool_calls')),
         'hint': f'报错 {_fmt_int(totals.get("tool_errors"))} 次'},
        {'label': '代码改动', 'value': f'+{_fmt_int(totals.get("lines_added"))}',
         'hint': f'-{_fmt_int(totals.get("lines_removed"))} 行 / {_fmt_int(totals.get("files_touched"))} 个文件'},
        {'label': '活跃天数', 'value': _fmt_int(totals.get('days_active')),
         'hint': f'{_fmt_int(totals.get("active_hours"))} 个活跃小时'},
        {'label': 'Token 消耗', 'value': _fmt_tokens((totals.get('tokens_input') or 0)
                                                  + (totals.get('tokens_output') or 0)),
         'hint': f'{_fmt_int(totals.get("token_sessions"))}/{_fmt_int(totals.get("sessions"))} 个会话有记录'},
    ]

    comparison_view = None
    if comparison is not None:
        comparison_view = {
            'available': comparison.available,
            'period': comparison.period,
            'prev_window': comparison.prev_window,
            'prev_path': comparison.prev_path,
            'rows': comparison.rows,
            'notes': comparison.notes,
            'text': sections['comparison'],
        }

    quality = []
    for warning in stats.get('warnings') or []:
        quality.append(warning)
    if window.get('clamped'):
        quality.append(f'用户请求窗口超出导出范围，已裁剪为 {window.get("description")}')

    return {
        'title': 'AI 使用洞察报告',
        'window_label': window.get('description', ''),
        'window_days': window.get('days'),
        'timezone': window.get('timezone') or '',
        'period': window.get('period'),
        'source_label': source_label,
        'chips': [
            ('会话', _fmt_int(sessions_total)),
            ('消息', _fmt_int(messages_total)),
            ('工具调用', _fmt_int(totals.get('tool_calls'))),
            ('Agent', str(len(agents))),
        ],
        'stat_cards': stat_cards,
        'sections': sections,
        'comparison': comparison_view,
        'agents': agent_rows,
        'projects': project_rows,
        'tools': {'families': family_rows, 'top': tool_rows,
                  'by_family': family_tools},
        'code': {
            'languages': language_rows,
            'files': _fmt_int(code.get('files')),
            'added': _fmt_int(code.get('lines_added')),
            'removed': _fmt_int(code.get('lines_removed')),
            'commits': _fmt_int(code.get('git_commits')),
            'pushes': _fmt_int(code.get('git_pushes')),
            'sessions_with_files': _fmt_int(code.get('sessions_with_files')),
        },
        'rhythm': {
            'daily': daily_rows,
            'hours': rhythm.get('hours') or [0] * 24,
            'response': response_buckets,
            'median': _fmt_seconds(rhythm.get('median_response_seconds')),
            'avg': _fmt_seconds(rhythm.get('avg_response_seconds')),
        },
        'parallel': {
            'pairs': parallel.get('overlap_pairs', 0),
            'sessions': parallel.get('sessions_involved', 0),
            'messages': parallel.get('messages_involved', 0),
            'share': parallel.get('message_share', 0),
        },
        'friction': {
            'errors': _fmt_int(friction.get('tool_errors')),
            'rate': round((friction.get('error_rate') or 0) * 100, 1),
            'incomplete': _fmt_int(friction.get('incomplete_results')),
            'empty_text': _fmt_int(friction.get('empty_text')),
            'categories': error_category_rows,
            'tools': error_tool_rows,
            'examples': friction.get('examples') or [],
        },
        'heavy_sessions': heavy_sessions,
        'facets': _facets_view(facets_doc),
        'quality': quality,
    }


def _response_buckets(times: list[float]) -> list[dict]:
    buckets = [
        ('2-10 秒', 0, 10), ('10-30 秒', 10, 30), ('30 秒-1 分', 30, 60),
        ('1-2 分', 60, 120), ('2-5 分', 120, 300), ('5-15 分', 300, 900),
        ('>15 分', 900, None),
    ]
    rows = [{'label': label, 'count': 0} for label, _, _ in buckets]
    for value in times:
        for index, (_label, low, high) in enumerate(buckets):
            if (high is None and value >= low) or (high is not None and low <= value < high):
                rows[index]['count'] += 1
                break
    return rows
