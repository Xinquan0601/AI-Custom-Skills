"""环比：history 存档的写入与「上期」定位。

规则（ADR-0002）：
- 只有周报/月报参与自动环比，按 period 对齐（周找上一自然周，月找上一自然月）；
- 只和同 schema 版本、同数据源类型的存档比较，跨版本/跨来源一律不比较；
- 找不到上期时如实说「首次生成」，不报错。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .constants import SCHEMA_VERSION

HISTORY_RE = re.compile(r'^stats-(week|month)-(\d{8})-(\d{8})\.json$')

# (字段路径, 展示名, 好的方向)
COMPARE_METRICS = [
    (('totals', 'substantive_sessions'), '实质会话', None),
    (('totals', 'user_messages'), '用户消息', None),
    (('totals', 'tool_calls'), '工具调用', None),
    (('totals', 'days_active'), '活跃天数', None),
    (('totals', 'lines_added'), '新增代码行', None),
    (('totals', 'tool_errors'), '工具报错', 'down'),
    (('totals', 'median_response_seconds'), '响应中位数(秒)', 'down'),
]


@dataclass
class Comparison:
    available: bool = False
    period: str | None = None
    prev_path: str = ''
    prev_window: str = ''
    rows: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def history_filename(stats: dict) -> str:
    window = stats['window']
    period = window.get('period')
    start = window['since'].replace('-', '')
    end = window['until'].replace('-', '')
    return f'stats-{period}-{start}-{end}.json'


def save_history(history_dir: str | Path, stats: dict) -> Path | None:
    """周期窗口（周/月）才存档，供下次环比。"""
    period = (stats.get('window') or {}).get('period')
    if not period:
        return None
    directory = Path(history_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / history_filename(stats)
    target.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def find_prev_stats(history_dir: str | Path, stats: dict) -> Path | None:
    """按周期类型找上一期存档：同 schema、同数据源类型、窗口结束早于本期开始。"""
    window = stats.get('window') or {}
    period = window.get('period')
    if not period:
        return None
    directory = Path(history_dir)
    if not directory.is_dir():
        return None

    start = date.fromisoformat(window['since'])
    kind = (stats.get('source') or {}).get('kind')
    candidates: list[tuple[date, Path]] = []
    for path in directory.iterdir():
        match = HISTORY_RE.match(path.name)
        if not match or match.group(1) != period:
            continue
        until = _parse_compact_date(match.group(3))
        if not until or until >= start:
            continue
        prev = _read_json(path)
        if not prev:
            continue
        if prev.get('schema_version') != SCHEMA_VERSION:
            continue
        if (prev.get('source') or {}).get('kind') != kind:
            continue
        candidates.append((until, path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _parse_compact_date(text: str) -> date | None:
    try:
        return datetime.strptime(text, '%Y%m%d').date()
    except ValueError:
        return None


def _dig(data: dict, path: tuple[str, ...]):
    value = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def from_dict(data: dict | None, text: dict | None = None) -> Comparison | None:
    """把 stats.json 里存的 comparison 还原成 Comparison（渲染时用）。"""
    if not isinstance(data, dict):
        return None
    return Comparison(
        available=bool(data.get('available')),
        period=data.get('period'),
        prev_path=data.get('prev_path') or '',
        prev_window=data.get('prev_window') or '',
        rows=list(data.get('rows') or []),
        notes=list(data.get('notes') or []),
    )


def compute(stats: dict, prev_stats: dict | None, prev_path: Path | None = None) -> Comparison:
    """生成本期 vs 上期的差值表。"""
    period = (stats.get('window') or {}).get('period')
    if not prev_stats:
        return Comparison(
            available=False, period=period,
            notes=['首次生成：history 里没有可比较的上期存档']
            if period else ['当前窗口不是周/月周期，不做自动环比'])

    prev_window = prev_stats.get('window') or {}
    rows = []
    for path, label, better in COMPARE_METRICS:
        current = _dig(stats, path)
        previous = _dig(prev_stats, path)
        if current is None or previous is None:
            continue
        delta = current - previous
        percent = round(delta / previous * 100, 1) if previous else None
        rows.append({
            'label': label, 'current': current, 'previous': previous,
            'delta': round(delta, 1), 'percent': percent,
            'better': better,
            'good': None if better is None or delta == 0 else (
                (delta < 0) if better == 'down' else (delta > 0)),
        })

    current_window = stats.get('window') or {}
    notes = []
    current_days = current_window.get('days')
    prev_days = prev_window.get('days')
    if current_days and prev_days and current_days != prev_days:
        notes.append(
            f'本期 {current_days} 天、上期 {prev_days} 天，量级差异可能来自窗口长度而非使用强度')
    return Comparison(
        available=True, period=period,
        prev_path=str(prev_path or ''), prev_window=prev_window.get('description', ''),
        rows=rows, notes=notes)
