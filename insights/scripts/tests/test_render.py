"""渲染：单文件离线 HTML、区块齐全、永不覆盖旧报告。"""
from __future__ import annotations

from insights_core import compare, render
from insights_core.metrics import select_sessions
from insights_core.stats import aggregate


def make_inputs(bundle, window):
    sessions, excluded = select_sessions(bundle, window)
    stats = aggregate(sessions, window, bundle, excluded)
    narratives = {
        'schema_version': 2,
        'overview': {
            'whats_working': '你把 AI 当执行者。',
            'whats_hindering': '文件层报错集中。',
            'quick_wins': '先读后改。',
            'ambitious_workflows': '把调研拆成多份。',
        },
        'project_areas': {'areas': [{'name': 'insights', 'session_count': 1,
                                     'description': '重写报告管线。'}]},
        'interaction_style': {'narrative': '你更愿意给目标而不是指令。', 'key_pattern': '目标先行。'},
        'what_works': {'intro': '有几件事做得漂亮。',
                       'impressive_workflows': [{'title': '统一视觉', 'description': '逐页检查。',
                                                 'source': '拆报告模块'}]},
        'friction_analysis': {'intro': '报错不多但集中。',
                              'categories': [{'category': '文件读写失败（1 次）',
                                              'description': '路径越界。',
                                              'examples': ['cannot read'], 'source': '拆报告模块'}]},
        'suggestions': {'agents_md_additions': [{'addition': '改文件前先读。', 'why': '少返工。',
                                                 'source': '拆报告模块'}],
                        'features_to_try': [{'feature': '子代理并行', 'one_liner': '拆调研。',
                                             'why_for_you': '你已经在并行。'}]},
        'on_the_horizon': {'intro': '再往前一步。',
                           'opportunities': [{'title': '周报自动化', 'description': '固定节奏。'}]},
        'fun_ending': {'headline': '凌晨还在追问。', 'detail': '0 点还有 30 条消息。'},
    }
    return stats, narratives


def test_render_html_is_self_contained(bundle, window):
    stats, narratives = make_inputs(bundle, window)
    html_text = render.render_html(stats, narratives, compare.compute(stats, None))
    assert html_text.startswith('<!DOCTYPE html>') or html_text.startswith('<!doctype html>')
    assert 'AI 使用洞察报告' in html_text
    assert '总览' in html_text and '问题出在哪' in html_text
    assert 'http://' not in html_text and 'https://' not in html_text
    assert 'fonts.googleapis' not in html_text
    assert stats['window']['description'] in html_text


def test_render_discloses_warnings(bundle, window):
    stats, narratives = make_inputs(bundle, window)
    stats['warnings'] = ['导出事件可能被截断', 'token 覆盖只有 2/3']
    html_text = render.render_html(stats, narratives, compare.compute(stats, None))
    assert '导出事件可能被截断' in html_text
    assert 'token 覆盖只有 2/3' in html_text


def make_facets(duplicates: int = 0) -> dict:
    accepted = 3
    tasks = accepted + duplicates
    return {
        'schema_version': 1,
        'coverage': {'tasks': tasks, 'unique_tasks': accepted, 'accepted': accepted,
                     'duplicates_merged': duplicates, 'missing': 0, 'evidence_pass': accepted},
        'summary': {
            'by_category': {'arch_review': 2, 'fw_defect': 1},
            'by_outcome': {'closed': 2, 'mostly': 1},
            'by_friction': {'incomplete': 2},
            'instructions': [{'text': '改完跑测试', 'sessions': 2}],
            'coverage_ratio': 1.0,
        },
    }


def test_render_includes_facets_section(bundle, window):
    stats, narratives = make_inputs(bundle, window)
    html_text = render.render_html(stats, narratives, compare.compute(stats, None), make_facets())
    assert 'id="sec-facets"' in html_text
    assert '这些会话最终做成了什么' in html_text
    assert '架构审查与调研' in html_text
    assert '已提取 3/3 场' in html_text
    assert '改完跑测试' in html_text


def test_render_without_facets_skips_section(bundle, window):
    stats, narratives = make_inputs(bundle, window)
    html_text = render.render_html(stats, narratives, compare.compute(stats, None))
    assert 'sec-facets' not in html_text
    assert '这些会话最终做成了什么' not in html_text


def test_render_discloses_duplicate_exports(bundle, window):
    stats, narratives = make_inputs(bundle, window)
    html_text = render.render_html(stats, narratives, compare.compute(stats, None),
                                   make_facets(duplicates=2))
    assert '另有 2 条任务来自同一场对话的多客户端重复导出，已合并' in html_text
    assert '原始 5 条任务' in html_text


WINDOW = {'since': '2026-10-01', 'until': '2026-10-31'}


def test_write_report_names_by_window(tmp_path):
    html_text = '<!DOCTYPE html><html><body>ok</body></html>'
    target = render.write_report(html_text, tmp_path, window=WINDOW)
    assert target.name == 'AI使用洞察报告-20261001-20261031.html'
    assert target.read_text(encoding='utf-8') == html_text


def test_write_report_never_overwrites(tmp_path):
    html_text = '<!DOCTYPE html><html><body>ok</body></html>'
    first = render.write_report(html_text, tmp_path, window=WINDOW)
    second = render.write_report(html_text, tmp_path, window=WINDOW)
    assert first.name == 'AI使用洞察报告-20261001-20261031.html'
    assert second.name == 'AI使用洞察报告-20261001-20261031-2.html'


def test_write_report_honours_prefix_and_single_day(tmp_path):
    target = render.write_report('x', tmp_path, prefix='周报',
                                 window={'since': '2026-11-05', 'until': '2026-11-05'})
    assert target.name == '周报-20261105-20261105.html'


def test_write_report_without_window_falls_back_to_prefix(tmp_path):
    assert render.write_report('x', tmp_path, prefix='临时').name == '临时.html'
