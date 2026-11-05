"""语义层（facets）：把「实质会话」变成结构化判断，供聚合与写作使用。

分层原则：
- 事实层（stats.json）只记事件与可复算的计数，本模块不参与；
- 语义层（facets.json）记模型判断，每条都必须带 evidence（逐字出自 digest），
  并披露覆盖率——没提取到的会话不会被当成「没问题」。

数据源无关：digest 由 Bundle / SessionMetrics 生成，六种 Agent 同一套字段。

流程（CLI 见 insights_report.py）：
    facet plan  -> tasks.json（确定性 digest + 提取提示词 + 缓存键）
    （LLM 按 tasks 产出 results.json）
    facet merge -> facets.json（校验 + 去伪 + 聚合摘要）
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    TOOL_RESULT_ERROR_STATUSES,
    utc_offset,
)
from .model import Event, SessionMetrics, local_iso, strip_error_banner, truncate

FACETS_SCHEMA_VERSION = 1
MAX_TASKS = 200
DIGEST_MESSAGE_CHARS = 320
DIGEST_REPLY_CHARS = 180
DIGEST_FINAL_CHARS = 240
DIGEST_HEAD_MESSAGES = 3
DIGEST_TAIL_MESSAGES = 2
MAX_EVIDENCE = 3
MAX_INSTRUCTIONS = 3
MAX_SUMMARY_CHARS = 80

# 导出包里混进来的「伪消息」：摘要续写、工具回填、继续指令，对语义判断没有信息量。
_NOISE_PATTERNS = (
    'please continue with the conversation',
    'maintain the same level of detail',
    'continue from where you left off',
    '请继续执行任务',
    '继续执行任务',
    '<send_user_message_question_reply>',
    '<long_text_quote>',
    '<conversation_history_summary>',
)

# 分类表按用户真实数据长出来（关键词预分桶覆盖 74%，其余交给语义判断）。
GOAL_CATEGORIES: dict[str, str] = {
    'fw_defect': '固件缺陷排查',
    'hw_interface': '硬件接口与设备树',
    'comm_protocol': '通信协议调试',
    'arch_review': '架构审查与调研',
    'design_doc': '设计与技术文档',
    'customer_delivery': '客户交付与汇报材料',
    'vision_analysis': '视觉与视频分析',
    'tooling_env': '工具链与环境',
    'req_clarify': '需求澄清与方案',
    'data_curation': '数据整理与沉淀',
}

OUTCOMES: dict[str, str] = {
    'closed': '闭环（目标达成且有验证）',
    'mostly': '基本闭环（主体完成，遗留小事）',
    'partial': '部分达成（只解决了一部分）',
    'open': '未达成（停在半路或换了方案）',
}

FRICTION_TYPES: dict[str, str] = {
    'silent_error': '报错无正文，无法定位',
    'incomplete': '结果未完成就停下',
    'drift': '长任务跑偏 / 遗忘约束',
    'structure': '生成物结构或格式不对',
    'edit_conflict': '改动冲突 / 覆盖了已有内容',
    'overstep': '超出授权范围或擅自扩大改动',
    'other': '其他摩擦',
}

SATISFACTION_SIGNALS: dict[str, tuple[str, ...]] = {
    'positive': ('继续', '可以', '没问题', '完美', '不错', '对了', '就这样', '很好', 'ok', 'okay', 'good'),
    'negative': ('不对', '错了', '不是这样', '重来', '不行', '还是不行', '又错', '搞错', '为什么还是'),
}

REQUIRED_RESULT_KEYS = ('session_id', 'goal_category', 'outcome', 'summary', 'evidence')


class FacetsError(RuntimeError):
    """输入不符合 facets 契约。"""


@dataclass
class Digest:
    """一个会话喂给模型的全部上下文（不含原始事件、不含整段对话）。"""
    session_id: str
    agent: str
    project: str
    title: str
    started_local: str
    ended_local: str
    duration_minutes: int
    user_messages: int
    assistant_messages: int
    tool_calls: int
    files: list[str]
    lines_added: int
    lines_removed: int
    git_commits: int
    errors: int
    incomplete: int
    error_categories: list[str]
    error_samples: list[str]
    messages: list[str]
    turns: list[dict[str, str]]
    final_assistant: str
    final_assistant_at: str
    tools: list[str]
    signals: dict[str, int]
    content_hash: str = ''
    cache_key: str = ''

    def as_dict(self) -> dict[str, Any]:
        return {
            'session_id': self.session_id,
            'agent': self.agent,
            'project': self.project,
            'title': self.title,
            'started_local': self.started_local,
            'ended_local': self.ended_local,
            'duration_minutes': self.duration_minutes,
            'user_messages': self.user_messages,
            'assistant_messages': self.assistant_messages,
            'tool_calls': self.tool_calls,
            'files': self.files,
            'lines': {'added': self.lines_added, 'removed': self.lines_removed},
            'git_commits': self.git_commits,
            'errors': self.errors,
            'incomplete': self.incomplete,
            'error_categories': self.error_categories,
            'error_samples': self.error_samples,
            'user_messages_text': self.messages,
            'turns': self.turns,
            'final_assistant': self.final_assistant,
            'final_assistant_at': self.final_assistant_at,
            'tools': self.tools,
            'signals': self.signals,
        }


def _normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '')).strip().lower()


def cache_key(digest: Digest) -> str:
    """会话内容变了就失效：会话 id + 消息数 + 工具数 + 最后一条消息 + schema 版本。"""
    payload = '|'.join([
        str(FACETS_SCHEMA_VERSION), digest.session_id, str(digest.user_messages),
        str(digest.tool_calls), digest.content_hash,
        '|'.join(sorted(GOAL_CATEGORIES)),
    ])
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


def _pick_indexes(total: int) -> list[int]:
    if total <= DIGEST_HEAD_MESSAGES + DIGEST_TAIL_MESSAGES:
        return list(range(total))
    picked: list[int] = []
    for index in list(range(DIGEST_HEAD_MESSAGES)) + list(range(total - DIGEST_TAIL_MESSAGES, total)):
        if index not in picked:
            picked.append(index)
    return picked


def _compact_path(path: str) -> str:
    """去掉用户名与盘符，只留项目内相对路径，避免把本机路径带进 digest。"""
    text = (path or '').replace('\\', '/').strip()
    lowered = text.lower()
    for marker in ('/desktop/project-win/', '/desktop/', '/documents/'):
        index = lowered.find(marker)
        if index >= 0:
            text = text[index + len(marker):]
            break
    else:
        match = re.match(r'^[a-z]:/users/[^/]+/', text, re.I)
        if match:
            text = '~/' + text[match.end():]
    parts = [part for part in text.split('/') if part]
    if len(parts) > 3:
        text = '…/' + '/'.join(parts[-3:])
    return text


def _is_noise(text: str) -> bool:
    lowered = (text or '').strip().lower()
    return not lowered or any(lowered.startswith(pattern) for pattern in _NOISE_PATTERNS)


def _dedupe_indexed(items: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """去掉空消息，并把「同一句话又发一遍、后面追加了问题」合并成较长的那条。"""
    kept: list[tuple[int, str]] = []
    for index, message in items:
        if _is_noise(message) or len(message.strip()) < 2:
            continue
        current = message.strip()
        last = kept[-1][1].strip() if kept else ''
        if last and (current.startswith(last) or last.startswith(current)
                     or current[:80] == last[:80]):
            if len(current) > len(last):
                kept[-1] = (index, message)
            continue
        kept.append((index, message))
    return kept


def _dedupe_messages(messages: list[str]) -> list[str]:
    return [text for _, text in _dedupe_indexed(list(enumerate(messages)))]


def _is_meta_reply(text: str) -> bool:
    """导出包里混进来的「思考过程」不是回复：判结果时只会误导。"""
    head = (text or '').strip().lower()
    return head.startswith(('the user ', "the user's", 'we need', 'let me ', 'let\'s ',
                            'i need to ', 'the assistant ', 'the repo ', 'looking at ',
                            'now key', '## task and constraints'))


def _dedupe_user_events(events: list[Event]) -> list[Event]:
    """同一条用户消息在导出包里可能重复（相隔几十毫秒），按内容去重。"""
    seen: set[str] = set()
    unique: list[Event] = []
    for event in events:
        key = _normalize(event.content)[:200]
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def _merge_tools(counter: Counter) -> list[str]:
    """Bash / bash 合并成一个计数，避免 digest 里同一工具出现两次。"""
    merged: dict[str, list] = {}
    for name, count in counter.items():
        key = name.lower()
        entry = merged.setdefault(key, [0, name, Counter()])
        entry[0] += count
        entry[2][name] += count
    ordered = sorted(merged.values(), key=lambda item: -item[0])
    return [f'{item[2].most_common(1)[0][0]}×{item[0]}' for item in ordered[:6]]


def _signals(messages: Iterable[str]) -> dict[str, int]:
    counts = {'positive': 0, 'negative': 0}
    for text in messages:
        lowered = text.lower()
        for kind, words in SATISFACTION_SIGNALS.items():
            if any(word in lowered for word in words):
                counts[kind] += 1
    return counts


def build_digest(metrics: SessionMetrics, events: list[Event]) -> Digest:
    """用会话指标 + 原始事件拼出 digest；同一份数据永远得到同一份 digest。

    每条用户消息都配一条「紧随其后的 Agent 回复」：没有回复内容，就分不清是
    「用户说完了」还是「Agent 跑偏后用户又来纠正」，结果与摩擦只能靠猜。
    """
    ordered = sorted(events, key=lambda event: event.ts)
    real_users = _dedupe_user_events(
        [e for e in ordered if e.type == 'user_message' and not e.synthetic])
    user_texts = [truncate(e.content, DIGEST_MESSAGE_CHARS) for e in real_users]
    ordinal_by_event = {event.event_id: index for index, event in enumerate(real_users)}

    replies: dict[int, str] = {}
    final_assistant = ''
    final_assistant_at = ''
    pending: int | None = None
    for event in ordered:
        if event.type == 'user_message' and not event.synthetic:
            ordinal = ordinal_by_event.get(event.event_id)
            if ordinal is not None:          # 重复副本不改变当前指向
                pending = ordinal
        elif event.type == 'assistant_message':
            text = truncate(event.content, DIGEST_REPLY_CHARS).strip()
            if not text or _is_meta_reply(text):
                continue
            final_assistant = truncate(event.content, DIGEST_FINAL_CHARS).strip()
            final_assistant_at = local_iso(event.ts, utc_offset())
            if pending is not None:
                replies[pending] = text   # 覆盖：一轮里最后一条才是给用户的回复

    kept = _dedupe_indexed(list(enumerate(user_texts)))
    picked = [kept[index] for index in _pick_indexes(len(kept))]
    turns = [{'user': text, 'reply': replies.get(index, '')} for index, text in picked]
    errors = [e for e in events
              if e.type == 'tool_result'
              and (e.tool_status or '').lower() in TOOL_RESULT_ERROR_STATUSES]
    samples: list[str] = []
    for event in errors:
        text = truncate(strip_error_banner(event.content), 160)
        if text and text not in samples:
            samples.append(text)
        if len(samples) >= 3:
            break
    digest = Digest(
        session_id=metrics.session_id,
        agent=metrics.agent,
        project=metrics.project,
        title=metrics.title,
        started_local=local_iso(metrics.started_at, utc_offset()),
        ended_local=local_iso(metrics.ended_at, utc_offset()),
        duration_minutes=metrics.duration_minutes,
        user_messages=len(real_users),
        assistant_messages=metrics.assistant_messages,
        tool_calls=metrics.tool_calls,
        files=[_compact_path(path) for path in sorted(metrics.files_touched)[:8]],
        lines_added=metrics.lines_added,
        lines_removed=metrics.lines_removed,
        git_commits=metrics.git_commits,
        errors=metrics.errors,
        incomplete=metrics.incomplete,
        error_categories=[f'{label}×{count}'
                          for label, count in metrics.error_categories.most_common(3)],
        error_samples=samples,
        messages=[text for _, text in picked],
        turns=turns,
        final_assistant=final_assistant,
        final_assistant_at=final_assistant_at,
        tools=_merge_tools(metrics.tool_name_counts),
        signals=_signals(user_texts),
    )
    fingerprint = user_texts + [replies[key] for key in sorted(replies)] + [final_assistant]
    digest.content_hash = hashlib.sha256('\n'.join(fingerprint).encode('utf-8')).hexdigest()[:16]
    digest.cache_key = cache_key(digest)
    return digest


def system_prompt() -> str:
    categories = '\n'.join(f'  - {key}: {label}' for key, label in GOAL_CATEGORIES.items())
    outcomes = '\n'.join(f'  - {key}: {label}' for key, label in OUTCOMES.items())
    frictions = '\n'.join(f'  - {key}: {label}' for key, label in FRICTION_TYPES.items())
    return (
        '你在给一份 AI 使用洞察报告做「会话维度提取」。输入是一段会话 digest，'
        '输出一个 JSON 对象，不要任何解释。\n\n'
        '规则：\n'
        '1. 只按用户明确发起的意图分类，不要把 Agent 自主探索当成用户任务；\n'
        '2. 判断依据只来自 digest：title / turns / final_assistant / files / tools / errors；\n'
        '   turns 是「用户这一句 + Agent 紧随其后的回复」，用它判断是理解了还是在试错；\n'
        f'3. evidence 给 1-{MAX_EVIDENCE} 条，必须逐字出自 digest 原文（中文原样），'
        '不得改写、不得编造；\n'
        '4. outcome 必须能指出依据：用户后续确认/催改（turns 后几条）、末条 final_assistant\n'
        '   的自述（完成/已提交/还剩什么）、客观信号（incomplete、git_commits、errors）。\n'
        '   只有「我改好了」而没有验证或用户回应，最多判 mostly；三样都没有，判 partial，不许判 closed；\n'
        '5. summary 不超过 60 字，说清「用户想做什么、做到哪一步」；\n'
        '6. instructions 只收用户明确给出的约束（如「改完跑测试」），没有就给 []；\n'
        '7. 数字只允许引用 digest 里已有的，不要自己算。\n\n'
        '字段与取值：\n'
        f'  goal_category: 从下列 key 选一个\n{categories}\n'
        f'  outcome: 从下列 key 选一个\n{outcomes}\n'
        f'  friction: 0-3 个 key 的数组\n{frictions}\n'
        '  helpfulness: 0-4 的整数（0=帮倒忙，4=关键一步是它做的）\n'
        '  satisfaction: positive / negative / neutral\n\n'
        '输出格式：\n'
        '{"session_id":"...","goal_category":"...","outcome":"...",'
        '"friction":["..."],"helpfulness":3,"satisfaction":"positive",'
        '"summary":"...","evidence":["..."],"instructions":["..."]}'
    )


def user_prompt(digest: Digest) -> str:
    return json.dumps(digest.as_dict(), ensure_ascii=False, indent=1)


def build_plan(sessions: list[SessionMetrics], events_by_session: dict[tuple[str, str], list[Event]],
               limit: int = MAX_TASKS, only: Iterable[str] | None = None) -> dict[str, Any]:
    """把实质会话排成提取任务；快速问答不提取，超限按最近活跃度取前 limit 个。"""
    wanted = set(only or [])
    candidates = [s for s in sessions if s.substantive and s.user_messages > 0]
    if wanted:
        candidates = [s for s in candidates if s.session_id in wanted]
    candidates.sort(key=lambda s: s.started_at or s.ended_at or 0, reverse=True)  # type: ignore[arg-type]
    warnings: list[str] = []
    if len(candidates) > limit:
        dropped = len(candidates) - limit
        warnings.append(f'实质会话 {len(candidates)} 个，超过上限 {limit}，只提取最近 {limit} 个'
                        f'（{dropped} 个未覆盖，报告需披露）')
        candidates = candidates[:limit]
    tasks = []
    for metrics in candidates:
        events = events_by_session.get((metrics.agent, metrics.session_id), [])
        digest = build_digest(metrics, events)
        tasks.append({
            'session_id': digest.session_id,
            'cache_key': digest.cache_key,
            'digest': digest.as_dict(),
            'prompt': {'system': system_prompt(), 'user': user_prompt(digest)},
        })
    quick = sum(1 for s in sessions if not s.substantive)
    return {
        'schema_version': FACETS_SCHEMA_VERSION,
        'categories': GOAL_CATEGORIES,
        'outcomes': OUTCOMES,
        'frictions': FRICTION_TYPES,
        'totals': {'sessions': len(sessions), 'substantive': sum(1 for s in sessions if s.substantive),
                   'quick': quick, 'tasks': len(tasks)},
        'warnings': warnings,
        'tasks': tasks,
    }


def load_tasks(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema_version') != FACETS_SCHEMA_VERSION:
        raise FacetsError(f'tasks schema_version 不是 {FACETS_SCHEMA_VERSION}')
    if not isinstance(data.get('tasks'), list):
        raise FacetsError('tasks 缺失或不是数组')
    return data


def load_results(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    items = data.get('results') if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise FacetsError('results 必须是数组，或 {"results": [...]}')
    return [item for item in items if isinstance(item, dict)]


def _digest_text(digest: dict[str, Any]) -> str:
    turns = digest.get('turns') or []
    parts = [
        digest.get('title', ''), digest.get('project', ''),
        ' '.join(digest.get('user_messages_text') or []),
        ' '.join(str(turn.get('reply') or '') for turn in turns if isinstance(turn, dict)),
        str(digest.get('final_assistant') or ''),
    ]
    return _normalize(' '.join(parts))


def _check_record(record: dict[str, Any], tasks_by_id: dict[str, dict[str, Any]]) -> list[str]:
    problems = []
    session_id = str(record.get('session_id') or '')
    if session_id not in tasks_by_id:
        return [f'{session_id or "（空）"}: 不在任务列表里']
    for key in REQUIRED_RESULT_KEYS:
        if record.get(key) in (None, '', []):
            problems.append(f'{session_id}: 缺字段 {key}')
    category = record.get('goal_category')
    if category and category not in GOAL_CATEGORIES:
        problems.append(f'{session_id}: goal_category 不在枚举里（{category}）')
    outcome = record.get('outcome')
    if outcome and outcome not in OUTCOMES:
        problems.append(f'{session_id}: outcome 不在枚举里（{outcome}）')
    for friction in record.get('friction') or []:
        if friction not in FRICTION_TYPES:
            problems.append(f'{session_id}: friction 不在枚举里（{friction}）')
    digest = tasks_by_id[session_id]['digest']
    body = _digest_text(digest)
    for item in record.get('evidence') or []:
        if _normalize(str(item)) and _normalize(str(item)) not in body:
            problems.append(f'{session_id}: evidence 未在 digest 中逐字出现（{truncate(str(item), 24)}）')
    if len(record.get('instructions') or []) > MAX_INSTRUCTIONS:
        problems.append(f'{session_id}: instructions 超过 {MAX_INSTRUCTIONS} 条')
    if len(str(record.get('summary') or '')) > MAX_SUMMARY_CHARS:
        problems.append(f'{session_id}: summary 超过 {MAX_SUMMARY_CHARS} 字')
    return problems


def _session_fingerprint(digest: dict[str, Any]) -> tuple[str, ...]:
    """同一会话可能被多个客户端各导出一份：用「项目 + 用户发言序列」认亲。"""
    turns = digest.get('turns') or []
    users = tuple(_normalize(str(turn.get('user') or ''))
                  for turn in turns if isinstance(turn, dict))
    if users:
        return (str(digest.get('project') or ''), *users)
    return (str(digest.get('project') or ''), _normalize(str(digest.get('title') or '')))


def merge_results(plan: dict[str, Any], results: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """校验并聚合；坏记录不静默吞掉，全部进 warnings。"""
    tasks_by_id = {task['session_id']: task for task in plan.get('tasks') or []}
    warnings: list[str] = []
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in results:
        session_id = str(record.get('session_id') or '')
        if session_id in seen:
            warnings.append(f'{session_id}: 重复结果，只保留第一条')
            continue
        problems = _check_record(record, tasks_by_id)
        if problems:
            warnings.extend(problems)
            continue
        seen.add(session_id)
        accepted.append({
            'session_id': session_id,
            'cache_key': tasks_by_id[session_id].get('cache_key', ''),
            'goal_category': record.get('goal_category'),
            'outcome': record.get('outcome'),
            'friction': list(record.get('friction') or []),
            'helpfulness': record.get('helpfulness'),
            'satisfaction': record.get('satisfaction') or 'neutral',
            'summary': str(record.get('summary') or ''),
            'evidence': list(record.get('evidence') or []),
            'instructions': list(record.get('instructions') or []),
        })
    unique: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    duplicates: list[str] = []
    for record in accepted:
        digest = tasks_by_id[record['session_id']]['digest']
        fingerprint = _session_fingerprint(digest)
        keeper = positions.get(fingerprint)
        if keeper is None:
            positions[fingerprint] = len(unique)
            unique.append(record)
            continue
        duplicates.append(record['session_id'])
        if len(record['session_id']) < len(unique[keeper]['session_id']):
            unique[keeper] = record
    if duplicates:
        warnings.append(f'{len(duplicates)} 条结果与另一会话的用户发言完全相同（多客户端重复导出），'
                        f'已按同一会话合并：{", ".join(sorted(duplicates)[:5])}'
                        + (' 等' if len(duplicates) > 5 else ''))
    accepted = unique
    unique_tasks = len({_session_fingerprint(task['digest'])
                        for task in tasks_by_id.values()})
    coverage = {
        'tasks': len(tasks_by_id),
        'unique_tasks': unique_tasks,
        'accepted': len(accepted),
        'duplicates_merged': len(duplicates),
        'missing': max(unique_tasks - len(accepted), 0),
        'evidence_pass': sum(1 for r in accepted if r['evidence']),
    }
    categories = Counter(r['goal_category'] for r in accepted)
    outcomes = Counter(r['outcome'] for r in accepted)
    frictions = Counter(f for r in accepted for f in r['friction'])
    instructions = Counter(i.strip() for r in accepted for i in r['instructions'] if i.strip())
    documents = {
        'schema_version': FACETS_SCHEMA_VERSION,
        'coverage': coverage,
        'facets': accepted,
        'summary': {
            'by_category': {k: categories.get(k, 0) for k in GOAL_CATEGORIES},
            'by_outcome': {k: outcomes.get(k, 0) for k in OUTCOMES},
            'by_friction': {k: frictions.get(k, 0) for k in FRICTION_TYPES},
            'instructions': [{'text': text, 'sessions': count}
                             for text, count in instructions.most_common(10)],
            'coverage_ratio': round(len(accepted) / unique_tasks, 3) if unique_tasks else 0.0,
        },
    }
    if coverage['missing']:
        warnings.append(f'{coverage["missing"]}/{unique_tasks} 个会话没有提取结果，'
                        f'报告只能覆盖 {coverage["accepted"]} 个')
    return documents, warnings
