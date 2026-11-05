"""渲染层：视图模型 + 模板 → 单文件离线 HTML。

对外只暴露两个函数：render_html() 出字符串，write_report() 落盘并返回路径。
"""
from __future__ import annotations

from pathlib import Path

from . import sections, view_model

TEMPLATE_DIR = Path(__file__).parent / 'templates'


def _asset(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding='utf-8')


def render_html(stats: dict, narratives: dict, comparison,
                facets_doc: dict | None = None) -> str:
    view = view_model.build(stats, narratives, comparison, facets_doc)
    shell = _asset('report.html')
    return (shell
            .replace('{{TITLE}}', f'AI 使用洞察报告 · {view["window_label"]}')
            .replace('{{CSS}}', _asset('report.css'))
            .replace('{{BODY}}', sections.render_body(view))
            .replace('{{JS}}', _asset('report.js')))


def window_suffix(window: dict | None) -> str:
    """把窗口起止日拼成文件名后缀：20261001-20261031。"""
    if not window:
        return ''
    since = str(window.get('since') or '').replace('-', '')
    until = str(window.get('until') or '').replace('-', '')
    return f'-{since}-{until}' if since and until else ''


def write_report(html_text: str, out_dir: str | Path, *, prefix: str = 'AI使用洞察报告',
                 window: dict | None = None) -> Path:
    """按报告窗口命名，永不覆盖已有报告（同名时追加 -2、-3）。"""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    label = f'{prefix}{window_suffix(window)}'
    target = directory / f'{label}.html'
    counter = 2
    while target.exists():
        target = directory / f'{label}-{counter}.html'
        counter += 1
    target.write_text(html_text, encoding='utf-8')
    return target
