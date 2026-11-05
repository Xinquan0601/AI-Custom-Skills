"""AgentTrail 适配器：字段映射、伪消息标记、去重、完整度告警。"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from insights_core.sources import SourceError, load_bundle

SESSION_HEADER = ('agent_key,external_id,title,project,cwd,model,started_at,ended_at,'
                  'message_count,user_message_count,assistant_message_count,'
                  'tool_call_count,tool_result_count,event_count,tokens_input,'
                  'tokens_output,source_path')
EVENT_HEADER = ('event_id,agent,session_id,event_type,timestamp,content,tool_name,'
                'tool_call_id,tool_status,tool_input_json,model,tokens_input,'
                'tokens_output,fingerprint')


def _session_row(sid='s1', agent='dsh', tool_calls=1, user_messages=2,
                 started='2026-10-30T02:00:00.000Z') -> str:
    return (f'{agent},{sid},会话{sid},项目,{chr(92)}prj,deepseek-v4,{started},'
            f'2026-10-30T03:00:00.000Z,4,{user_messages},2,{tool_calls},0,10,100,50,src')


def _event_row(fields: dict, fingerprint='f1') -> str:
    base = {
        'event_id': 'e1', 'agent': 'dsh', 'session_id': 's1',
        'event_type': 'user_message', 'timestamp': '2026-10-30T02:00:00.000Z',
        'content': '帮我看看渲染', 'tool_name': '', 'tool_call_id': '',
        'tool_status': '', 'tool_input_json': '', 'model': 'deepseek-v4',
        'tokens_input': '0', 'tokens_output': '0', 'fingerprint': fingerprint,
    }
    base.update(fields)
    return ','.join(f'"{base[key]}"' for key in base)


def _make_zip(tmp_path: Path, *, events: list[str], sessions: list[str] | None = None,
              manifest: dict | None = None) -> Path:
    target = tmp_path / 'agenttrail-test.zip'
    manifest = manifest if manifest is not None else {
        'export_version': 'test-1',
        'generated_at': '2026-11-05T09:00:00Z',
        'filters': {'from': '2026-10-29T16:00:00Z', 'to': '2026-11-05T15:59:59.999Z'},
        'counts': {'sessions': len(sessions or []), 'events': len(events)},
    }
    with zipfile.ZipFile(target, 'w') as zf:
        zf.writestr('manifest.json', json.dumps(manifest))
        zf.writestr('sessions.csv', SESSION_HEADER + '\n' + '\n'.join(sessions or []))
        zf.writestr('events.csv', EVENT_HEADER + '\n' + '\n'.join(events))
    return target


def test_load_reads_sessions_and_window(tmp_path):
    path = _make_zip(tmp_path, sessions=[_session_row()], events=[_event_row({})])
    bundle = load_bundle(path)
    assert bundle.kind == 'agenttrail'
    assert bundle.export_version == 'test-1'
    assert bundle.window_start_utc.startswith('2026-10-29T16:00')
    assert [s.session_id for s in bundle.sessions] == ['s1']
    assert bundle.events[0].content == '帮我看看渲染'
    assert bundle.counts['events'] == 1


def test_synthetic_user_messages_are_flagged(tmp_path):
    events = [
        _event_row({}, fingerprint='a'),
        _event_row({'event_id': 'e2', 'content': 'Time sampled while preparing turn 2'},
                   fingerprint='b'),
        _event_row({'event_id': 'e3', 'content': '<path>a.png</path><type>image</type>'},
                   fingerprint='c'),
    ]
    bundle = load_bundle(_make_zip(tmp_path, sessions=[_session_row()], events=events))
    assert [e.synthetic for e in bundle.events] == [False, True, True]
    assert any('伪用户消息' in w for w in bundle.warnings)


def test_fingerprint_dedupes(tmp_path):
    events = [_event_row({}, fingerprint='same'), _event_row({'event_id': 'e2'}, fingerprint='same')]
    bundle = load_bundle(_make_zip(tmp_path, sessions=[_session_row()], events=events))
    assert len(bundle.events) == 1
    assert any('去重 1 条' in w for w in bundle.warnings)


def test_missing_declared_counts_warns(tmp_path):
    manifest = {'filters': {'from': '2026-10-29T16:00:00Z',
                            'to': '2026-11-05T15:59:59.999Z'},
                'counts': {'sessions': 5, 'events': 99}}
    bundle = load_bundle(_make_zip(tmp_path, sessions=[_session_row()],
                                   events=[_event_row({})], manifest=manifest))
    assert any('声明 5 个会话' in w for w in bundle.warnings)
    assert any('声明 99 条事件' in w for w in bundle.warnings)


def test_partial_session_warns_about_truncation(tmp_path):
    # 会话级声明 5 次工具调用，事件里只有 1 次 → 说明事件被截断
    path = _make_zip(tmp_path, sessions=[_session_row(tool_calls=5)],
                     events=[_event_row({}),
                             _event_row({'event_id': 'e2', 'event_type': 'tool_call',
                                         'tool_name': 'run_code'}, fingerprint='t1')])
    bundle = load_bundle(path)
    assert any('窗口开始前就已开始' in w for w in bundle.warnings)


def test_bad_rows_are_skipped_with_warning(tmp_path):
    events = [_event_row({}), _event_row({'event_id': 'e2', 'timestamp': 'not-a-time'},
                                         fingerprint='bad')]
    bundle = load_bundle(_make_zip(tmp_path, sessions=[_session_row()], events=events,
                                   manifest={'filters': {}, 'counts': {}}))
    assert len(bundle.events) == 1
    assert any('跳过 1 条' in w for w in bundle.warnings)


def test_package_without_manifest_is_rejected(tmp_path):
    target = tmp_path / 'broken.zip'
    with zipfile.ZipFile(target, 'w') as zf:
        zf.writestr('sessions.csv', SESSION_HEADER)
        zf.writestr('events.csv', EVENT_HEADER)
    with pytest.raises(SourceError, match='manifest.json'):
        load_bundle(target)


def test_directory_source_is_supported(tmp_path):
    folder = tmp_path / 'unzipped'
    folder.mkdir()
    _make_zip(tmp_path, sessions=[_session_row()], events=[_event_row({})])
    with zipfile.ZipFile(tmp_path / 'agenttrail-test.zip') as zf:
        zf.extractall(folder)
    bundle = load_bundle(folder)
    assert len(bundle.sessions) == 1


def test_missing_path_is_rejected(tmp_path):
    with pytest.raises(SourceError, match='不存在'):
        load_bundle(tmp_path / 'nope.zip')
