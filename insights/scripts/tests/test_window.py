"""窗口解析：默认对齐导出包、显式参数收窄、越界裁剪、无交集报错。"""
from __future__ import annotations

from datetime import date

import pytest
from insights_core.window import WindowError, compute_window, parse_natural_window

BUNDLE = dict(bundle_since=date(2026, 10, 30), bundle_until=date(2026, 11, 5))
TODAY = date(2026, 11, 5)          # 周四


def win(**kwargs):
    return compute_window(today=TODAY, **BUNDLE, **kwargs)


def test_default_follows_bundle_window():
    w = win()
    assert (w.since, w.until) == (date(2026, 10, 30), date(2026, 11, 5))
    assert w.source == 'bundle'
    assert w.period is None
    assert w.clamped is False
    assert '导出窗口' in w.description


def test_all_equals_bundle_window():
    assert win(all_=True) == win()


def test_explicit_range_inside_bundle():
    w = win(since='2026-11-01', until='2026-11-02')
    assert (w.since, w.until) == (date(2026, 11, 1), date(2026, 11, 2))
    assert w.source == 'requested'
    assert w.clamped is False


def test_until_only_looks_back_two_weeks():
    w = win(until='2026-11-02')
    assert (w.since, w.until) == (date(2026, 10, 30), date(2026, 11, 2))
    assert w.clamped is True   # 10-20 被裁剪到导出起点


def test_range_before_bundle_is_clamped():
    w = win(since='2026-10-01', until='2026-10-31')
    assert (w.since, w.until) == (date(2026, 10, 30), date(2026, 10, 31))
    assert w.source == 'requested-clamped'
    assert '已裁剪' in w.description


def test_range_outside_bundle_raises():
    with pytest.raises(WindowError, match='没有交集'):
        win(since='2026-12-01', until='2026-12-05')


def test_reversed_range_raises():
    with pytest.raises(WindowError, match='晚于'):
        win(since='2026-11-04', until='2026-11-01')


def test_bad_date_raises():
    with pytest.raises(WindowError):
        win(since='2026-13-01')


def test_week_this_clips_to_today():
    w = win(week='this')
    assert (w.since, w.until) == (date(2026, 11, 2), date(2026, 11, 5))
    assert w.period == 'week'


def test_week_last_clipped_by_bundle_start():
    w = win(week='last')
    assert (w.since, w.until) == (date(2026, 10, 30), date(2026, 11, 1))
    assert w.period == 'week'
    assert w.clamped is True


def test_month_this():
    w = win(month='this')
    assert (w.since, w.until) == (date(2026, 11, 1), date(2026, 11, 5))
    assert w.period == 'month'


def test_days():
    w = win(days=3)
    assert (w.since, w.until) == (date(2026, 11, 3), date(2026, 11, 5))


@pytest.mark.parametrize('days', [0, -1])
def test_days_must_be_positive(days):
    with pytest.raises(WindowError, match='正整数'):
        win(days=days)


def test_bundle_window_must_be_sane():
    with pytest.raises(WindowError, match='导出窗口非法'):
        compute_window(bundle_since=date(2026, 11, 5), bundle_until=date(2026, 11, 1),
                       today=TODAY)


@pytest.mark.parametrize('text', ['本周', '这周', '这一周'])
def test_natural_this_week(text):
    assert parse_natural_window(text) == {'week': 'this'}


@pytest.mark.parametrize('text', ['上周', '上一周'])
def test_natural_last_week(text):
    assert parse_natural_window(text) == {'week': 'last'}


def test_natural_full_range():
    assert parse_natural_window('2026-10-30 至 2026-11-02') == {
        'since': '2026-10-30', 'until': '2026-11-02'}


def test_natural_all():
    assert parse_natural_window('全部') == {'all_': True}


def test_natural_unknown_returns_empty():
    assert parse_natural_window('最近状态怎么样') == {}
