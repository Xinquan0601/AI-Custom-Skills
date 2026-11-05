"""领域模型：项目归并、能力族、报错分类、伪消息识别、diff 行数。"""
from __future__ import annotations

import pytest
from insights_core.model import (
    canonical_project,
    diff_line_counts,
    is_synthetic_user_message,
    strip_error_banner,
    tool_error_category,
    tool_family,
    truncate,
)


@pytest.mark.parametrize('project,cwd,want', [
    ('insights', 'D:/prj/insights', 'insights'),
    ('', 'D:/prj/RK3576_Linux_Sdk', 'RK3576_Linux_Sdk'),
    ('d-prj-win-dv454', 'D:/prj-win/dv454', 'dv454'),
    ('', '', '未标注项目'),
    ('Default Project', 'D:/x', '未标注项目'),
    ('Temp', 'D:/x', '未标注项目'),
])
def test_canonical_project(project, cwd, want):
    assert canonical_project(project, cwd) == want


def test_timestamp_directory_becomes_temp_session():
    assert canonical_project('', 'D:/prj/WorkBuddy/2026-11-01-10-20-30') == 'WorkBuddy 临时会话'


@pytest.mark.parametrize('name,family', [
    ('run_code', 'exec'),
    ('bash', 'exec'),
    ('edit', 'edit'),
    ('write', 'edit'),
    ('read', 'read'),
    ('grep', 'search'),
    ('web_search', 'web'),
    ('spawn_agent', 'agent'),
    ('question', 'other'),
])
def test_tool_family(name, family):
    assert tool_family(name) == family


def test_error_category_ignores_sandbox_banner():
    text = 'cannot read "C:/x/a.py"\nFile sandbox: workspace-write.'
    assert 'File sandbox' not in strip_error_banner(text)
    assert tool_error_category(text) == 'file_access'


def test_error_category_empty_body_is_not_guessed():
    assert tool_error_category('', 'edit') == 'unclassified'
    assert tool_error_category('', 'read') == 'unclassified'
    assert tool_error_category('', '') == 'unclassified'


def test_error_category_syntax_and_runtime():
    assert tool_error_category('Expected a semicolon') == 'syntax'
    assert tool_error_category('TypeError: x is not a function') == 'runtime'
    assert tool_error_category('old_string was not found') == 'edit_conflict'
    assert tool_error_category('command failed with exit code 2') == 'command_failed'
    assert tool_error_category('grep search failed') == 'other'


@pytest.mark.parametrize('text', [
    'Time sampled while preparing turn 2',
    '<path>a.png</path><type>image</type>',
    'The approval policy changed from "ask" to "never"',
])
def test_synthetic_detection(text):
    assert is_synthetic_user_message(text) is True


@pytest.mark.parametrize('text', ['帮我看看这个 bug', '  Time 采样说明不是前缀'])
def test_real_message_is_not_synthetic(text):
    assert is_synthetic_user_message(text) is False


def test_diff_line_counts():
    assert diff_line_counts('a\nb\n', 'a\nb\nc\n') == (1, 0)
    assert diff_line_counts('a\nb\n', 'a\n') == (0, 1)
    assert diff_line_counts('a\n', 'b\n') == (1, 1)


def test_truncate_keeps_short_and_marks_long():
    assert truncate('abc', 10) == 'abc'
    assert truncate('a' * 20, 10).endswith('…')
    assert len(truncate('a' * 20, 10)) == 11
