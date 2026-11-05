"""领域模型：事件、会话元数据、会话指标，以及工具入参的提取规则。

数据源只负责产出 Event / SessionMeta；这里定义它们的形状与「怎么从工具入参里
读出文件、行数、命令」——同一语义只在本文件定义一次，统计与渲染都不再解析原始字段。
"""
from __future__ import annotations

import difflib
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .constants import (
    EXTENSION_TO_LANGUAGE,
    PATCH_TOOL_NAMES,
    SHELL_TOOL_NAMES,
    WRITE_TOOL_NAMES,
    tool_family,
)

# ============================================================================
# 时间与解析辅助
# ============================================================================


def parse_utc(value: str | None) -> datetime | None:
    """解析 ISO-8601（可带 Z / 偏移），统一成 UTC aware datetime；失败返回 None。"""
    if not value:
        return None
    text = str(value).strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_epoch_ms(dt: datetime | None) -> int | None:
    return int(dt.timestamp() * 1000) if dt else None


def local_hour(dt: datetime, offset_hours: int) -> int:
    """UTC 时间 → 展示时区的小时（0-23）。"""
    return (dt.hour + offset_hours) % 24


def local_date(dt: datetime, offset_hours: int) -> str:
    """UTC 时间 → 展示时区的日期字符串（YYYY-MM-DD）。"""
    from datetime import timedelta
    return (dt + timedelta(hours=offset_hours)).strftime('%Y-%m-%d')


def local_iso(dt: datetime | None, offset_hours: int) -> str:
    """UTC 时间 → 展示时区的「YYYY-MM-DD HH:MM」。"""
    if not dt:
        return ''
    from datetime import timedelta
    return (dt + timedelta(hours=offset_hours)).strftime('%Y-%m-%d %H:%M')


# ============================================================================
# 事件与会话元数据
# ============================================================================


@dataclass(frozen=True)
class Event:
    """规范化事件：一行 events.csv。

    tool_input 为解析后的 dict（可能是空 dict）；原始串保留在 tool_input_raw，
    便于错误信息里回显。tool_status 只在 tool_result 上有语义。
    """
    event_id: str
    agent: str
    session_id: str
    type: str
    ts: datetime
    content: str = ''
    tool_name: str = ''
    tool_call_id: str = ''
    tool_status: str = ''
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_input_raw: str = ''
    model: str = ''
    tokens_input: int = 0
    tokens_output: int = 0
    synthetic: bool = False

    @property
    def family(self) -> str:
        return tool_family(self.tool_name)


@dataclass(frozen=True)
class SessionMeta:
    """会话元数据：一行 sessions.csv（数据源侧的完整聚合，优先于事件重算）。"""
    agent: str
    session_id: str
    title: str
    project: str
    model: str
    cwd: str
    started_at: datetime | None
    ended_at: datetime | None
    message_count: int
    user_message_count: int
    assistant_message_count: int
    tool_call_count: int
    tool_result_count: int
    event_count: int
    tokens_input: int
    tokens_output: int
    source_path: str = ''


@dataclass
class SessionMetrics:
    """一个会话在统计窗口内的全部派生指标（统计层唯一的中间产物）。"""
    agent: str
    session_id: str
    title: str
    project: str
    cwd: str
    model: str
    started_at: datetime | None
    ended_at: datetime | None
    duration_minutes: int
    user_messages: int
    assistant_messages: int
    tool_calls: int
    tokens_input: int
    tokens_output: int
    substantive: bool
    user_message_times: list[datetime] = field(default_factory=list)
    assistant_message_times: list[datetime] = field(default_factory=list)
    user_message_samples: list[str] = field(default_factory=list)
    first_prompt: str = ''
    tool_family_counts: Counter = field(default_factory=Counter)
    tool_name_counts: Counter = field(default_factory=Counter)
    tools_used: list[str] = field(default_factory=list)
    files_touched: set[str] = field(default_factory=set)
    languages: Counter = field(default_factory=Counter)
    lines_added: int = 0
    lines_removed: int = 0
    git_commits: int = 0
    git_pushes: int = 0
    errors: int = 0
    incomplete: int = 0
    error_categories: Counter = field(default_factory=Counter)
    error_tool_counts: Counter = field(default_factory=Counter)
    errors_without_text: int = 0
    response_times: list[float] = field(default_factory=list)
    message_hours: list[int] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return self.title or self.first_prompt or self.session_id


# ============================================================================
# 工具入参提取（同一语义只在这里定义）
# ============================================================================


def tool_input_dict(event: Event) -> dict[str, Any]:
    if isinstance(event.tool_input, dict):
        return event.tool_input
    return {}


def _first_str(mapping: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ''


FILE_PATH_KEYS = ('file_path', 'filePath', 'path', 'image_path', 'imagePath',
                  'notebook_path', 'notebookPath', 'target_file')
OLD_STRING_KEYS = ('old_string', 'oldString', 'old_str', 'oldStr', 'old_text')
NEW_STRING_KEYS = ('new_string', 'newString', 'new_str', 'newStr', 'new_text')
CONTENT_KEYS = ('content', 'contents', 'text', 'file_text')
COMMAND_KEYS = ('command', 'cmd', 'script')


def extract_file_path(event: Event) -> str:
    return _first_str(tool_input_dict(event), FILE_PATH_KEYS)


def extract_command(event: Event) -> str:
    return _first_str(tool_input_dict(event), COMMAND_KEYS)


def language_from_path(path: str) -> str | None:
    ext = os.path.splitext((path or '').lower())[1]
    return EXTENSION_TO_LANGUAGE.get(ext)


def count_text_lines(text: str) -> int:
    """写入内容的行数（末尾无换行时补 1，空串记 0）。"""
    if not text:
        return 0
    return text.count('\n') + (0 if text.endswith('\n') else 1)


def diff_line_counts(old: str, new: str) -> tuple[int, int]:
    """按行比较旧串/新串，返回 (added, removed)。"""
    old_lines = (old or '').splitlines(keepends=True)
    new_lines = (new or '').splitlines(keepends=True)
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'insert':
            added += j2 - j1
        elif tag == 'delete':
            removed += i2 - i1
        elif tag == 'replace':
            removed += i2 - i1
            added += j2 - j1
    return added, removed


PATCH_FILE_RE = re.compile(r'^\*\*\* (?:Add|Update|Delete) File: (.+)$')


def patch_effect(patch: str) -> tuple[list[str], int, int]:
    """解析 apply_patch 风格的补丁，返回 (涉及文件, added, removed)。"""
    files: list[str] = []
    added = removed = 0
    for line in (patch or '').splitlines():
        match = PATCH_FILE_RE.match(line)
        if match:
            files.append(match.group(1).strip())
            continue
        if line.startswith('***') or line.startswith('+++') or line.startswith('---'):
            continue
        if line.startswith('+'):
            added += 1
        elif line.startswith('-'):
            removed += 1
    return files, added, removed


def tool_effect(event: Event) -> tuple[list[str], int, int, bool]:
    """从一次工具调用读出产出效果。

    返回 (涉及文件, 新增行, 删除行, 是否写入型工具)。识别不了就返回空，不猜。
    """
    params = tool_input_dict(event)
    name = (event.tool_name or '').strip().lower()
    if name in PATCH_TOOL_NAMES:
        files, added, removed = patch_effect(_first_str(params, ('patch', 'diff')))
        return files, added, removed, True
    if name not in WRITE_TOOL_NAMES:
        return [], 0, 0, False

    path = extract_file_path(event)
    files = [path] if path else []
    old = _first_str(params, OLD_STRING_KEYS)
    new = _first_str(params, NEW_STRING_KEYS)
    if old or new:
        added, removed = diff_line_counts(old, new)
        return files, added, removed, True
    content = _first_str(params, CONTENT_KEYS)
    return files, count_text_lines(content), 0, True


def git_effect(event: Event) -> tuple[int, int]:
    """shell 类工具的命令里是否包含 git commit / push。"""
    if (event.tool_name or '').strip().lower() not in SHELL_TOOL_NAMES:
        return 0, 0
    command = extract_command(event).lower()
    commits = 1 if 'git commit' in command else 0
    pushes = 1 if 'git push' in command else 0
    return commits, pushes


def response_gaps(user_times: list[datetime],
                  assistant_times: list[datetime]) -> list[float]:
    """用户消息发出后、第一条助手回复之间的间隔（秒），过滤异常值。

    每条用户消息最多贡献一个间隔；连续多条用户消息以最后一条为起点。
    """
    from .constants import RESPONSE_TIME_MAX_SECONDS, RESPONSE_TIME_MIN_SECONDS
    marks = [(ts, 'user') for ts in user_times] + [(ts, 'assistant') for ts in assistant_times]
    marks.sort(key=lambda item: item[0])
    pending: datetime | None = None
    gaps: list[float] = []
    for ts, kind in marks:
        if kind == 'user':
            pending = ts
        elif pending is not None:
            gap = (ts - pending).total_seconds()
            if RESPONSE_TIME_MIN_SECONDS < gap < RESPONSE_TIME_MAX_SECONDS:
                gaps.append(gap)
            pending = None
    return gaps




_SLUG_PROJECT_RE = re.compile(r'^[A-Za-z]-[A-Za-z]')
_TIMESTAMP_DIR_RE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}-[0-9]{2}-[0-9]{2}$')


def is_synthetic_user_message(text: str) -> bool:
    """客户端注入的「伪用户消息」：时间采样说明、图片回显、审批策略通知。

    它们不是用户打的字，混进消息量会把 DeepSeek Harness 的占比放大好几倍。
    """
    from .constants import SYNTHETIC_USER_PREFIXES
    head = (text or '').lstrip()
    return any(head.startswith(prefix) for prefix in SYNTHETIC_USER_PREFIXES)


def canonical_project(project: str, cwd: str) -> str:
    """把各 Agent 各自命名的项目名收敛成同一种叫法。

    - WorkBuddy 用 cwd 的 slug（d-prj-win-xxx）当项目名，取 cwd 最后一段；
    - 时间戳目录（WorkBuddy / opencode 的临时工作区）合并成「父目录 临时会话」；
    - 空项目名统一成「未标注项目」。
    """
    name = (project or '').strip()
    path = (cwd or '').strip()
    parts = [part for part in re.split(r'[\\/]+', path) if part]
    if path and (not name or _SLUG_PROJECT_RE.match(name)) and parts:
        name = parts[-1]
        if _TIMESTAMP_DIR_RE.match(name) and len(parts) >= 2:
            return f'{parts[-2]} 临时会话'
        return name
    if _TIMESTAMP_DIR_RE.match(name):
        return f'{parts[-2]} 临时会话' if len(parts) >= 2 else '临时会话'
    if name in ('Default Project', 'Temp'):
        return '未标注项目'
    return name or '未标注项目'


def truncate(text: str, limit: int) -> str:
    text = (text or '').strip()
    return text if len(text) <= limit else text[:limit].rstrip() + '…'


_SANDBOX_BANNER_RE = re.compile(r'\s*File sandbox:\s*[a-z-]+\.?\s*$',
                                re.IGNORECASE)


def strip_error_banner(text: str) -> str:
    """去掉导出包附加在报错末尾的沙箱说明，否则每条报错都会被认成权限问题。"""
    return _SANDBOX_BANNER_RE.sub('', (text or '').strip())


def tool_error_category(text: str, tool_name: str = '') -> str:
    """把报错正文归到固定的错误类型；正文为空时按工具族给一个诚实的兜底。"""
    from .constants import (
        EMPTY_ERROR_TOOL_FAMILY,
        ERROR_CATEGORY_PATTERNS,
        ERROR_TEXT_SCAN_CHARS,
        TOOL_FAMILY_BY_NAME,
    )
    body = strip_error_banner(text)
    low = body[:ERROR_TEXT_SCAN_CHARS].lower()
    if not low:
        family = TOOL_FAMILY_BY_NAME.get((tool_name or '').lower())
        return EMPTY_ERROR_TOOL_FAMILY.get(family or '', 'unclassified')
    for category, needles in ERROR_CATEGORY_PATTERNS:
        if any(needle in low for needle in needles):
            return category
    return 'other'
