"""insights_core：AI 使用洞察报告的领域层。

分层（依赖只能向下）：
- window.py    时间窗口：用户说法 + 导出窗口 → 确定区间
- model.py     数据结构与工具效果抽取（Event / SessionMeta / SessionMetrics）
- sources/     数据源适配：导出包 → Bundle
- metrics.py   单会话指标
- stats.py     全局聚合 → stats.json
- compare.py   环比：history 存档与差值
- narrative.py 叙事契约与证据校验
- render/      stats + narratives → 单文件 HTML

CLI 壳与参数解析在 scripts/insights_report.py。
"""
__all__ = ['compare', 'constants', 'metrics', 'model', 'narrative', 'render',
           'sources', 'stats', 'window']
