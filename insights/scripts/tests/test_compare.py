"""环比：存档命名、按周期找上期、跨版本/跨来源不比较、差值方向。"""
from __future__ import annotations

import json

from insights_core import compare


def make_stats(*, period='week', since='2026-11-02', until='2026-11-05',
               kind='agenttrail', schema=2, messages=100, errors=5):
    return {
        'schema_version': schema,
        'source': {'kind': kind},
        'window': {'since': since, 'until': until, 'period': period, 'days': 4,
                   'description': f'{since} 至 {until}'},
        'totals': {'substantive_sessions': 10, 'user_messages': messages,
                   'tool_calls': 500, 'days_active': 4, 'lines_added': 300,
                   'tool_errors': errors, 'median_response_seconds': 60},
    }


def write_history(directory, stats, name=None):
    path = directory / (name or compare.history_filename(stats))
    path.write_text(json.dumps(stats, ensure_ascii=False), encoding='utf-8')
    return path


def test_history_filename_uses_period_and_window(tmp_path):
    stats = make_stats()
    assert compare.history_filename(stats) == 'stats-week-20261102-20261105.json'


def test_save_history_skips_non_periodic_window(tmp_path):
    stats = make_stats(period=None)
    assert compare.save_history(tmp_path, stats) is None
    stats = make_stats()
    saved = compare.save_history(tmp_path, stats)
    assert saved is not None and saved.is_file()


def test_find_prev_requires_same_period(tmp_path):
    write_history(tmp_path, make_stats(period='month', since='2026-10-01', until='2026-10-31'))
    current = make_stats(since='2026-11-02', until='2026-11-05')
    assert compare.find_prev_stats(tmp_path, current) is None


def test_find_prev_requires_earlier_window(tmp_path):
    write_history(tmp_path, make_stats(since='2026-11-02', until='2026-11-05'))
    current = make_stats(since='2026-11-02', until='2026-11-05')
    assert compare.find_prev_stats(tmp_path, current) is None


def test_find_prev_rejects_other_schema_and_kind(tmp_path):
    write_history(tmp_path, make_stats(since='2026-10-26', until='2026-11-01', schema=1))
    write_history(tmp_path, make_stats(since='2026-10-19', until='2026-10-25', kind='zcode'))
    current = make_stats(since='2026-11-02', until='2026-11-05')
    assert compare.find_prev_stats(tmp_path, current) is None


def test_find_prev_picks_latest_earlier(tmp_path):
    older = write_history(tmp_path, make_stats(since='2026-10-19', until='2026-10-25'))
    latest = write_history(tmp_path, make_stats(since='2026-10-26', until='2026-11-01'))
    current = make_stats(since='2026-11-02', until='2026-11-05')
    assert compare.find_prev_stats(tmp_path, current) == latest
    assert older.exists()


def test_compute_without_previous_is_unavailable():
    result = compare.compute(make_stats(), None)
    assert result.available is False
    assert '首次生成' in result.notes[0]


def test_compute_non_periodic_says_no_comparison():
    result = compare.compute(make_stats(period=None), None)
    assert result.available is False
    assert '不做自动环比' in result.notes[0]


def test_compute_rows_and_direction():
    prev = make_stats(since='2026-10-26', until='2026-11-01', messages=80, errors=8)
    current = make_stats(messages=100, errors=5)
    result = compare.compute(current, prev, tmp_path_path())
    assert result.available is True
    rows = {row['label']: row for row in result.rows}
    assert rows['用户消息']['delta'] == 20
    assert rows['用户消息']['percent'] == 25.0
    assert rows['工具报错']['good'] is True      # 报错变少是好事
    assert rows['工具报错']['delta'] == -3


def tmp_path_path():
    from pathlib import Path
    return Path('history/stats-week-20261026-20261101.json')
