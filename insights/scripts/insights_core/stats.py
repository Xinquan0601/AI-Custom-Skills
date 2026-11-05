"""全局聚合：SessionMetrics 列表 → stats.json 的 aggregated_data。

只做汇总与派生（占比、Top 榜、节奏、摩擦），不读文件、不打印。
输出结构见 docs/stats-schema.md。
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from .constants import (
    ERROR_CATEGORY_LABELS,
    NARRATIVE_SESSION_SAMPLES,
    PARALLEL_OVERLAP_WINDOW_MS,
    SCHEMA_VERSION,
    SESSION_SUMMARY_CHARS,
    TOOL_RESULT_ERROR_STATUSES,
    TOP_ERROR_CATEGORIES,
    TOP_ERROR_TOOLS,
    TOP_PROJECTS,
    TOP_TOOLS,
    agent_label,
    tool_family,
    utc_offset,
)
from .model import (
    SessionMetrics,
    language_from_path,
    local_date,
    local_hour,
    local_iso,
    strip_error_banner,
    tool_error_category,
    truncate,
)
from .sources.base import Bundle
from .window import Window


def detect_parallel_sessions(sessions: list[SessionMetrics]) -> dict:
    """30 分钟窗口内两个会话的消息交错，记为一次并行。"""
    marks: list[tuple[int, str]] = []
    for session in sessions:
        for ts in session.user_message_times:
            marks.append((int(ts.timestamp() * 1000), session.session_id))
    marks.sort()

    pairs: set[tuple[str, str]] = set()
    involved: set[str] = set()
    involved_marks: set[tuple[int, str]] = set()
    left = 0
    for right, (ts, _sid) in enumerate(marks):
        while ts - marks[left][0] > PARALLEL_OVERLAP_WINDOW_MS:
            left += 1
        window_slice = marks[left:right + 1]
        distinct = {sid for _t, sid in window_slice}
        if len(distinct) >= 2:
            ordered = sorted(distinct)
            for i in range(len(ordered)):
                for j in range(i + 1, len(ordered)):
                    pairs.add((ordered[i], ordered[j]))
                    involved.add(ordered[i])
                    involved.add(ordered[j])
            for mark in window_slice:
                involved_marks.add(mark)

    total_user_marks = len(marks)
    return {
        'overlap_pairs': len(pairs),
        'sessions_involved': len(involved),
        'messages_involved': len(involved_marks),
        'messages_total': total_user_marks,
        'message_share': round(len(involved_marks) / total_user_marks, 4) if total_user_marks else 0.0,
    }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def aggregate(sessions: list[SessionMetrics], window: Window,
              bundle: Bundle, excluded: int) -> dict:
    """把会话指标汇总成 stats.json 的 aggregated_data 部分。"""
    substantive = [s for s in sessions if s.substantive]
    quick = [s for s in sessions if not s.substantive]

    agents: dict[str, dict] = {}
    for session in sessions:
        entry = agents.setdefault(session.agent, {
            'key': session.agent, 'label': agent_label(session.agent),
            'sessions': 0, 'substantive': 0, 'quick': 0, 'user_messages': 0,
            'assistant_messages': 0, 'tool_calls': 0, 'errors': 0, 'incomplete': 0,
            'tokens_input': 0, 'tokens_output': 0, 'duration_minutes': 0,
            'files_touched': 0, 'lines_added': 0, 'lines_removed': 0,
            'tool_families': Counter(), 'top_tools': Counter(), 'projects': Counter(),
        })
        entry['sessions'] += 1
        entry['substantive' if session.substantive else 'quick'] += 1
        entry['user_messages'] += session.user_messages
        entry['assistant_messages'] += session.assistant_messages
        entry['tool_calls'] += session.tool_calls
        entry['errors'] += session.errors
        entry['incomplete'] += session.incomplete
        entry['tokens_input'] += session.tokens_input
        entry['tokens_output'] += session.tokens_output
        entry['duration_minutes'] += session.duration_minutes
        entry['files_touched'] += len(session.files_touched)
        entry['lines_added'] += session.lines_added
        entry['lines_removed'] += session.lines_removed
        entry['tool_families'].update(session.tool_family_counts)
        entry['top_tools'].update(session.tool_name_counts)
        entry['projects'][session.project] += 1

    agent_list = []
    for entry in agents.values():
        entry['tool_families'] = dict(entry['tool_families'])
        entry['top_tools'] = [{'name': n, 'count': c, 'family': tool_family(n)}
                              for n, c in entry['top_tools'].most_common(5)]
        entry['projects'] = dict(entry['projects'])
        agent_list.append(entry)
    agent_list.sort(key=lambda a: (-a['user_messages'], a['label']))

    projects: dict[str, dict] = {}
    for session in sessions:
        name = session.project or '（未标注项目）'
        entry = projects.setdefault(name, {
            'name': name, 'sessions': 0, 'substantive': 0, 'quick': 0, 'user_messages': 0,
            'tool_calls': 0, 'errors': 0, 'lines_added': 0, 'lines_removed': 0,
            'agents': Counter(), 'duration_minutes': 0,
        })
        entry['sessions'] += 1
        entry['substantive' if session.substantive else 'quick'] += 1
        entry['user_messages'] += session.user_messages
        entry['tool_calls'] += session.tool_calls
        entry['errors'] += session.errors
        entry['lines_added'] += session.lines_added
        entry['lines_removed'] += session.lines_removed
        entry['duration_minutes'] += session.duration_minutes
        entry['agents'][session.agent] += 1

    project_list = sorted(projects.values(), key=lambda p: -p['user_messages'])
    for entry in project_list:
        entry['agents'] = dict(entry['agents'])
        entry['agent_labels'] = [agent_label(a) for a in entry['agents']]

    families: Counter = Counter()
    tools: Counter = Counter()
    for session in sessions:
        families.update(session.tool_family_counts)
        tools.update(session.tool_name_counts)

    file_languages: Counter = Counter()
    for session in sessions:
        for path in session.files_touched:
            language = language_from_path(path)
            if language:
                file_languages[language] += 1

    code = {
        'files': len(_all_files(sessions)),
        'languages': dict(file_languages.most_common(12)),
        'lines_added': sum(s.lines_added for s in sessions),
        'lines_removed': sum(s.lines_removed for s in sessions),
        'git_commits': sum(s.git_commits for s in sessions),
        'git_pushes': sum(s.git_pushes for s in sessions),
        'sessions_with_files': sum(1 for s in sessions if s.files_touched),
    }

    response_times = [gap for s in sessions for gap in s.response_times]
    hours = [0] * 24
    for session in sessions:
        for hour in session.message_hours:
            hours[hour] += 1
    daily: dict[str, dict] = {}
    for session in sessions:
        for ts in session.user_message_times:
            day = local_date(ts, utc_offset())
            daily.setdefault(day, {'date': day, 'messages': 0, 'sessions': set()})
            daily[day]['messages'] += 1
            daily[day]['sessions'].add(session.session_id)
    daily_list = [{'date': d['date'], 'messages': d['messages'],
                   'sessions': len(d['sessions'])} for d in sorted(daily.values(),
                                                                  key=lambda x: x['date'])]
    active_slots = {(local_date(ts, utc_offset()), local_hour(ts, utc_offset()))
                    for session in sessions for ts in session.user_message_times}

    error_categories: Counter = Counter()
    error_by_agent: Counter = Counter()
    error_by_tool: Counter = Counter()
    for session in sessions:
        error_categories.update(session.error_categories)
        error_by_tool.update(session.error_tool_counts)
        if session.errors:
            error_by_agent[session.agent] += session.errors

    tool_calls_total = sum(s.tool_calls for s in sessions)
    errors_total = sum(s.errors for s in sessions)

    sessions_with_tokens = sum(1 for s in sessions if s.tokens_input or s.tokens_output)
    totals = {
        'sessions': len(sessions),
        'substantive_sessions': len(substantive),
        'quick_sessions': len(quick),
        'scanned_sessions': len(bundle.sessions),
        'excluded_sessions': excluded,
        'user_messages': sum(s.user_messages for s in sessions),
        'assistant_messages': sum(s.assistant_messages for s in sessions),
        'tool_calls': tool_calls_total,
        'tool_errors': errors_total,
        'incomplete_results': sum(s.incomplete for s in sessions),
        'duration_minutes': sum(s.duration_minutes for s in sessions),
        'tokens_input': sum(s.tokens_input for s in sessions),
        'tokens_output': sum(s.tokens_output for s in sessions),
        'token_sessions': sessions_with_tokens,
        'files_touched': code['files'],
        'lines_added': code['lines_added'],
        'lines_removed': code['lines_removed'],
        'days_active': len(daily_list),
        'active_hours': len(active_slots),
        'messages_per_day': round(sum(s.user_messages for s in sessions) / len(daily_list), 1)
        if daily_list else 0.0,
        'median_response_seconds': _median(response_times),
        'avg_response_seconds': round(sum(response_times) / len(response_times), 1)
        if response_times else 0.0,
        'error_rate': round(errors_total / tool_calls_total, 4) if tool_calls_total else 0.0,
    }

    family_tools: dict[str, list[dict]] = {}
    for name, count in tools.most_common():
        bucket = family_tools.setdefault(tool_family(name), [])
        if len(bucket) < 2:
            bucket.append({'name': name, 'count': count})

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    session_rows = [_session_row(s, window) for s in sorted(
        sessions, key=lambda s: s.started_at or epoch, reverse=True)]

    duplicates = detect_duplicate_sessions(sessions)
    warnings = _quality_notes(bundle, sessions, sessions_with_tokens)
    if duplicates['extra_sessions']:
        warnings.append(
            f"导出包里有 {duplicates['extra_sessions']} 个会话是同一场对话的多客户端重复导出"
            f"（{duplicates['groups']} 组，其中 {duplicates['extra_substantive']} 个实质会话），"
            f'会话数与消息量按原始数据统计、未去重；语义层已按会话合并')

    return {
        'schema_version': SCHEMA_VERSION,
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'source': _source_block(bundle, window),
        'window': _window_block(window),
        'totals': totals,
        'agents': agent_list,
        'projects': project_list,
        'tools': {
            'families': dict(families),
            'by_agent': {a['key']: a['tool_families'] for a in agent_list},
            'top_tools': [{'name': n, 'count': c, 'family': tool_family(n)}
                          for n, c in tools.most_common(TOP_TOOLS)],
            'by_family': family_tools,
        },
        'code': code,
        'rhythm': {
            'hours': hours,
            'daily': daily_list,
            'response_times': response_times,
            'median_response_seconds': totals['median_response_seconds'],
            'avg_response_seconds': totals['avg_response_seconds'],
        },
        'parallel': detect_parallel_sessions(sessions),
        'friction': {
            'tool_errors': errors_total,
            'error_rate': totals['error_rate'],
            'incomplete_results': totals['incomplete_results'],
            'empty_text': sum(s.errors_without_text for s in sessions),
            'categories': dict(error_categories.most_common(TOP_ERROR_CATEGORIES)),
            'by_agent': dict(error_by_agent),
            'by_tool': [{'name': n, 'count': c} for n, c in error_by_tool.most_common(TOP_ERROR_TOOLS)],
            'examples': _error_examples(bundle, window),
        },
        'sessions': session_rows,
        'duplicates': duplicates,
        'narrative_material': _narrative_material(sessions, error_categories),
        'warnings': warnings,
    }


# ============================================================================
# 辅助
# ============================================================================


_CLIENT_PREFIX = re.compile(r'^(?:opencode-[a-z]+:)+')


def detect_duplicate_sessions(sessions: list[SessionMetrics]) -> dict:
    """同一场对话被多个客户端各导出一份：id 去掉客户端前缀后相同即视为重复。"""
    groups: dict[tuple[str, str], list[SessionMetrics]] = {}
    for session in sessions:
        key = (session.project or '', _CLIENT_PREFIX.sub('', session.session_id))
        groups.setdefault(key, []).append(session)
    duplicate_groups = [members for members in groups.values() if len(members) > 1]
    clients = sorted({match.group(1).rstrip(':') for session in sessions
                      if (match := re.match(r'^(opencode-[a-z]+):', session.session_id))})
    return {
        'groups': len(duplicate_groups),
        'extra_sessions': sum(len(members) - 1 for members in duplicate_groups),
        'extra_substantive': sum(1 for members in duplicate_groups
                                 for session in members[1:] if session.substantive),
        'clients': clients,
    }


def _all_files(sessions: list[SessionMetrics]) -> set[str]:
    files: set[str] = set()
    for session in sessions:
        files |= session.files_touched
    return files


def _merge_counters(counters) -> Counter:
    merged: Counter = Counter()
    for counter in counters:
        merged.update(counter)
    return merged


def _session_row(session: SessionMetrics, window: Window) -> dict:
    return {
        'id': session.session_id,
        'agent': session.agent,
        'agent_label': agent_label(session.agent),
        'title': truncate(session.title or session.first_prompt, SESSION_SUMMARY_CHARS),
        'project': session.project,
        'started_at': local_iso(session.started_at, utc_offset()),
        'ended_at': local_iso(session.ended_at, utc_offset()),
        'duration_minutes': session.duration_minutes,
        'substantive': session.substantive,
        'user_messages': session.user_messages,
        'tool_calls': session.tool_calls,
        'errors': session.errors,
        'tokens_input': session.tokens_input,
        'tokens_output': session.tokens_output,
        'files': len(session.files_touched),
        'lines_added': session.lines_added,
        'lines_removed': session.lines_removed,
        'tools': session.tools_used,
        'model': session.model,
    }


def _narrative_material(sessions: list[SessionMetrics],
                        error_categories: Counter) -> dict:
    """给 LLM 写叙事用的证据集：项目、工具组合、错误、真实原话。"""
    by_project: Counter = Counter()
    for session in sessions:
        by_project[session.project or '（未标注项目）'] += 1

    combos: Counter = Counter()
    for session in sessions:
        families = tuple(sorted(session.tool_family_counts))
        if len(families) >= 2:
            combos[families] += 1

    ordered = sorted(sessions, key=lambda s: (-s.tool_calls, -s.user_messages))
    samples = []
    for session in ordered[:NARRATIVE_SESSION_SAMPLES]:
        samples.append({
            'session': session.session_id,
            'agent': session.agent,
            'agent_label': agent_label(session.agent),
            'project': session.project,
            'title': truncate(session.title, 100),
            'tools': session.tools_used,
            'messages': session.user_message_samples,
        })

    return {
        'repeated_projects': [{'project': p, 'sessions': c}
                              for p, c in by_project.most_common(TOP_PROJECTS) if c >= 2],
        'tool_combos': [{'families': list(combo), 'sessions': count}
                        for combo, count in combos.most_common(8)],
        'error_categories': [{'category': c, 'count': n}
                             for c, n in error_categories.most_common(TOP_ERROR_CATEGORIES)],
        'session_samples': samples,
    }


def _error_examples(bundle: Bundle, window: Window, limit: int = 12) -> list[dict]:
    """报错样本：剥掉沙箱尾巴、去重，并保证同类型最多两条。"""
    call_names: dict[tuple[str, str, str], str] = {}
    for event in bundle.events:
        if event.type == 'tool_call' and event.tool_call_id:
            call_names[(event.agent, event.session_id, event.tool_call_id)] = event.tool_name
    seen: set[str] = set()
    per_category: Counter = Counter()
    examples = []
    for event in bundle.events:
        if event.type != 'tool_result':
            continue
        if (event.tool_status or '').lower() not in TOOL_RESULT_ERROR_STATUSES:
            continue
        if not window.contains_ms(int(event.ts.timestamp() * 1000)):
            continue
        body = strip_error_banner(event.content or '')
        if not body:
            continue
        tool_name = event.tool_name or call_names.get(
            (event.agent, event.session_id, event.tool_call_id), '')
        category = tool_error_category(body, tool_name)
        if per_category[category] >= 2:
            continue
        text = truncate(body, 180)
        if text[:60] in seen:
            continue
        seen.add(text[:60])
        per_category[category] += 1
        examples.append({
            'agent': event.agent,
            'tool': tool_name or '（未知工具）',
            'category': ERROR_CATEGORY_LABELS.get(category, category),
            'text': text,
        })
        if len(examples) >= limit:
            break
    return examples


def _quality_notes(bundle: Bundle, sessions: list[SessionMetrics],
                   sessions_with_tokens: int) -> list[str]:
    notes = list(bundle.warnings)
    if sessions and sessions_with_tokens < len(sessions):
        notes.append(
            f'token 只有 {sessions_with_tokens}/{len(sessions)} 个会话有记录，'
            f'各 Agent 的上报口径也不同，合计值仅作量级参考')
    errors = sum(s.errors for s in sessions)
    empty = sum(s.errors_without_text for s in sessions)
    if errors and empty * 2 >= errors:
        notes.append(
            f'{errors} 次报错里有 {empty} 次导出包没留错误正文，只能记为「未提供错误详情」，'
            f'错误类型分布只能反映有正文的那一小部分')
    return notes


def _source_block(bundle: Bundle, window: Window) -> dict:
    return {
        'kind': bundle.kind,
        'path': str(bundle.path),
        'export_version': bundle.export_version,
        'exported_at': bundle.generated_at,
        'export_window': {'from': bundle.window_start_utc, 'to': bundle.window_end_utc},
        'counts': {
            'sessions': bundle.counts.get('sessions', len(bundle.sessions)),
            'events': bundle.counts.get('events', len(bundle.events)),
            'tool_calls': bundle.counts.get('tool_calls', 0),
        },
        'agents': bundle.agent_keys,
        'warnings': list(bundle.warnings),
    }


def _window_block(window: Window) -> dict:
    return {
        'since': window.since.isoformat(),
        'until': window.until.isoformat(),
        'days': window.days,
        'description': window.description,
        'period': window.period,
        'source': window.source,
        'clamped': window.clamped,
        'timezone': f'UTC{utc_offset():+d}',
    }

STATS_KEYS = ('schema_version', 'source', 'window', 'totals', 'agents', 'projects',
              'tools', 'code', 'rhythm', 'parallel', 'friction', 'sessions')


def check_stats(stats: dict) -> list[str]:
    """stats.json 的结构自检，返回错误列表（空列表才允许渲染）。"""
    errors: list[str] = []
    if not isinstance(stats, dict):
        return ['stats 顶层不是对象']
    if stats.get('schema_version') != SCHEMA_VERSION:
        errors.append(f'schema_version 应为 {SCHEMA_VERSION}，实际 {stats.get("schema_version")!r}')
    missing = [key for key in STATS_KEYS if key not in stats]
    if missing:
        errors.append(f'缺字段：{", ".join(missing)}')
        return errors
    for key in ('source', 'window', 'totals', 'tools', 'code', 'rhythm', 'parallel', 'friction'):
        if not isinstance(stats[key], dict):
            errors.append(f'{key} 必须是对象')
    for key in ('agents', 'projects', 'sessions'):
        if not isinstance(stats[key], list):
            errors.append(f'{key} 必须是数组')
    window = stats['window']
    for key in ('since', 'until', 'description'):
        if not window.get(key):
            errors.append(f'window.{key} 不能为空')
    return errors
