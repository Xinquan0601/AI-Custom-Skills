"""测试夹具：直接构造 Bundle，避免依赖真实导出包。"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from insights_core.model import Event, SessionMeta  # noqa: E402
from insights_core.sources.base import Bundle  # noqa: E402
from insights_core.window import compute_window  # noqa: E402

WINDOW_START = '2026-10-29T16:00:00Z'
WINDOW_END = '2026-11-05T15:59:59.999Z'


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)


def make_event(*, agent='dsh', session_id='s1', type='user_message',
               ts='2026-10-30T02:00:00Z', content='', tool_name='',
               tool_call_id='', tool_status='', tool_input=None,
               synthetic=False) -> Event:
    return Event(
        event_id=f'{session_id}-{ts}-{tool_call_id}',
        agent=agent,
        session_id=session_id,
        type=type,
        ts=utc(ts),
        content=content,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_status=tool_status,
        tool_input=tool_input or {},
        model='deepseek-v4',
        synthetic=synthetic,
    )


def make_meta(*, agent='dsh', session_id='s1', title='会话一', project='insights',
              cwd='D:\\prj\\insights', model='deepseek-v4',
              started='2026-10-30T02:00:00Z', ended='2026-10-30T02:30:00Z',
              user_messages=2, tool_calls=1, tokens=(100, 50)) -> SessionMeta:
    return SessionMeta(
        agent=agent,
        session_id=session_id,
        title=title,
        project=project,
        model=model,
        cwd=cwd,
        started_at=utc(started),
        ended_at=utc(ended),
        message_count=user_messages * 2,
        user_message_count=user_messages,
        assistant_message_count=user_messages,
        tool_call_count=tool_calls,
        tool_result_count=tool_calls,
        event_count=user_messages * 2 + tool_calls * 2,
        tokens_input=tokens[0],
        tokens_output=tokens[1],
    )


def build_bundle() -> Bundle:
    """两个 Agent、三个会话：两个实质会话 + 一个快速问答。"""
    events = [
        # s1：实质会话，含一次报错的 run_code 和一次 edit
        make_event(ts='2026-10-30T02:00:00Z', content='先读一下 render 的模板结构'),
        make_event(type='assistant_message', ts='2026-10-30T02:00:20Z', content='好'),
        make_event(type='tool_call', ts='2026-10-30T02:01:00Z', content='git commit -m x',
                   tool_name='bash', tool_call_id='c1',
                   tool_input={'command': 'git commit -m "x"'}),
        make_event(type='tool_result', ts='2026-10-30T02:01:05Z',
                   content='File sandbox: SetNamedSecurityInfoW failed (Win32: 5)',
                   tool_name='bash', tool_call_id='c1', tool_status='error'),
        make_event(type='tool_call', ts='2026-10-30T02:02:00Z', tool_name='edit',
                   tool_call_id='c2', tool_input={'path': r'D:\prj\insights\a.py',
                                                  'old_string': 'a\nb\n', 'new_string': 'a\nb\nc\n'}),
        make_event(type='tool_result', ts='2026-10-30T02:02:02Z', content='ok',
                   tool_name='edit', tool_call_id='c2', tool_status='ok'),
        make_event(ts='2026-10-30T02:05:00Z', content='把这段拆成模块'),
        make_event(type='assistant_message', ts='2026-10-30T02:05:30Z', content='好'),
        # s1 里混入一条伪用户消息，统计时应被剔除
        make_event(ts='2026-10-30T02:06:00Z',
                   content='Time sampled while preparing turn 3', synthetic=True),
        # s2：快速问答（只有 1 条用户消息）
        make_event(agent='wb', session_id='s2', ts='2026-10-31T03:00:00Z',
                   content='帮我把这个表格转成 markdown'),
        make_event(agent='wb', session_id='s2', type='assistant_message',
                   ts='2026-10-31T03:00:30Z', content='好'),
        # s3：跨到 11-02 的实质会话
        make_event(agent='oc', session_id='s3', ts='2026-11-02T01:00:00Z',
                   content='检查一下 USB 枚举日志'),
        make_event(agent='oc', session_id='s3', type='tool_call', ts='2026-11-02T01:01:00Z',
                   content='grep usb', tool_name='run_code', tool_call_id='c9',
                   tool_input={'code': 'grep usb dmesg'}),
        make_event(agent='oc', session_id='s3', type='tool_result',
                   ts='2026-11-02T01:01:02Z', content='usb 1-1: new device',
                   tool_name='run_code', tool_call_id='c9', tool_status='ok'),
        make_event(agent='oc', session_id='s3', ts='2026-11-02T01:10:00Z',
                   content='继续看供电'),
        make_event(agent='oc', session_id='s3', type='assistant_message',
                   ts='2026-11-02T01:10:30Z', content='好'),
    ]
    sessions = [
        make_meta(session_id='s1', title='拆报告模块', project='insights',
                  cwd=r'D:\prj\insights', user_messages=2, tool_calls=2),
        make_meta(agent='wb', session_id='s2', title='表格转 markdown',
                  project='DV454 周报', cwd=r'D:\prj\dv454',
                  started='2026-10-31T03:00:00Z', ended='2026-10-31T03:01:00Z',
                  user_messages=1, tool_calls=0, tokens=(0, 0)),
        make_meta(agent='oc', session_id='s3', title='USB 枚举排查',
                  project='RK3576', cwd=r'D:\prj\rk3576',
                  started='2026-11-02T01:00:00Z', ended='2026-11-02T01:20:00Z',
                  user_messages=2, tool_calls=1, tokens=(300, 120)),
    ]
    bundle = Bundle(
        kind='agenttrail',
        path=Path('fixture.zip'),
        window_start_utc=WINDOW_START,
        window_end_utc=WINDOW_END,
        export_version='test',
        generated_at='2026-11-05T09:24:20Z',
        counts={'sessions': 3, 'events': len(events)},
        warnings=['fixture warning'],
        sessions=sessions,
        events=events,
    )
    return bundle


@pytest.fixture()
def bundle() -> Bundle:
    return build_bundle()


@pytest.fixture()
def window():
    from datetime import date
    return compute_window(bundle_since=date(2026, 10, 30), bundle_until=date(2026, 11, 5))
