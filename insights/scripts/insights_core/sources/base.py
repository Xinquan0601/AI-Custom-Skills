"""数据源协议：读入一个导出包，产出统一的 Bundle。

统计层只认 Bundle（manifest + sessions + events + warnings），不认具体来源。
新增数据源 = 新写一个 load()，在 load_bundle() 里登记。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..model import Event, SessionMeta


class SourceError(RuntimeError):
    """数据源不可用或结构不符合契约。"""


@dataclass
class Bundle:
    """一次导入的完整数据。"""
    path: Path
    kind: str
    export_version: str
    generated_at: str
    window_start_utc: str
    window_end_utc: str
    sessions: list[SessionMeta] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    @property
    def agent_keys(self) -> list[str]:
        seen: dict[str, None] = {}
        for session in self.sessions:
            seen.setdefault(session.agent, None)
        return list(seen)


def load_bundle(path: str | Path) -> Bundle:
    """按路径形态选择适配器：.zip 或已解压目录都指向 AgentTrail 导出包。"""
    from .agenttrail import load

    target = Path(path).expanduser()
    if not target.exists():
        raise SourceError(f'数据源不存在：{target}')
    return load(target)
