"""会话级指标：一个会话的 Event 列表 → SessionMetrics。

口径常量全部来自 constants.py；这里只做单会话计算与窗口筛选，不做全局聚合。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from .constants import (
    NARRATIVE_MESSAGE_CHARS,
    SUBSTANTIVE_MIN_DURATION_MINUTES,
    SUBSTANTIVE_MIN_USER_MESSAGES,
    TOOL_RESULT_ERROR_STATUSES,
    TOOL_RESULT_INCOMPLETE_STATUSES,
    utc_offset,
)
from .model import (
    Event,
    SessionMeta,
    SessionMetrics,
    git_effect,
    is_synthetic_user_message,
    language_from_path,
    local_hour,
    response_gaps,
    strip_error_banner,
    tool_effect,
    tool_error_category,
    truncate,
)
from .sources.base import Bundle
from .window import Window


def _duration_minutes(meta: SessionMeta, user_times: list[datetime],
                      assistant_times: list[datetime], events: list[Event],
                      window: Window | None) -> int:
    """会话时长。

    会话在导出窗口之前就已开始时，会话级 started_at 会把窗口外的时间也算进来，
    这时改用「窗口内事件的首尾跨度」，避免时长虚高。
    """
    started_before_window = (
        window is not None and meta.started_at is not None
        and int(meta.started_at.timestamp() * 1000) < window.start_ms)
    if not started_before_window and meta.started_at and meta.ended_at:
        return max(0, int((meta.ended_at - meta.started_at).total_seconds() // 60))
    marks = user_times + assistant_times or [e.ts for e in events]
    if len(marks) >= 2:
        span = max(marks) - min(marks)
        return max(0, int(span.total_seconds() // 60))
    return 0


def _build_metrics(meta: SessionMeta, events: list[Event], offset_hours: int,
                   window: Window | None = None) -> SessionMetrics:
    user_events = [e for e in events if e.type == 'user_message' and not e.synthetic]
    assistant_events = [e for e in events if e.type == 'assistant_message']
    tool_calls = [e for e in events if e.type == 'tool_call']
    tool_results = [e for e in events if e.type == 'tool_result']

    user_times = sorted(e.ts for e in user_events)
    assistant_times = sorted(e.ts for e in assistant_events)
    duration = _duration_minutes(meta, user_times, assistant_times, events, window)

    family_counter: Counter = Counter()
    name_counter: Counter = Counter()
    languages: Counter = Counter()
    files: set[str] = set()
    lines_added = lines_removed = 0
    commits = pushes = 0

    for call in tool_calls:
        family_counter[call.family] += 1
        name_counter[call.tool_name] += 1
        touched, added, removed, _ = tool_effect(call)
        for path in touched:
            normalized = _normalize_path(path)
            if normalized:
                files.add(normalized)
                language = _language_of(path)
                if language:
                    languages[language] += 1
        lines_added += added
        lines_removed += removed
        c, p = git_effect(call)
        commits += c
        pushes += p

    call_names = {call.tool_call_id: call.tool_name for call in tool_calls if call.tool_call_id}
    errors = 0
    incomplete = 0
    errors_without_text = 0
    categories: Counter = Counter()
    error_tools: Counter = Counter()
    for result in tool_results:
        status = (result.tool_status or '').lower()
        if status in TOOL_RESULT_ERROR_STATUSES:
            errors += 1
            tool_name = result.tool_name or call_names.get(result.tool_call_id, '')
            if not strip_error_banner(result.content):
                errors_without_text += 1
            categories[tool_error_category(result.content, tool_name)] += 1
            error_tools[tool_name or '（未知工具）'] += 1
        elif status in TOOL_RESULT_INCOMPLETE_STATUSES:
            incomplete += 1

    user_message_count = len(user_events)
    substantive = (user_message_count >= SUBSTANTIVE_MIN_USER_MESSAGES
                   and duration >= SUBSTANTIVE_MIN_DURATION_MINUTES)

    samples = [truncate(e.content, NARRATIVE_MESSAGE_CHARS) for e in user_events[:2]]
    title = (meta.title or '').strip()
    if not title or is_synthetic_user_message(title):
        title = truncate(user_events[0].content if user_events else meta.session_id, 80)
    return SessionMetrics(
        agent=meta.agent,
        session_id=meta.session_id,
        title=title,
        project=meta.project,
        cwd=meta.cwd,
        model=meta.model,
        started_at=meta.started_at,
        ended_at=meta.ended_at,
        duration_minutes=duration,
        user_messages=user_message_count,
        assistant_messages=len(assistant_events),
        tool_calls=len(tool_calls),
        tokens_input=meta.tokens_input,
        tokens_output=meta.tokens_output,
        substantive=substantive,
        user_message_times=user_times,
        assistant_message_times=assistant_times,
        user_message_samples=samples,
        first_prompt=truncate(user_events[0].content if user_events else '', 200),
        tool_family_counts=family_counter,
        tool_name_counts=name_counter,
        tools_used=[name for name, _ in name_counter.most_common(6)],
        files_touched=files,
        languages=languages,
        lines_added=lines_added,
        lines_removed=lines_removed,
        git_commits=commits,
        git_pushes=pushes,
        errors=errors,
        incomplete=incomplete,
        error_categories=categories,
        error_tool_counts=error_tools,
        errors_without_text=errors_without_text,
        response_times=response_gaps(user_times, assistant_times),
        message_hours=[local_hour(ts, offset_hours) for ts in user_times],
    )


def _normalize_path(path: str) -> str:
    cleaned = (path or '').strip().replace('\\', '/')
    if not cleaned:
        return ''
    return cleaned[0].lower() + cleaned[1:] if cleaned[0].isalpha() else cleaned


def _language_of(path: str) -> str | None:
    return language_from_path(path)


# ============================================================================
# 窗口与聚合
# ============================================================================


def select_sessions(bundle: Bundle, window: Window) -> tuple[list[SessionMetrics],
                                                             int]:
    """挑出窗口内的会话并计算指标。

    纳入规则（沿用旧口径）：会话至少有一条用户消息落在窗口内 → 整会话计入。
    返回 (指标列表, 窗口外被排除的会话数)。
    """
    by_session: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for event in bundle.events:
        by_session[(event.agent, event.session_id)].append(event)

    included: list[SessionMetrics] = []
    excluded = 0
    for meta in bundle.sessions:
        events = by_session.get((meta.agent, meta.session_id), [])
        in_window = any(
            e.type == 'user_message' and window.contains_ms(int(e.ts.timestamp() * 1000))
            for e in events
        )
        if not in_window:
            excluded += 1
            continue
        included.append(_build_metrics(meta, events, utc_offset(), window))
    return included, excluded
