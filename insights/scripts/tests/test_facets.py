"""语义层：digest 确定性、计划覆盖、结果校验与聚合。"""
from __future__ import annotations

import collections
import copy
from dataclasses import replace

from insights_core import facets
from insights_core.metrics import select_sessions


def _sessions_and_events(bundle, window):
    sessions, _ = select_sessions(bundle, window)
    events: dict = {}
    for event in bundle.events:
        events.setdefault((event.agent, event.session_id), []).append(event)
    return sessions, events


def _plan(bundle, window, **kwargs):
    sessions, events = _sessions_and_events(bundle, window)
    return sessions, events, facets.build_plan(sessions, events, **kwargs)


def test_taxonomy_is_unique_and_complete():
    keys = list(facets.GOAL_CATEGORIES)
    assert len(keys) == len(set(keys)) == 10
    assert all(label.strip() for label in facets.GOAL_CATEGORIES.values())
    assert set(facets.OUTCOMES) == {'closed', 'mostly', 'partial', 'open'}
    assert 'silent_error' in facets.FRICTION_TYPES


def test_digest_is_deterministic_and_has_cache_key(bundle, window):
    sessions, events = _sessions_and_events(bundle, window)
    session = next(s for s in sessions if s.session_id == 's1')
    first = facets.build_digest(session, events[('dsh', 's1')])
    second = facets.build_digest(session, list(events[('dsh', 's1')]))
    assert first.as_dict() == second.as_dict()
    assert len(first.cache_key) == 16
    assert first.messages == ['先读一下 render 的模板结构', '把这段拆成模块']


def test_digest_pairs_user_messages_with_replies(bundle, window):
    sessions, events = _sessions_and_events(bundle, window)
    session = next(s for s in sessions if s.session_id == 's1')
    digest = facets.build_digest(session, events[('dsh', 's1')])
    assert [turn['user'] for turn in digest.turns] == digest.messages
    assert [turn['reply'] for turn in digest.turns] == ['好', '好']
    assert digest.final_assistant == '好'
    assert digest.final_assistant_at.endswith('10:05')


def test_digest_reply_is_empty_when_agent_did_not_answer(bundle, window):
    sessions, events = _sessions_and_events(bundle, window)
    session = next(s for s in sessions if s.session_id == 's1')
    only_users = [event for event in events[('dsh', 's1')] if event.type == 'user_message']
    digest = facets.build_digest(session, only_users)
    assert [turn['reply'] for turn in digest.turns] == ['', '']
    assert digest.final_assistant == ''


def test_digest_survives_duplicated_events(bundle, window):
    sessions, events = _sessions_and_events(bundle, window)
    session = next(s for s in sessions if s.session_id == 's1')
    source = events[('dsh', 's1')][:2]          # 用户消息 + 回复
    duplicated = [source[0], source[0], source[1]]
    digest = facets.build_digest(session, duplicated)
    assert len(digest.turns) == 1
    assert digest.turns[0]['reply'] == '好'


def test_digest_keeps_last_reply_of_turn(bundle, window):
    from conftest import make_event
    sessions, events = _sessions_and_events(bundle, window)
    session = next(s for s in sessions if s.session_id == 's1')
    first = events[('dsh', 's1')][0]
    draft = make_event(type='assistant_message', ts='2026-10-30T02:00:05Z', content='我先看看')
    final = make_event(type='assistant_message', ts='2026-10-30T02:00:30Z', content='模板在 render/templates 下')
    digest = facets.build_digest(session, [first, draft, final])
    assert digest.turns[0]['reply'] == '模板在 render/templates 下'


def test_digest_skips_reasoning_style_replies(bundle, window):
    from conftest import make_event
    sessions, events = _sessions_and_events(bundle, window)
    session = next(s for s in sessions if s.session_id == 's1')
    source = events[('dsh', 's1')][:2]
    reasoning = make_event(type='assistant_message', ts='2026-10-30T02:00:10Z',
                           content='The user asks how to read the template.')
    digest = facets.build_digest(session, [source[0], reasoning, source[1]])
    assert digest.turns[0]['reply'] == '好'
    assert digest.final_assistant == '好'


def test_digest_evidence_includes_assistant_text(bundle, window):
    sessions, events = _sessions_and_events(bundle, window)
    session = next(s for s in sessions if s.session_id == 's1')
    digest = facets.build_digest(session, events[('dsh', 's1')])
    text = facets._digest_text(digest.as_dict())
    assert '好' in text and '先读一下 render 的模板结构' in text


def test_digest_compacts_local_paths(bundle, window):
    sessions, events = _sessions_and_events(bundle, window)
    session = next(s for s in sessions if s.session_id == 's1')
    digest = facets.build_digest(session, events[('dsh', 's1')])
    assert digest.files and all('D:' not in path for path in digest.files)
    assert digest.files[0].endswith('a.py')


def test_digest_merges_tool_name_case(bundle, window):
    sessions, events = _sessions_and_events(bundle, window)
    session = next(s for s in sessions if s.session_id == 's1')
    session.tool_name_counts = collections.Counter({'Bash': 3, 'bash': 2, 'edit': 1})
    digest = facets.build_digest(session, events[('dsh', 's1')])
    assert digest.tools[0].startswith('Bash×5')


def test_messages_drop_noise_and_near_duplicates():
    kept = facets._dedupe_messages([
        '请继续执行任务',
        'Please continue with the conversation based on the summarized context above.',
        '把报警逻辑改一下，只在绑定输出时拉高',
        '把报警逻辑改一下，只在绑定输出时拉高，另外补一版说明',
        '好',
    ])
    assert kept == ['把报警逻辑改一下，只在绑定输出时拉高，另外补一版说明']


def test_plan_only_covers_substantive_sessions(bundle, window):
    sessions, events, plan = _plan(bundle, window)
    assert plan['totals'] == {'sessions': 3, 'substantive': 2, 'quick': 1, 'tasks': 2}
    assert {task['session_id'] for task in plan['tasks']} == {'s1', 's3'}
    assert all(task['prompt']['system'] for task in plan['tasks'])


def test_plan_warns_when_over_limit(bundle, window):
    _, _, plan = _plan(bundle, window, limit=1)
    assert plan['totals']['tasks'] == 1
    assert any('只提取最近' in warning for warning in plan['warnings'])


def test_plan_can_filter_single_session(bundle, window):
    _, _, plan = _plan(bundle, window, only=['s3'])
    assert [task['session_id'] for task in plan['tasks']] == ['s3']


def test_cache_key_changes_with_content(bundle, window):
    sessions, events = _sessions_and_events(bundle, window)
    session = next(s for s in sessions if s.session_id == 's1')
    before = facets.build_digest(session, events[('dsh', 's1')])
    changed = copy.deepcopy(events[('dsh', 's1')])
    changed[0] = replace(changed[0], content='先读一下渲染层的模板结构')
    after = facets.build_digest(session, changed)
    assert before.cache_key != after.cache_key


def _result(session_id: str, **overrides) -> dict:
    record = {
        'session_id': session_id,
        'goal_category': 'fw_defect',
        'outcome': 'closed',
        'summary': '把报告模块拆开',
        'evidence': ['拆报告模块'],
        'friction': [],
        'instructions': [],
        'helpfulness': 3,
        'satisfaction': 'positive',
    }
    record.update(overrides)
    return record


def test_merge_accepts_valid_result(bundle, window):
    _, _, plan = _plan(bundle, window)
    documents, warnings = facets.merge_results(plan, [_result('s1')])
    assert documents['coverage'] == {'tasks': 2, 'unique_tasks': 2, 'accepted': 1,
                                      'duplicates_merged': 0, 'missing': 1, 'evidence_pass': 1}
    assert documents['summary']['by_category']['fw_defect'] == 1
    assert any('没有提取结果' in warning for warning in warnings)


def test_merge_folds_multi_client_duplicates():
    def task(session_id):
        digest = {'session_id': session_id, 'project': 'p1', 'title': '同一场会话',
                  'turns': [{'user': '先看日志', 'reply': '好'}],
                  'user_messages_text': ['先看日志'], 'final_assistant': '做完了'}
        return {'session_id': session_id, 'cache_key': 'k',
                'digest': digest, 'prompt': {'system': '', 'user': ''}}

    def result(session_id):
        return {'session_id': session_id, 'goal_category': 'fw_defect', 'outcome': 'mostly',
                'friction': [], 'helpfulness': 3, 'satisfaction': 'neutral',
                'summary': '看日志', 'evidence': ['先看日志'], 'instructions': []}

    plan = {'tasks': [task('opencode-local:abc'), task('abc')]}
    documents, warnings = facets.merge_results(
        plan, [result('opencode-local:abc'), result('abc')])
    assert documents['coverage']['accepted'] == 1
    assert documents['coverage']['duplicates_merged'] == 1
    assert documents['facets'][0]['session_id'] == 'abc'
    assert any('多客户端重复导出' in warning for warning in warnings)


def test_merge_rejects_unknown_enums_and_paraphrased_evidence(bundle, window):
    _, _, plan = _plan(bundle, window)
    documents, warnings = facets.merge_results(plan, [
        _result('s1', goal_category='not_a_category'),
        _result('s3', evidence=['USB 枚举日志排查']),   # 逐字不在 digest 里
    ])
    assert documents['coverage']['accepted'] == 0
    assert any('枚举' in warning for warning in warnings)
    assert any('evidence' in warning for warning in warnings)


def test_merge_ignores_unknown_session_and_duplicates(bundle, window):
    _, _, plan = _plan(bundle, window)
    documents, warnings = facets.merge_results(plan, [
        _result('s1'), _result('s1'), _result('missing-id'),
    ])
    assert documents['coverage']['accepted'] == 1
    assert any('重复结果' in warning for warning in warnings)
    assert any('不在任务列表' in warning for warning in warnings)


def test_merge_skips_records_missing_required_field(bundle, window):
    _, _, plan = _plan(bundle, window)
    record = _result('s1')
    record.pop('summary')
    documents, warnings = facets.merge_results(plan, [record])
    assert documents['coverage']['accepted'] == 0
    assert any('缺字段 summary' in warning for warning in warnings)
