"""聚合层：口径、能力族、代码产出、报错分类、stats 契约。"""
from __future__ import annotations

import copy
from types import SimpleNamespace

from insights_core import constants
from insights_core.metrics import select_sessions
from insights_core.stats import aggregate, check_stats, detect_duplicate_sessions


def build_stats(bundle, window) -> dict:
    sessions, excluded = select_sessions(bundle, window)
    return aggregate(sessions, window, bundle, excluded)


def test_utc_offset_reads_env_and_falls_back(monkeypatch):
    monkeypatch.setenv(constants.UTC_OFFSET_ENV, '0')
    assert constants.utc_offset() == 0
    monkeypatch.setenv(constants.UTC_OFFSET_ENV, '99')
    assert constants.utc_offset() == constants.DEFAULT_UTC_OFFSET_HOURS
    monkeypatch.delenv(constants.UTC_OFFSET_ENV)
    assert constants.utc_offset() == constants.DEFAULT_UTC_OFFSET_HOURS


def test_duplicate_sessions_across_clients_are_detected():
    sessions = [
        SimpleNamespace(project='p', session_id='opencode-local:ses_a', substantive=True),
        SimpleNamespace(project='p', session_id='ses_a', substantive=True),
        SimpleNamespace(project='p', session_id='opencode-linux:ses_a', substantive=False),
        SimpleNamespace(project='p', session_id='ses_b', substantive=True),
    ]
    found = detect_duplicate_sessions(sessions)
    assert found['groups'] == 1
    assert found['extra_sessions'] == 2
    assert found['extra_substantive'] == 1
    assert found['clients'] == ['opencode-linux', 'opencode-local']


def test_stats_carry_duplicate_block_and_warning(bundle, window):
    stats = build_stats(bundle, window)
    assert stats['duplicates']['extra_sessions'] == 0
    assert not any('重复导出' in warning for warning in stats['warnings'])


def test_select_sessions_counts_everything_in_window(bundle, window):
    sessions, excluded = select_sessions(bundle, window)
    assert excluded == 0
    by_id = {s.session_id: s for s in sessions}
    assert by_id['s1'].user_messages == 2          # 伪用户消息被剔除
    assert by_id['s1'].tool_calls == 2
    assert by_id['s2'].substantive is False
    assert by_id['s3'].substantive is True


def test_totals_split_substantive_and_quick(bundle, window):
    stats = build_stats(bundle, window)
    totals = stats['totals']
    assert totals['sessions'] == 3
    assert totals['substantive_sessions'] == 2
    assert totals['quick_sessions'] == 1
    assert totals['user_messages'] == 5
    assert totals['tool_calls'] == 3
    assert totals['tool_errors'] == 1
    assert stats['code']['git_commits'] == 1
    assert totals['days_active'] == 3


def test_tool_families_and_top_tools(bundle, window):
    stats = build_stats(bundle, window)
    families = stats['tools']['families']
    assert families['exec'] == 2
    assert families['edit'] == 1
    assert {row['name'] for row in stats['tools']['top_tools']} == {'bash', 'run_code', 'edit'}
    assert set(stats['tools']['by_family']) == {'exec', 'edit'}


def test_code_lines_come_from_tool_input(bundle, window):
    stats = build_stats(bundle, window)
    assert stats['code']['lines_added'] == 1
    assert stats['code']['lines_removed'] == 0
    assert stats['code']['files'] == 1
    assert stats['code']['languages'] == {'Python': 1}


def test_friction_strips_sandbox_banner(bundle, window):
    stats = build_stats(bundle, window)
    friction = stats['friction']
    assert friction['tool_errors'] == 1
    assert friction['categories'] == {'sandbox_permission': 1}
    assert friction['by_tool'][0]['name'] == 'bash'
    assert 'SetNamedSecurityInfoW' in friction['examples'][0]['text']


def test_warnings_are_passed_through(bundle, window):
    stats = build_stats(bundle, window)
    assert 'fixture warning' in stats['warnings']


def test_narrative_material_samples_skip_synthetic(bundle, window):
    stats = build_stats(bundle, window)
    samples = {row['session']: row for row in stats['narrative_material']['session_samples']}
    assert len(samples) == 3
    assert samples['s1']['messages'][0].startswith('先读一下')
    assert all('Time sampled' not in text for text in samples['s1']['messages'])


def test_stats_contract_passes(bundle, window):
    assert check_stats(build_stats(bundle, window)) == []


def test_stats_contract_reports_missing_keys(bundle, window):
    stats = build_stats(bundle, window)
    broken = copy.deepcopy(stats)
    del broken['friction']
    errors = check_stats(broken)
    assert any('缺字段' in error for error in errors)


def test_stats_contract_reports_bad_version(bundle, window):
    stats = build_stats(bundle, window)
    stats['schema_version'] = 1
    assert any('schema_version' in error for error in check_stats(stats))
