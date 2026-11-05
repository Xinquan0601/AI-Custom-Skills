"""insights 技能命令行：now / collect / facet / render / validate。

职责边界：
- collect 只产出 stats.json（数据事实 + 口径 + 数据质量）；
- render 只吃 stats.json + narratives.json，不做任何数据再计算；
- validate 给 LLM 一个可自检的入口，避免带着坏叙事出报告。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from insights_core import compare, constants, facets, narrative, render
from insights_core.model import parse_utc
from insights_core.sources import SourceError, load_bundle
from insights_core.stats import aggregate, check_stats
from insights_core.window import (
    WindowError,
    compute_window,
    local_today,
    parse_natural_window,
    utc_range_to_local_dates,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY = REPO_ROOT / 'history'
DEFAULT_STATS = Path('insights_stats.json')
DEFAULT_SOURCE_HINT = 'insights/data/agenttrail-*.zip'


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass


def _add_tz_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--utc-offset', type=int, metavar='H',
                        help='展示时区偏移（小时，默认 8，也可用环境变量 INSIGHTS_UTC_OFFSET）')


def _apply_utc_offset(args) -> None:
    offset = getattr(args, 'utc_offset', None)
    if offset is None:
        return
    if not -12 <= offset <= 14:
        raise SystemExit('[error] --utc-offset 必须在 -12 到 14 之间')
    os.environ[constants.UTC_OFFSET_ENV] = str(offset)


def _add_window_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group('窗口（默认取导出包的完整窗口）')
    group.add_argument('--since', help='起始日 YYYY-MM-DD（含）')
    group.add_argument('--until', help='结束日 YYYY-MM-DD（含）；只给这个时向前取 14 天')
    group.add_argument('--days', type=int, help='最近 N 天（含今天）')
    group.add_argument('--week', choices=['this', 'last'], help='本周 / 上周')
    group.add_argument('--month', choices=['this'], help='本月')
    group.add_argument('--all', action='store_true', help='导出包覆盖的全部日期')
    group.add_argument('--natural', help='用户原话，识别不出窗口时兜底解析')


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='insights_report.py', description='从 AgentTrail 导出包生成 AI 使用洞察报告')
    sub = parser.add_subparsers(dest='command', required=True)

    now = sub.add_parser('now', help='打印时间锚点与导出窗口，供判断「本周/最近」用')
    now.add_argument('--source', help='导出包路径（.zip 或解压目录），用于读出导出窗口')
    _add_tz_arg(now)

    collect = sub.add_parser('collect', help='读取导出包，产出 stats.json')
    collect.add_argument('--source', required=True, help=f'导出包路径，例如 {DEFAULT_SOURCE_HINT}')
    collect.add_argument('--out', default=str(DEFAULT_STATS), help='stats.json 输出路径')
    collect.add_argument('--history-dir', default=str(DEFAULT_HISTORY),
                         help='环比存档目录（周报/月报才会写）')
    _add_window_args(collect)
    _add_tz_arg(collect)

    facet = sub.add_parser('facet', help='语义层：生成会话提取任务 / 合并提取结果')
    facet_sub = facet.add_subparsers(dest='facet_command', required=True)
    facet_plan = facet_sub.add_parser('plan', help='为实质会话生成 digest 与提取任务')
    facet_plan.add_argument('--source', required=True, help=f'导出包路径，例如 {DEFAULT_SOURCE_HINT}')
    facet_plan.add_argument('--out', default='facets-tasks.json', help='tasks.json 输出路径')
    facet_plan.add_argument('--limit', type=int, default=facets.MAX_TASKS,
                            help=f'最多提取多少个会话（默认 {facets.MAX_TASKS}，按最近活跃排序）')
    facet_plan.add_argument('--session', action='append', default=[],
                            help='只提取指定会话 id（可重复），用于抽查')
    _add_window_args(facet_plan)
    _add_tz_arg(facet_plan)

    facet_merge = facet_sub.add_parser('merge', help='校验提取结果并聚合为 facets.json')
    facet_merge.add_argument('--tasks', required=True)
    facet_merge.add_argument('--results', required=True)
    facet_merge.add_argument('--out', default='facets.json')
    facet_merge.add_argument('--summary', help='聚合摘要另存路径（可选）')

    render_cmd = sub.add_parser('render', help='用 stats.json + narratives.json 生成 HTML')
    render_cmd.add_argument('--stats', required=True)
    render_cmd.add_argument('--narratives', required=True)
    render_cmd.add_argument('--facets', help='可选：facets.json，渲染语义层章节')
    render_cmd.add_argument('--out', required=True, help='报告输出目录')
    render_cmd.add_argument('--prefix', default='AI使用洞察报告', help='文件名前缀')

    validate = sub.add_parser('validate', help='检查 stats / narratives 是否符合契约')
    validate.add_argument('--stats')
    validate.add_argument('--narratives')
    validate.add_argument('--facets', help='可选：facets.json，用于核对叙事里的数字来源')
    return parser


# ---------------------------------------------------------------------------
# now
# ---------------------------------------------------------------------------


def _cmd_now(args) -> int:
    _apply_utc_offset(args)
    offset = constants.utc_offset()
    today = local_today(offset)
    monday = today.fromordinal(today.toordinal() - today.weekday())
    print(f'今天（UTC{offset:+d}）：{today.isoformat()}')
    print(f'本周一：{monday.isoformat()}')
    print(f'上周：{monday.fromordinal(monday.toordinal() - 7).isoformat()} 至 '
          f'{monday.fromordinal(monday.toordinal() - 1).isoformat()}')
    print(f'本月：{today.replace(day=1).isoformat()} 至 {today.isoformat()}')
    if args.source:
        try:
            bundle = load_bundle(args.source)
        except SourceError as exc:
            print(f'[error] {exc}', file=sys.stderr)
            return 2
        start, end = _bundle_local_window(bundle)
        print(f'导出窗口（UTC{offset:+d}）：{start.isoformat()} 至 {end.isoformat()}')
        print(f'导出包：{bundle.counts.get("sessions")} 个会话 / '
              f'{bundle.counts.get("events")} 条事件')
    return 0


def _bundle_local_window(bundle):
    start_utc = parse_utc(bundle.window_start_utc)
    end_utc = parse_utc(bundle.window_end_utc)
    if not start_utc or not end_utc:
        raise WindowError(f'导出包没有可用的窗口信息：{bundle.window_start_utc!r} ~ {bundle.window_end_utc!r}')
    return utc_range_to_local_dates(start_utc, end_utc, 8)


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------


def _load_windowed(args):
    """读取导出包并按参数算出窗口；collect 与 facet plan 共用，保证口径一致。"""
    bundle = load_bundle(args.source)
    bundle_since, bundle_until = _bundle_local_window(bundle)
    natural = parse_natural_window(args.natural)
    window = compute_window(
        bundle_since=bundle_since, bundle_until=bundle_until,
        since=args.since or natural.get('since'), until=args.until or natural.get('until'),
        days=args.days or natural.get('days'),
        week=args.week or natural.get('week'), month=args.month or natural.get('month'),
        all_=args.all or natural.get('all_', False))
    return bundle, window


def _cmd_collect(args) -> int:
    _apply_utc_offset(args)
    try:
        bundle, window = _load_windowed(args)
    except SourceError as exc:
        print(f'[error] {exc}', file=sys.stderr)
        return 2
    except (WindowError, ValueError) as exc:
        print(f'[error] {exc}', file=sys.stderr)
        return 2

    from insights_core.metrics import select_sessions
    sessions, excluded = select_sessions(bundle, window)
    if not sessions:
        print('[error] 窗口内没有任何会话包含用户消息，换一个窗口试试', file=sys.stderr)
        return 2

    stats = aggregate(sessions, window, bundle, excluded)

    history_dir = Path(args.history_dir)
    prev_path = compare.find_prev_stats(history_dir, stats)
    prev_stats = json.loads(prev_path.read_text(encoding='utf-8')) if prev_path else None
    comparison = compare.compute(stats, prev_stats, prev_path)
    stats['comparison'] = asdict(comparison)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')

    saved = compare.save_history(history_dir, stats)
    _print_collect_summary(stats, out, saved, comparison)
    return 0


def _print_collect_summary(stats: dict, out: Path, saved: Path | None,
                           comparison) -> None:
    totals = stats['totals']
    print(f"窗口：{stats['window']['description']}（{stats['window']['days']} 天）")
    print(f"会话 {totals['sessions']}（实质 {totals['substantive_sessions']} / "
          f"快速 {totals['quick_sessions']}），消息 {totals['user_messages']}，"
          f"工具调用 {totals['tool_calls']}，报错 {totals['tool_errors']}")
    if comparison.available:
        print(f"环比：找到上期 {comparison.prev_window}")
    else:
        print(f"环比：{comparison.notes[0] if comparison.notes else '不可用'}")
    for warning in stats.get('warnings') or []:
        print(f'[warn] {warning}')
    print(f'stats → {out}')
    if saved:
        print(f'存档 → {saved}')



# ---------------------------------------------------------------------------
# facet：语义层
# ---------------------------------------------------------------------------


def _cmd_facet(args) -> int:
    if args.facet_command == 'plan':
        return _facet_plan(args)
    return _facet_merge(args)


def _facet_plan(args) -> int:
    _apply_utc_offset(args)
    try:
        bundle, window = _load_windowed(args)
    except (SourceError, WindowError, ValueError) as exc:
        print(f'[error] {exc}', file=sys.stderr)
        return 2

    from insights_core.metrics import select_sessions
    sessions, _ = select_sessions(bundle, window)
    if not sessions:
        print('[error] 窗口内没有任何会话包含用户消息', file=sys.stderr)
        return 2

    by_session: dict = {}
    for event in bundle.events:
        by_session.setdefault((event.agent, event.session_id), []).append(event)
    plan = facets.build_plan(sessions, by_session, limit=args.limit, only=args.session)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')

    totals = plan['totals']
    sizes = sorted(len(task['prompt']['user']) for task in plan['tasks'])
    median = sizes[len(sizes) // 2] if sizes else 0
    print(f'窗口：{window.description}（{window.days} 天）')
    print(f"会话 {totals['sessions']}：实质 {totals['substantive']} / 快速 {totals['quick']}；"
          f"生成任务 {totals['tasks']} 份，digest 中位 {median} 字符")
    for warning in plan['warnings']:
        print(f'[warn] {warning}')
    print(f'tasks → {out}')
    print('下一步：按 tasks[i].prompt 提取，产出 results.json 后运行 facet merge')
    return 0


def _facet_merge(args) -> int:
    try:
        plan = facets.load_tasks(args.tasks)
        results = facets.load_results(args.results)
    except (OSError, ValueError, facets.FacetsError) as exc:
        print(f'[error] {exc}', file=sys.stderr)
        return 2

    documents, warnings = facets.merge_results(plan, results)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(documents, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.summary:
        summary_path = Path(args.summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(documents['summary'], ensure_ascii=False, indent=2),
                                encoding='utf-8')

    coverage = documents['coverage']
    print(f"覆盖：{coverage['accepted']}/{coverage['tasks']} 个会话（缺 {coverage['missing']}）")
    for key, count in documents['summary']['by_category'].items():
        if count:
            print(f"  {facets.GOAL_CATEGORIES[key]}：{count}")
    for warning in warnings[:12]:
        print(f'[warn] {warning}')
    if len(warnings) > 12:
        print(f'[warn] ...另有 {len(warnings) - 12} 条')
    print(f'facets → {out}')
    return 0 if coverage['accepted'] else 1

# ---------------------------------------------------------------------------
# render / validate
# ---------------------------------------------------------------------------


def _load_stats(path: str) -> dict:
    stats = json.loads(Path(path).read_text(encoding='utf-8'))
    errors = check_stats(stats)
    if errors:
        raise SystemExit('[error] stats 不符合契约：\n- ' + '\n- '.join(errors))
    return stats


def _load_narratives(path: str) -> dict:
    data = narrative.load(path)
    narrative.assert_schema(data)
    return data


def _cmd_render(args) -> int:
    stats = _load_stats(args.stats)
    narratives = _load_narratives(args.narratives)
    facets_doc = json.loads(Path(args.facets).read_text(encoding='utf-8')) if args.facets else None
    for warning in narrative.validate_content(narratives, stats, facets_doc):
        print(f'[warn] {warning}')
    comparison = compare.from_dict(stats.get('comparison') or '', '')
    html_text = render.render_html(stats, narratives, comparison, facets_doc)
    target = render.write_report(html_text, args.out, prefix=args.prefix,
                                 window=stats.get('window'))
    print(f'报告 → {target}（{target.stat().st_size // 1024} KB）')
    return 0


def _cmd_validate(args) -> int:
    if not args.stats and not args.narratives:
        print('[error] 至少给 --stats 或 --narratives 之一', file=sys.stderr)
        return 2

    stats: dict = {}
    code = 0
    if args.stats:
        stats = json.loads(Path(args.stats).read_text(encoding='utf-8'))
        errors = check_stats(stats)
        if errors:
            print('stats 契约：不通过')
            for error in errors:
                print(f'  - {error}')
            code = 1
        else:
            print('stats 契约：通过')
        for warning in stats.get('warnings') or []:
            print(f'[warn] {warning}')

    if args.narratives:
        try:
            data = narrative.load(args.narratives)
            narrative.assert_schema(data)
        except narrative.NarrativeError as exc:
            print(f'narratives 契约：不通过（{exc}）')
            return 1
        facets_doc = json.loads(Path(args.facets).read_text(encoding='utf-8')) if args.facets else None
        warnings = narrative.validate_content(data, stats, facets_doc)
        print(f'narratives 契约：通过（{len(warnings)} 条内容提醒）')
        for warning in warnings:
            print(f'[warn] {warning}')
    return code


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


HANDLERS = {
    'now': _cmd_now,
    'collect': _cmd_collect,
    'facet': _cmd_facet,
    'render': _cmd_render,
    'validate': _cmd_validate,
}


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    args = _build_parser().parse_args(argv)
    try:
        return HANDLERS[args.command](args)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
