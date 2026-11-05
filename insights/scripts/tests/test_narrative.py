"""叙事契约：结构错误阻断、内容空缺警告、source 可追溯性校验。"""
from __future__ import annotations

import copy

import pytest
from insights_core import narrative

STATS = {
    'sessions': [
        {'id': 'a1b2c3d4e5', 'title': '拆报告模块'},
        {'id': 'f6g7h8i9j0', 'title': 'USB 枚举排查'},
    ],
    'narrative_material': {
        'session_samples': [
            {'session': 'a1b2c3d4e5', 'messages': ['先读一下 render 的模板结构']},
        ],
    },
}


def make_narratives() -> dict:
    return {
        'schema_version': 2,
        'overview': {
            'whats_working': '你把 AI 当执行者。',
            'whats_hindering': '报错集中在文件层。',
            'quick_wins': '先读后改。',
            'ambitious_workflows': '把一个调研拆成五份。',
        },
        'project_areas': {'areas': [{'name': 'insights', 'session_count': 2,
                                     'description': '重写报告管线。'}]},
        'interaction_style': {'narrative': '你更愿意给目标而不是指令。',
                              'key_pattern': '目标先行——例如「拆成模块」。'},
        'what_works': {'intro': '这周有几件事做得漂亮。',
                       'impressive_workflows': [{'title': '统一视觉', 'description': '逐页检查。',
                                                 'source': '拆报告模块'}]},
        'friction_analysis': {'intro': '报错不多但集中。',
                              'categories': [{'category': '文件读写失败（2 次）',
                                              'description': '路径越界。',
                                              'examples': ['cannot read'], 'source': 'a1b2c3d4e5'}]},
        'suggestions': {'agents_md_additions': [{'addition': '改文件前先读。', 'why': '少返工。',
                                                 'source': '拆报告模块'}],
                        'features_to_try': [{'feature': '子代理并行', 'one_liner': '拆调研。',
                                             'why_for_you': '你已经在并行。'}]},
        'on_the_horizon': {'intro': '再往前一步。',
                           'opportunities': [{'title': '周报自动化', 'description': '固定节奏。'}]},
        'fun_ending': {'headline': '周日只说了 1 句。', 'detail': '凌晨 0 点还在追问。'},
    }


def test_valid_narratives_pass_schema():
    narrative.assert_schema(make_narratives())


def test_wrong_version_is_rejected():
    data = make_narratives()
    data['schema_version'] = 1
    with pytest.raises(narrative.NarrativeError, match='schema_version'):
        narrative.assert_schema(data)


def test_missing_section_is_rejected():
    data = make_narratives()
    del data['friction_analysis']
    with pytest.raises(narrative.NarrativeError, match='friction_analysis'):
        narrative.assert_schema(data)


def test_non_object_section_is_rejected():
    data = make_narratives()
    data['overview'] = 'x'
    with pytest.raises(narrative.NarrativeError, match='overview'):
        narrative.assert_schema(data)


def test_valid_narratives_have_no_content_warnings():
    assert narrative.validate_content(make_narratives(), STATS) == []


def test_empty_sections_produce_warnings():
    data = make_narratives()
    data['overview'] = {}
    data['project_areas'] = {'areas': []}
    data['what_works'] = {'impressive_workflows': []}
    data['fun_ending'] = {}
    warnings = narrative.validate_content(data, STATS)
    assert any('overview.whats_working' in w for w in warnings)
    assert any('project_areas' in w for w in warnings)
    assert any('what_works' in w for w in warnings)


def test_fabricated_source_is_flagged():
    data = make_narratives()
    data['what_works']['impressive_workflows'][0]['source'] = '某次不存在的会话'
    warnings = narrative.validate_content(data, STATS)
    assert any('疑似编造' in w for w in warnings)


def test_real_message_fragment_is_accepted():
    data = make_narratives()
    data['friction_analysis']['categories'][0]['source'] = '先读一下 render 的模板结构'
    assert narrative.validate_content(data, STATS) == []


def test_fabricated_number_is_flagged():
    data = make_narratives()
    data['what_works']['intro'] = '这周一共改了 98765 行。'
    warnings = narrative.validate_content(data, STATS)
    assert any('98765' in warning for warning in warnings)


def test_number_from_stats_is_accepted():
    stats = copy.deepcopy(STATS)
    stats['totals'] = {'lines_added': 12345}
    data = make_narratives()
    data['what_works']['intro'] = '一共 12,345 行。'
    assert narrative.validate_content(data, stats) == []


def test_percentage_matching_ratio_is_accepted():
    stats = copy.deepcopy(STATS)
    stats.update({'part': 9, 'total': 77})
    data = make_narratives()
    data['what_works']['intro'] = '闭环率 11.7%。'
    assert narrative.validate_content(data, stats) == []


def test_percentage_without_source_is_flagged():
    data = make_narratives()
    data['what_works']['intro'] = '闭环率 91.3%。'
    warnings = narrative.validate_content(data, STATS)
    assert any('91.3%' in warning for warning in warnings)


def test_load_reports_missing_file(tmp_path):
    with pytest.raises(narrative.NarrativeError, match='不存在'):
        narrative.load(tmp_path / 'nope.json')


def test_load_reports_bad_json(tmp_path):
    target = tmp_path / 'bad.json'
    target.write_text('{oops', encoding='utf-8')
    with pytest.raises(narrative.NarrativeError, match='不是合法 JSON'):
        narrative.load(target)


def test_copy_is_independent():
    data = make_narratives()
    clone = copy.deepcopy(data)
    clone['overview']['whats_working'] = 'x'
    assert data['overview']['whats_working'] != 'x'
