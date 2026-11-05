"""AgentTrail 导出包适配器（zip 或解压目录）。

契约见 docs/data-source.md。要点：
- sessions.csv 是会话级权威聚合，events.csv 是事件明细；
- 事件可能被导出筛选截断，按 manifest.counts 与工具调用计数核对完整度并告警；
- 全部时间字段是 UTC，解析失败的行跳过并计数，绝不静默丢弃。
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from ..model import Event, SessionMeta, canonical_project, is_synthetic_user_message, parse_utc
from .base import Bundle, SourceError

csv.field_size_limit(1 << 30)

SESSIONS_CSV = 'sessions.csv'
EVENTS_CSV = 'events.csv'
MANIFEST_JSON = 'manifest.json'

REQUIRED_SESSION_FIELDS = {'agent_key', 'external_id', 'started_at'}
REQUIRED_EVENT_FIELDS = {'agent', 'session_id', 'event_type', 'timestamp'}


class _Package:
    """统一读取 zip / 目录里的成员文件。"""

    def __init__(self, path: Path):
        self.path = path
        self._zip: zipfile.ZipFile | None = None
        if path.is_dir():
            self._root = path
            missing = [n for n in (SESSIONS_CSV, EVENTS_CSV, MANIFEST_JSON)
                       if not (path / n).is_file()]
            if missing:
                raise SourceError(f'导出包缺少文件：{", ".join(missing)}（{path}）')
        else:
            self._root = None
            try:
                self._zip = zipfile.ZipFile(path)
            except zipfile.BadZipFile as exc:
                raise SourceError(f'无法读取 zip：{path}（{exc}）') from exc
            names = set(self._zip.namelist())
            missing = [n for n in (SESSIONS_CSV, EVENTS_CSV, MANIFEST_JSON) if n not in names]
            if missing:
                raise SourceError(f'导出包缺少文件：{", ".join(missing)}（{path}）')

    def read_text(self, name: str) -> str:
        if self._zip is not None:
            with self._zip.open(name) as handle:
                return handle.read().decode('utf-8-sig')
        return (self._root / name).read_text(encoding='utf-8-sig')

    @contextmanager
    def open_csv(self, name: str) -> Iterator[csv.DictReader]:
        """流式读取 CSV：导出包可能有几十 MB，不在内存里留第二份行字典。"""
        if self._zip is not None:
            with self._zip.open(name) as raw:
                with io.TextIOWrapper(raw, encoding='utf-8-sig', newline='') as text:
                    yield csv.DictReader(text)
        else:
            with (self._root / name).open('r', encoding='utf-8-sig', newline='') as text:
                yield csv.DictReader(text)

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()


def _to_int(value: str | None) -> int:
    try:
        return int(float(str(value).strip() or 0))
    except (TypeError, ValueError):
        return 0


def _load_manifest(package: _Package) -> dict:
    try:
        return json.loads(package.read_text(MANIFEST_JSON))
    except json.JSONDecodeError as exc:
        raise SourceError(f'manifest.json 不是合法 JSON：{exc}') from exc


def _check_fields(fields: Iterable[str] | None, required: set[str], name: str) -> None:
    if fields is None:
        raise SourceError(f'{name} 没有表头')
    missing = required - set(fields)
    if missing:
        raise SourceError(f'{name} 缺字段：{", ".join(sorted(missing))}')


def _parse_tool_input(raw: str) -> tuple[dict, str]:
    text = (raw or '').strip()
    if not text:
        return {}, ''
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}, text
    if isinstance(parsed, dict):
        return parsed, text
    return {'value': parsed}, text


def _session_from_row(row: dict) -> SessionMeta | None:
    started = parse_utc(row.get('started_at'))
    if not row.get('external_id') or not started:
        return None
    ended = parse_utc(row.get('ended_at'))
    return SessionMeta(
        agent=(row.get('agent_key') or '').strip(),
        session_id=(row.get('external_id') or '').strip(),
        title=(row.get('title') or '').strip(),
        project=canonical_project(row.get('project') or '', row.get('cwd') or ''),
        model=(row.get('model') or '').strip(),
        cwd=(row.get('cwd') or '').strip(),
        started_at=started,
        ended_at=ended,
        message_count=_to_int(row.get('message_count')),
        user_message_count=_to_int(row.get('user_message_count')),
        assistant_message_count=_to_int(row.get('assistant_message_count')),
        tool_call_count=_to_int(row.get('tool_call_count')),
        tool_result_count=_to_int(row.get('tool_result_count')),
        event_count=_to_int(row.get('event_count')),
        tokens_input=_to_int(row.get('tokens_input')),
        tokens_output=_to_int(row.get('tokens_output')),
        source_path=(row.get('source_path') or '').strip(),
    )


def _event_from_row(row: dict) -> Event | None:
    ts = parse_utc(row.get('timestamp'))
    if not ts or not row.get('session_id') or not row.get('event_type'):
        return None
    tool_input, raw_input = _parse_tool_input(row.get('tool_input_json'))
    event_type = (row.get('event_type') or '').strip()
    content = row.get('content') or ''
    return Event(
        event_id=str(row.get('event_id') or '').strip(),
        agent=(row.get('agent') or '').strip(),
        session_id=(row.get('session_id') or '').strip(),
        type=event_type,
        ts=ts,
        content=content,
        tool_name=(row.get('tool_name') or '').strip(),
        tool_call_id=(row.get('tool_call_id') or '').strip(),
        tool_status=(row.get('tool_status') or '').strip(),
        tool_input=tool_input,
        tool_input_raw=raw_input,
        model=(row.get('model') or '').strip(),
        tokens_input=_to_int(row.get('tokens_input')),
        tokens_output=_to_int(row.get('tokens_output')),
        synthetic=event_type == 'user_message' and is_synthetic_user_message(content),
    )


def _completeness_warnings(manifest: dict, sessions: list[SessionMeta],
                           events: list[Event],
                           per_session_calls: dict[str, int]) -> list[str]:
    warnings: list[str] = []
    counts = (manifest or {}).get('counts') or {}
    declared_events = _to_int(counts.get('events'))
    declared_sessions = _to_int(counts.get('sessions'))
    if declared_events and declared_events != len(events):
        warnings.append(
            f'manifest 声明 {declared_events} 条事件，实际读到 {len(events)} 条')
    if declared_sessions and declared_sessions != len(sessions):
        warnings.append(
            f'manifest 声明 {declared_sessions} 个会话，实际读到 {len(sessions)} 个')

    totals = _event_totals(events)
    declared = _declared_totals(sessions)
    partial = sum(1 for meta in sessions
                  if meta.tool_call_count > per_session_calls.get(meta.session_id, 0))
    if partial:
        warnings.append(
            f'{partial} 个会话在导出窗口开始前就已开始：sessions.csv 的会话级合计比事件表多 '
            f'{declared["tool_calls"] - totals["tool_calls"]} 次工具调用、'
            f'{declared["user_messages"] - totals["user_messages"]} 条用户消息；'
            f'本报告的消息量、工具量、代码与报错均按事件表统计')
    return warnings


def _event_totals(events: list[Event]) -> dict:
    counts = {'tool_calls': 0, 'user_messages': 0}
    for event in events:
        if event.type == 'tool_call':
            counts['tool_calls'] += 1
        elif event.type == 'user_message':
            counts['user_messages'] += 1
    return counts


def _declared_totals(sessions: list[SessionMeta]) -> dict:
    return {
        'tool_calls': sum(s.tool_call_count for s in sessions),
        'user_messages': sum(s.user_message_count for s in sessions),
    }


def load(path: str | Path) -> Bundle:
    """读取导出包并转换成 Bundle。"""
    target = Path(path).expanduser()
    package = _Package(target)
    try:
        manifest = _load_manifest(package)

        sessions: list[SessionMeta] = []
        skipped_sessions = 0
        with package.open_csv(SESSIONS_CSV) as reader:
            _check_fields(reader.fieldnames, REQUIRED_SESSION_FIELDS, SESSIONS_CSV)
            for row in reader:
                meta = _session_from_row(row)
                if meta is None:
                    skipped_sessions += 1
                else:
                    sessions.append(meta)

        events: list[Event] = []
        seen_fingerprints: set[str] = set()
        skipped_events = 0
        duplicates = 0
        with package.open_csv(EVENTS_CSV) as reader:
            _check_fields(reader.fieldnames, REQUIRED_EVENT_FIELDS, EVENTS_CSV)
            for row in reader:
                fingerprint = (row.get('fingerprint') or '').strip()
                if fingerprint and fingerprint in seen_fingerprints:
                    duplicates += 1
                    continue
                event = _event_from_row(row)
                if event is None:
                    skipped_events += 1
                    continue
                if fingerprint:
                    seen_fingerprints.add(fingerprint)
                events.append(event)
    finally:
        package.close()

    if not events:
        raise SourceError(f'导出包里没有任何事件：{target}')
    if not sessions:
        raise SourceError(f'导出包里没有任何会话：{target}')

    per_session_calls: dict[str, int] = {}
    for event in events:
        if event.type == 'tool_call':
            per_session_calls[event.session_id] = per_session_calls.get(event.session_id, 0) + 1
    warnings = _completeness_warnings(manifest, sessions, events, per_session_calls)
    if skipped_events:
        warnings.append(f'跳过 {skipped_events} 条时间戳/会话 ID 缺失的事件')
    if skipped_sessions:
        warnings.append(f'跳过 {skipped_sessions} 条缺少会话 ID 或开始时间的会话')
    if duplicates:
        warnings.append(f'按 fingerprint 去重 {duplicates} 条重复事件')
    synthetic = sum(1 for event in events if event.synthetic)
    if synthetic:
        warnings.append(
            f'另有 {synthetic} 条客户端注入的伪用户消息（时间采样说明、图片回显、'
            f'审批策略通知），不计入消息量')

    filters = (manifest or {}).get('filters') or {}
    return Bundle(
        path=target,
        kind='agenttrail',
        export_version=str((manifest or {}).get('export_version') or ''),
        generated_at=str((manifest or {}).get('generated_at') or ''),
        window_start_utc=str(filters.get('from') or ''),
        window_end_utc=str(filters.get('to') or ''),
        sessions=sessions,
        events=events,
        warnings=warnings,
        counts={
            'sessions': len(sessions),
            'events': len(events),
            'declared_sessions': _to_int((manifest.get('counts') or {}).get('sessions')),
            'declared_events': _to_int((manifest.get('counts') or {}).get('events')),
            'tool_calls': sum(1 for e in events if e.type == 'tool_call'),
        },
    )
