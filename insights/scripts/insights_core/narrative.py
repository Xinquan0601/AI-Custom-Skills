"""叙事层：narratives.json 的结构契约与证据校验。

LLM 负责写内容，脚本负责说清楚「哪里不符合契约」：
- 结构错误（版本不符 / 顶层缺失 / 类型不对）直接阻断渲染；
- 内容警告（空字段 / 疑似编造的 source）打印出来但照常出报告。
契约见 docs/narratives-schema.md。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .constants import SCHEMA_VERSION

_NUMBER_TOKEN = re.compile(r'(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(亿|万|%)?')


class NarrativeError(ValueError):
    """叙事文件不符合结构契约，不能进入渲染。"""


REQUIRED_SECTIONS = ('overview', 'project_areas', 'interaction_style',
                     'what_works', 'friction_analysis', 'suggestions',
                     'on_the_horizon', 'fun_ending')

OVERVIEW_KEYS = ('whats_working', 'whats_hindering', 'quick_wins',
                 'ambitious_workflows')


def load(path: str | Path) -> dict:
    target = Path(path)
    if not target.is_file():
        raise NarrativeError(f'叙事文件不存在：{target}')
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise NarrativeError(f'叙事文件不是合法 JSON：{exc}') from exc
    if not isinstance(data, dict):
        raise NarrativeError('叙事文件的顶层必须是对象')
    return data


def assert_schema(narratives: dict) -> None:
    """结构不对就抛 NarrativeError，附带可直接照做的修法。"""
    version = narratives.get('schema_version')
    if version != SCHEMA_VERSION:
        raise NarrativeError(
            f'narratives.schema_version 必须是 {SCHEMA_VERSION}，当前是 {version!r}；'
            f'请按 docs/narratives-schema.md 重写')
    missing = [key for key in REQUIRED_SECTIONS if key not in narratives]
    if missing:
        raise NarrativeError(
            f'narratives 缺顶层区块：{", ".join(missing)}；'
            f'必填区块见 docs/narratives-schema.md')
    for key in REQUIRED_SECTIONS:
        if not isinstance(narratives[key], dict):
            raise NarrativeError(f'narratives.{key} 必须是对象')


def _number_texts(narratives: dict) -> list[str]:
    """叙事里所有文字（跳过 source：那是数据定位串，不是结论）。"""
    texts: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'source':
                    continue
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            texts.append(node)

    walk(narratives)
    return texts


def _numbers_in_documents(*documents) -> tuple[set[str], list[float]]:
    tokens: set[str] = set()
    values: list[float] = []

    def add(number) -> None:
        if isinstance(number, str):
            for token in re.findall(r'\d+', number):
                tokens.add(token)
            return
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            return
        value = float(number)
        values.append(value)
        tokens.add(f'{value:g}')
        tokens.add(f'{value:.1f}')
        tokens.add(f'{value:.2f}')
        if value == int(value):
            tokens.add(str(int(value)))
            tokens.add(f'{int(value):,}')

    def walk(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        else:
            add(node)

    for document in documents:
        walk(document)
    return tokens, values


def _ratio_permille(values: list[float]) -> set[float]:
    """任意两项的百分比比值；用来放行「闭环率 11.7%」这类派生数字。"""
    ratios: set[float] = set()
    numbers = [v for v in values if v >= 0]
    for part in numbers:
        for total in numbers:
            if total >= 10 and part <= total:
                ratios.add(round(part / total * 100, 1))
    return ratios


def validate_numbers(narratives: dict, stats: dict, facets: dict | None = None) -> list[str]:
    """抽查叙事里的数字能否在 stats/facets 找到来源；只查「够大」的数字，避免误报。"""
    tokens, values = _numbers_in_documents(stats, facets or {})
    ratios = _ratio_permille(values)
    warnings: list[str] = []
    seen: set[str] = set()
    for text in _number_texts(narratives):
        for match in _NUMBER_TOKEN.finditer(text):
            raw, unit = match.group(1), match.group(2) or ''
            number = float(raw.replace(',', ''))
            label = f'{raw}{unit}'
            if label in seen:
                continue
            if unit == '%':
                ok = (any(abs(value - number / 100) <= 0.006 for value in values if 0 < value <= 1)
                      or any(abs(ratio - number) <= 0.6 for ratio in ratios))
            elif unit == '亿':
                ok = any(abs(value - number * 1e8) <= max(1.0, number * 1e8 * 0.02) for value in values)
            elif unit == '万':
                ok = any(abs(value - number * 1e4) <= max(1.0, number * 1e4 * 0.02) for value in values)
            else:
                if number < 100:
                    continue
                if raw in tokens or f'{number:g}' in tokens:
                    ok = True
                else:
                    ok = any(abs(value - number) <= max(0.5, number * 0.001) for value in values)
            if not ok:
                seen.add(label)
                warnings.append(f'疑似编造的数字「{label}」：stats / facets 里找不到来源')
    return warnings


def validate_content(narratives: dict, stats: dict, facets: dict | None = None) -> list[str]:
    """返回内容层面的警告（不阻断渲染）。"""
    warnings: list[str] = []
    overview = narratives.get('overview') or {}
    for key in OVERVIEW_KEYS:
        if not str(overview.get(key) or '').strip():
            warnings.append(f'overview.{key} 为空，报告总览会少一条')

    if not _areas(narratives):
        warnings.append('project_areas.areas 为空，「你都在做什么」区块会被跳过')
    if not str((narratives.get('interaction_style') or {}).get('narrative') or '').strip():
        warnings.append('interaction_style.narrative 为空，「你怎么用 AI」区块会被跳过')
    if not _items(narratives, 'what_works', 'impressive_workflows'):
        warnings.append('what_works.impressive_workflows 为空，「你的亮点」区块会被跳过')
    if not _items(narratives, 'friction_analysis', 'categories'):
        warnings.append('friction_analysis.categories 为空，「问题出在哪」区块会被跳过')
    if not _suggestions(narratives):
        warnings.append('suggestions 为空，「值得尝试」区块会被跳过')
    if not _items(narratives, 'on_the_horizon', 'opportunities'):
        warnings.append('on_the_horizon.opportunities 为空，「展望」区块会被跳过')

    warnings.extend(_source_warnings(narratives, stats))
    warnings.extend(validate_numbers(narratives, stats, facets))
    return warnings


def _areas(narratives: dict) -> list:
    return ((narratives.get('project_areas') or {}).get('areas') or [])


def _items(narratives: dict, section: str, key: str) -> list:
    return ((narratives.get(section) or {}).get(key) or [])


def _suggestions(narratives: dict) -> list:
    suggestions = narratives.get('suggestions') or {}
    return list(suggestions.get('agents_md_additions') or []) + list(
        suggestions.get('features_to_try') or [])


def _valid_evidence(stats: dict) -> tuple[set[str], list[str]]:
    ids: set[str] = set()
    texts: list[str] = []
    for session in stats.get('sessions') or []:
        sid = str(session.get('id') or '')
        if sid:
            ids.add(sid[:8])
        title = str(session.get('title') or '')
        if title:
            texts.append(title)
    material = stats.get('narrative_material') or {}
    for sample in material.get('session_samples') or []:
        sid = str(sample.get('session') or '')
        if sid:
            ids.add(sid[:8])
        for message in sample.get('messages') or []:
            if message:
                texts.append(str(message))
    return ids, texts


def _source_warnings(narratives: dict, stats: dict) -> list[str]:
    ids, texts = _valid_evidence(stats)
    suspects: list[str] = []

    def check(source: str | None, label: str) -> None:
        text = str(source or '').strip()
        if not text:
            return
        if text[:8] in ids or any(text in candidate for candidate in texts):
            return
        suspects.append(f'{label}: {text[:60]}…')

    for index, item in enumerate(_items(narratives, 'what_works', 'impressive_workflows')):
        check(item.get('source'), f'what_works[{index}].source')
    for index, item in enumerate(_items(narratives, 'friction_analysis', 'categories')):
        check(item.get('source'), f'friction_analysis[{index}].source')
    return [f'[warn] 疑似编造的引用 {item}' for item in suspects]
