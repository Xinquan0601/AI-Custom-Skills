"""纯展示图元：输入数字，输出 HTML 片段。不含任何业务判断。

所有标签都经 esc() 转义；空数据统一渲染为空态提示，绝不输出空白块。
"""
from __future__ import annotations

import html
from collections.abc import Iterable

EMPTY = '<p class="empty">本窗口内无可用数据</p>'


def esc(value) -> str:
    return html.escape(str(value if value is not None else ''))


def bar_list(items: Iterable[dict], *, color: str = '#6366f1',
             max_value: float | None = None, empty: str = EMPTY,
             value_suffix: str = '') -> str:
    """横向条形图：items 里每项是 {label, value, color?, note?}。"""
    rows = [item for item in items if item.get('value')]
    if not rows:
        return empty
    peak = max_value or max(item['value'] for item in rows) or 1
    out = []
    for item in rows:
        pct = max(2.0, item['value'] / peak * 100)
        fill = item.get('color') or color
        note = f'<span class="bar-note">{esc(item["note"])}</span>' if item.get('note') else ''
        out.append(
            f'<div class="bar-row">'
            f'<div class="bar-label" title="{esc(item["label"])}">{esc(item["label"])}{note}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{fill}"></div></div>'
            f'<div class="bar-value">{esc(item["value"])}{esc(value_suffix)}</div>'
            f'</div>')
    return '\n'.join(out)


def stacked_shares(items: Iterable[dict]) -> str:
    """单行占比条：items 里每项是 {label, value, color}。"""
    rows = [item for item in items if item.get('value')]
    total = sum(item['value'] for item in rows)
    if not rows or not total:
        return EMPTY
    segments = []
    legend = []
    for item in rows:
        pct = item['value'] / total * 100
        segments.append(
            f'<span class="stack-seg" style="width:{pct:.2f}%;background:{item.get("color", "#94a3b8")}" '
            f'title="{esc(item["label"])}：{esc(item["value"])}"></span>')
        legend.append(
            f'<li><i style="background:{item.get("color", "#94a3b8")}"></i>'
            f'{esc(item["label"])}<b>{esc(item["value"])}</b></li>')
    return (f'<div class="stack">{"".join(segments)}</div>'
            f'<ul class="legend">{"".join(legend)}</ul>')


def column_chart(items: Iterable[dict], *, color: str = '#6366f1',
                 empty: str = EMPTY) -> str:
    """纵向柱状图：items 里每项是 {label, value, title?}。"""
    rows = list(items)
    if not rows or not any(item.get('value') for item in rows):
        return empty
    peak = max(item['value'] for item in rows) or 1
    bars = []
    for item in rows:
        height = max(2.0, item['value'] / peak * 100) if item['value'] else 0.0
        bars.append(
            f'<div class="col" title="{esc(item.get("title") or item["label"])}：{esc(item["value"])}">'
            f'<div class="col-bar" style="height:{height:.1f}%;background:{color}"></div>'
            f'<div class="col-label">{esc(item["label"])}</div></div>')
    return f'<div class="columns">{"".join(bars)}</div>'


def hour_grid(hours: list[int], *, empty: str = EMPTY) -> str:
    """24 小时热力格：0-6 凌晨、6-12 上午、12-18 下午、18-24 晚上。"""
    if not hours or not any(hours):
        return empty
    peak = max(hours) or 1
    cells = []
    for hour, value in enumerate(hours):
        intensity = value / peak if peak else 0
        opacity = 0.12 + 0.88 * intensity
        cells.append(
            f'<div class="hour-cell" title="{hour}:00 — {value} 条消息">'
            f'<span style="opacity:{opacity:.2f}">{hour:02d}</span>'
            f'<em>{value or ""}</em></div>')
    return ('<div class="hour-grid">' + ''.join(cells) + '</div>'
            '<div class="hour-axis"><span>0-6 凌晨</span><span>6-12 上午</span>'
            '<span>12-18 下午</span><span>18-24 晚上</span></div>')


def histogram(buckets: list[dict], *, color: str = '#6366f1',
              empty: str = EMPTY) -> str:
    """把已经分好桶的 [{label, count}] 画成条形图。"""
    items = [{'label': bucket['label'], 'value': bucket['count']} for bucket in buckets]
    return bar_list(items, color=color, empty=empty)


def chips(items: Iterable[tuple[str, str]]) -> str:
    return ''.join(
        f'<span class="chip"><b>{esc(value)}</b>{esc(label)}</span>'
        for label, value in items)
