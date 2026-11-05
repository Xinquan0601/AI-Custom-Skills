"""报告窗口：把用户说法/显式参数翻译成数据源内的确定时间区间。

窗口优先对齐导出文件（manifest 的 from/to），用户指定窗口时取其与导出窗口的交集：
- 完全落在导出窗口内 → 直接用；
- 部分越界 → 裁剪到导出窗口并告警；
- 完全无交集 → 报错，不生成空报告。

时区：数据源一律 UTC，这里统一换算成报告时区（默认 UTC+8）的自然日。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime


class WindowError(ValueError):
    """窗口无法与数据源对齐（无交集 / 参数非法）。"""


@dataclass(frozen=True)
class Window:
    """解析后的统计窗口，边界是本地自然日。"""
    since: date
    until: date
    period: str | None      # week / month / None
    description: str
    source: str             # bundle / requested / requested-clamped / all
    clamped: bool = False

    @property
    def start_ms(self) -> int:
        return int(datetime.combine(self.since, dtime.min).timestamp() * 1000)

    @property
    def end_ms(self) -> int:
        return int(datetime.combine(self.until, dtime.max).timestamp() * 1000)

    @property
    def days(self) -> int:
        return (self.until - self.since).days + 1

    def contains_ms(self, epoch_ms: int) -> bool:
        return self.start_ms <= epoch_ms <= self.end_ms


def local_today(offset_hours: int) -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=offset_hours)).date()


def utc_range_to_local_dates(start_utc: datetime, end_utc: datetime,
                             offset_hours: int) -> tuple[date, date]:
    local_start = (start_utc + timedelta(hours=offset_hours)).date()
    local_end = (end_utc + timedelta(hours=offset_hours)).date()
    return local_start, local_end


def _parse_date(text: str) -> date:
    try:
        return datetime.strptime(text.strip(), '%Y-%m-%d').date()
    except ValueError:
        raise WindowError(f'日期格式应为 YYYY-MM-DD，收到 {text!r}') from None


def _fmt_range(start: date, end: date) -> str:
    if start == end:
        return start.isoformat()
    return f'{start.isoformat()} 至 {end.isoformat()}'


def compute_window(*,
                   bundle_since: date,
                   bundle_until: date,
                   since: str | None = None,
                   until: str | None = None,
                   days: int | None = None,
                   week: str | None = None,
                   month: str | None = None,
                   all_: bool = False,
                   today: date | None = None) -> Window:
    """计算最终统计窗口。

    bundle_since / bundle_until：导出文件覆盖的本地自然日，作为硬边界。
    参数优先级：all > week/month > since/until > days > 默认（整个导出窗口）。
    """
    if bundle_since > bundle_until:
        raise WindowError(f'导出窗口非法：{bundle_since} 晚于 {bundle_until}')

    today = today or local_today(8)
    base_desc = f'{_fmt_range(bundle_since, bundle_until)}'

    if all_ or (since is None and until is None and days is None
                and not week and not month):
        return Window(since=bundle_since, until=bundle_until, period=None,
                      description=f'{base_desc}（导出窗口）', source='bundle')

    period: str | None = None
    if week:
        monday = today - timedelta(days=today.weekday())
        if week == 'this':
            start, end = monday, today
            period = 'week'
        else:
            start = monday - timedelta(days=7)
            end = start + timedelta(days=6)
            period = 'week'
    elif month:
        start = today.replace(day=1)
        end = today
        period = 'month'
    elif since or until:
        if since and until:
            start, end = _parse_date(since), _parse_date(until)
        elif since:
            start, end = _parse_date(since), today
        else:
            end = _parse_date(until)
            start = end - timedelta(days=13)   # 只给结束日：向前取 14 天
        if start > end:
            raise WindowError(f'起始日期 {start} 晚于结束日期 {end}')
    else:
        n = days if days is not None else 15
        if n <= 0:
            raise WindowError('--days 必须是正整数')
        start, end = today - timedelta(days=n - 1), today

    requested_desc = _fmt_range(start, end)
    clipped_start = max(start, bundle_since)
    clipped_end = min(end, bundle_until)

    if clipped_start > clipped_end:
        raise WindowError(
            f'请求窗口 {requested_desc} 与导出数据窗口 {base_desc} 没有交集；'
            f'本次导出只覆盖 {base_desc}'
        )

    clamped = (clipped_start, clipped_end) != (start, end)
    if clamped:
        description = f'{_fmt_range(clipped_start, clipped_end)}（请求 {requested_desc}，已裁剪到导出范围）'
    else:
        description = _fmt_range(clipped_start, clipped_end)

    return Window(since=clipped_start, until=clipped_end, period=period,
                  description=description,
                  source='requested-clamped' if clamped else 'requested',
                  clamped=clamped)


# ============================================================================
# 自然语言兜底解析（LLM 才是主通道，这里只兜底常见说法）
# ============================================================================

_WEEK_WORDS = ('本周', '这周', '这一周', '这个星期')
_LAST_WEEK_WORDS = ('上周', '上一周', '上个星期')
_MONTH_WORDS = ('本月', '这个月', '这月')
_ALL_WORDS = ('全部', '所有', '不限', 'all')
_DAYS_RE = re.compile(r'(?:最近|近|过去)\s*(\d{1,2})\s*(?:天|日)')
_DAYS_ONLY_RE = re.compile(r'^\s*(\d{1,2})\s*天\s*$')
_RANGE_RE = re.compile(
    r'(\d{4}-\d{1,2}-\d{1,2})\s*(?:至|到|~|-|—)\s*(\d{4}-\d{1,2}-\d{1,2})')


def parse_natural_window(text: str | None) -> dict:
    """从用户原话里兜底识别窗口参数；识别不出返回空 dict。"""
    if not text:
        return {}
    raw = str(text).strip()
    low = raw.lower()

    if any(word in raw for word in _ALL_WORDS) or low == 'all':
        return {'all_': True}

    match = _DAYS_RE.search(raw) or _DAYS_ONLY_RE.match(raw)
    if match:
        return {'days': int(match.group(1))}

    if any(word in raw for word in _WEEK_WORDS):
        return {'week': 'this'}
    if any(word in raw for word in _LAST_WEEK_WORDS):
        return {'week': 'last'}
    if any(word in raw for word in _MONTH_WORDS):
        return {'month': 'this'}

    match = _RANGE_RE.search(raw)
    if match:
        return {'since': match.group(1), 'until': match.group(2)}

    return {}
