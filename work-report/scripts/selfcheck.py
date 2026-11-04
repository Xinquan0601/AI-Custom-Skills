#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归自检：造一个最小数据包，跑通 collect -> 手写周报 -> render -> monthly。

  python scripts/selfcheck.py

只依赖标准库，不联网。全部断言通过返回 0，失败打印断点并返回 1。
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"

SESSIONS = [
    {
        "external_id": "s-work",
        "project": "prj-dv460",
        "cwd": r"D:\proj\rk3576-dv460-v2",
        "title": "rk3576 PCIe Gen2 建链验证",
        "started_at": "2026-10-28T02:00:00Z",
        "ended_at": "2026-10-28T03:00:00Z",
        "event_count": "4",
    },
    {
        "external_id": "s-other",
        "project": "scratch",
        "cwd": r"C:\tmp\notes",
        "title": "整理一下本机笔记",
        "started_at": "2026-10-29T02:00:00Z",
        "ended_at": "2026-10-29T02:30:00Z",
        "event_count": "2",
    },
]

EVENTS = [
    ("s-work", "2026-10-28T02:00:00Z", "user_message", "帮我确认 PCIe Gen2 的建链速率"),
    ("s-work", "2026-10-28T02:05:00Z", "assistant_message",
     "新建 Gen2 DTS 后成功建链 5.0GT/s，顺序读 429MB/s，顺序写 300MB/s，压测无掉线。"),
    ("s-work", "2026-10-28T02:30:00Z", "assistant_message",
     "已在 v3 板上复测，链路稳定在 5.0GT/s，没有出现 AER 报错。"),
    ("s-work", "2026-10-28T02:40:00Z", "user_message", "那顺序写呢"),
    ("s-other", "2026-10-29T02:00:00Z", "user_message", "整理一下本机笔记"),
    ("s-other", "2026-10-29T02:10:00Z", "assistant_message", "已按主题归档 12 条笔记。"),
]

WEEKLY = """# 工作周报 | 2026.10.27 - 2026.11.02

## DV460

- 完成PCIe Gen2 链路验证：新建 Gen2 DTS 成功建链 5.0GT/s，顺序读 429MB/s、顺序写 300MB/s，压测无掉线
"""


def write_bundle(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "sessions.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(SESSIONS[0]))
        w.writeheader()
        w.writerows(SESSIONS)
    with open(root / "events.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "session_id", "timestamp", "event_type", "role", "content", "fingerprint"])
        for i, (sid, ts, kind, content) in enumerate(EVENTS):
            w.writerow([f"e{i}", sid, ts, kind,
                        "user" if kind == "user_message" else "assistant",
                        content, f"{sid}-{i}"])
    (root / "manifest.json").write_text(json.dumps({"export": "selfcheck"}), encoding="utf-8")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, encoding="utf-8")


def main() -> int:
    fails: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    with tempfile.TemporaryDirectory(prefix="work-report-selfcheck-") as tmp:
        tmpdir = Path(tmp)
        bundle = tmpdir / "bundle"
        write_bundle(bundle)

        # 1) collect
        digest_path = tmpdir / "digest.json"
        r = run(str(SCRIPTS / "collect.py"), str(bundle),
                "--json", str(digest_path), "--transcripts", str(tmpdir / "素材"))
        check(r.returncode == 0, f"collect 失败：{r.stderr[-400:]}")
        digest = json.loads(digest_path.read_text(encoding="utf-8")) if digest_path.exists() else {"sessions": []}
        sessions = {s["title"]: s for s in digest.get("sessions", [])}
        work = sessions.get("rk3576 PCIe Gen2 建链验证", {})
        other = sessions.get("整理一下本机笔记", {})
        check(work.get("bucket") == "work", "任务会话没有归到 work")
        check(work.get("series") == "DV460", f"板号没有命中 DV460：{work.get('series')!r}")
        check(work.get("week") == "2026-10-27", f"周起始日应为周二 2026-10-27：{work.get('week')!r}")
        check(other.get("bucket") == "nonwork", "无法识别的内容没有落到非工作")
        check(other.get("group") == "其他", f"非工作兜底组应为 其他：{other.get('group')!r}")
        check(any(s.get("conclusions") for s in digest.get("sessions", [])), "没有抽出结论候选")

        # 2) 手写周报 + render
        reports = tmpdir / "reports"
        (reports / "周报").mkdir(parents=True)
        (reports / "周报" / "20261027-周报.md").write_text(WEEKLY, encoding="utf-8")
        r = run(str(SCRIPTS / "render.py"), str(reports), "--check", "--profile", "work")
        check(r.returncode == 0, f"render --check 报错：{r.stdout[-400:]}{r.stderr[-200:]}")
        r = run(str(SCRIPTS / "render.py"), str(reports), "--profile", "work")
        check(r.returncode == 0, f"render 失败：{r.stderr[-300:]}")
        hub = reports / "索引.html"
        check(hub.exists(), "没有生成 索引.html")
        if hub.exists():
            text = hub.read_text(encoding="utf-8")
            check("DV460" in text, "索引里没有 DV460 章节")
            check("429MB/s" in text, "索引没有带上条目原文")

        # 3) monthly
        draft = tmpdir / "草稿.md"
        r = run(str(SCRIPTS / "monthly.py"), str(reports), "--month", "2026-10",
                "--digest", str(digest_path), "--out", str(draft))
        check(r.returncode == 0, f"monthly 失败：{r.stderr[-300:]}")
        if draft.exists():
            body = draft.read_text(encoding="utf-8")
            check("DV460" in body, "月报草稿没有 DV460")
            check("429MB/s" in body, "月报草稿没有合并周报条目")
        else:
            fails.append("没有生成月报草稿")

    if fails:
        print("selfcheck 失败：")
        for f in fails:
            print("  - " + f)
        return 1
    print("selfcheck 通过：collect / render / monthly 全链路正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
