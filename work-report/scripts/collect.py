#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 agenttrail 导出包整理成写报告用的素材。

  python collect.py <bundle 目录>                 # 输出 digest.json + 概览
  python collect.py <bundle 目录> --week 2026-10-26   # 只看这一周，逐会话列素材

只读 events.csv / sessions.csv，不改任何原始文件。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 单条事件内容可能远超 csv 默认的 128KB 上限
csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG = SKILL_DIR / "config" / "report-config.json"
TZ = timezone(timedelta(hours=8))


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def local(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ)
    except ValueError:
        return None


def week_start(d: datetime) -> str:
    """周报按 周二 ~ 周一 起算。"""
    start = d - timedelta(days=(d.weekday() - 1) % 7)
    return start.strftime("%Y-%m-%d")


def base_path(p: str) -> str:
    return os.path.basename(p.replace("\\", "/").rstrip("/")) if p else ""


def classify(session: dict, cfg: dict) -> tuple[str, str, str]:
    hay = " ".join([session.get("project") or "", base_path(session.get("cwd") or ""),
                    session.get("title") or ""]).lower()
    for needle in cfg["projects"]["ignore"]:
        if needle.lower() in hay:
            return "ignore", "", ""
    # 同一个仓库按板子出固件，靠标题里的板号区分系列，优先于项目名
    for hint in cfg["projects"].get("board_hints", []):
        if re.search(hint["pattern"], hay, re.I):
            return "work", hint["series"], hint["group"]
    for rule in cfg["projects"]["work"]:
        if rule["match"].lower() in hay:
            return "work", rule["series"], rule["group"]
    for rule in cfg["projects"]["nonwork"]:
        if rule["match"].lower() in hay:
            return "nonwork", "", rule["group"]
    # 既不是工作项目、也不在忽略清单 -> 一律算非工作，不留在未归类
    return "nonwork", "", "其他"


def read_bundle(bundle: Path) -> tuple[list[dict], list[dict]]:
    with open(bundle / "sessions.csv", encoding="utf-8", newline="") as fh:
        sessions = list(csv.DictReader(fh))
    with open(bundle / "events.csv", encoding="utf-8", newline="") as fh:
        events = list(csv.DictReader(fh))
    return sessions, events


def merge_bundles(bundles: list[Path]) -> tuple[list[dict], list[dict], list[str]]:
    """多个导出包合并。同一会话取事件最全的那份；事件按 fingerprint 去重。"""
    sessions: dict[str, dict] = {}
    events: dict[str, dict] = {}
    seen_files: list[str] = []
    for bundle in bundles:
        s_list, e_list = read_bundle(bundle)
        seen_files.append(bundle.name)
        for s in s_list:
            key = s["external_id"]
            old = sessions.get(key)
            if old is None or int(s.get("event_count") or 0) > int(old.get("event_count") or 0):
                sessions[key] = s
        for e in e_list:
            sig = e.get("fingerprint") or (e["session_id"] + "|" + e["event_type"] + "|" + e["timestamp"])
            events[sig] = e
    return list(sessions.values()), list(events.values()), seen_files


SUBAGENT_MARK = "You are a subagent spawned by another session"


def merge_subagents(sessions: list[dict], first_msg: dict[str, str] | None = None) -> tuple[list[dict], dict[str, str]]:
    """子会话挂到父会话上；挂不上就留 orphan，绝不猜。

    两种子会话都要认：project 明确写 subagents 的，以及正文以
    "You are a subagent spawned by another session" 开头的（opencode 会把它记成独立会话）。
    """
    first_msg = first_msg or {}
    subs = [s for s in sessions
            if (s.get("project") or "").lower() == "subagents"
            or first_msg.get(s["external_id"], "").startswith(SUBAGENT_MARK)]
    parents = [s for s in sessions if s not in subs]
    mapping: dict[str, str] = {}
    for sub in subs:
        scwd = base_path(sub.get("cwd") or "")
        s_from, s_to = local(sub["started_at"]), local(sub["ended_at"])
        best, best_gap = None, None
        for p in parents:
            pcwd = base_path(p.get("cwd") or "")
            if not (scwd and pcwd and (scwd == pcwd or scwd.startswith(pcwd) or pcwd.startswith(scwd))):
                continue
            p_from, p_to = local(p["started_at"]), local(p["ended_at"])
            if not (p_from and p_to and s_from and s_to):
                continue
            if s_from >= p_from - timedelta(minutes=5) and s_to <= p_to + timedelta(minutes=5):
                gap = abs((s_from - p_from).total_seconds())
                if best is None or gap < best_gap:
                    best, best_gap = p, gap
        if best:
            mapping[sub["external_id"]] = best["external_id"]
    return subs, mapping



EVIDENCE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:MB/s|GB/s|MiB/s|Gbps|GT/s|Mbps|Kbps|KiB|GiB|ms|%))"
    r"|(0x[0-9A-Fa-f]{2,})|(\d+\s*(?:页|个|块|条|路|帧|盘|秒|分钟|小时|字节|行))"
    r"|(\d{4,5}\s*8N1)|(CRC16|CRC|AA\s*55|Modbus)", re.I)
VERDICT = re.compile(
    r"定位|排查|根因|确认|复现|改为|修复|完成|验证|实测|构建|提交|降速|建链|不支持|无法|只有|没有")


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"[。\n；;]+", text or "")
    return [p.strip(" \t-*#|") for p in parts if p.strip(" \t-*#|")]


CJK = re.compile(r"[\u4e00-\u9fff]")
CODE_HEAD = re.compile(r"^\s*(?:printf|grep|cat |cd |ls |sudo|curl|git |python|pip|echo|\$|#include|import |def |class |function |var |const )")
QUESTION = re.compile(r"(要我|需要我|是否要|可以先|可以吗|要不要)")


LIST_PREFIX = re.compile(r"^\s*(?:>\s*)?(?:\d+[.)]|[-*\u2022])\s*")


def clean(s: str) -> str:
    s = s.replace("**", "").replace("~~", "").replace(chr(96), "")
    s = LIST_PREFIX.sub("", s)
    return " ".join(s.split())


def _usable(s: str) -> bool:
    if not (12 <= len(s) <= 220):
        return False
    if "?" in s or "？" in s or QUESTION.search(s):
        return False
    if CODE_HEAD.search(s):
        return False
    if s.count(chr(96)) >= 4 or s.count("|") >= 3:
        return False
    if len(CJK.findall(s)) / max(1, len(s)) < 0.45:
        return False
    return True


def pick_conclusions(msgs, limit: int = 14):
    """从全部助手消息里挑结论候选：原文照抄，只做取舍不做改写。

    打分偏好「既有实测数字、又有判定动词」的句子；问句、代码行、英文行丢掉。
    """
    pool = []
    for mi, (role, _ts, text) in enumerate(msgs):
        if role != "assistant":
            continue
        for si, s in enumerate(split_sentences(text)):
            s = clean(s)
            if not _usable(s):
                continue
            score = (2 if EVIDENCE.search(s) else 0) + (1 if VERDICT.search(s) else 0)
            score += min(len(s), 120) / 120.0
            pool.append((score, mi, si, s))
    pool.sort(key=lambda x: (-x[0], x[1], x[2]))
    chosen, seen = [], set()
    for score, mi, si, s in pool:
        key = re.sub(r"\W+", "", s)[:32]
        if key in seen:
            continue
        seen.add(key)
        chosen.append((mi, si, s))
        if len(chosen) >= limit:
            break
    chosen.sort(key=lambda x: (x[0], x[1]))
    return [s for _mi, _si, s in chosen]

def write_transcripts(texts: dict, rows: list[dict], out_dir: Path) -> int:
    """每条会话一份全文，按周分目录。素材名以 _ 开头，render 时会被跳过。"""
    meta = {r["sid"]: r for r in rows}
    n = 0
    for sid, msgs in texts.items():
        r = meta.get(sid)
        if not r or r["bucket"] not in ("work", "nonwork") or not msgs:
            continue
        week_dir = out_dir / r["bucket"] / (r["week"] or "unknown")
        week_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[\\/:*?\"<>|\s]+", "_", r["title"])[:40] or "会话"
        path = week_dir / f"{r['start'][:10]}_{r['group'] or r['series'] or 'x'}_{safe}_{sid[-8:]}.txt"
        body = [f"# {r['title']}",
                f"系列 {r['series']} · {r['group']} | {r['project']} | {r['start']} | 事件 {r['events']}",
                ""]
        for role, ts, text in msgs:
            body.append(f"## [{role}] {ts}")
            body.append(text.strip())
            body.append("")
        path.write_text("\n".join(body), encoding="utf-8")
        n += 1
    return n


def build(bundles: list[Path], cfg: dict) -> dict:
    sessions, events, names = merge_bundles(bundles)
    first_msg: dict[str, str] = {}
    for e in sorted(events, key=lambda x: x["timestamp"]):
        if e["event_type"] == "user_message":
            first_msg.setdefault(e["session_id"], " ".join(e["content"].split()))
    subs, merge = merge_subagents(sessions, first_msg)
    texts: dict[str, list[tuple[str, str, str]]] = {}

    by_sid: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        sid = e["session_id"]
        by_sid[merge.get(sid, sid)].append(e)

    out = []
    sub_ids = {s["external_id"] for s in subs}
    for s in sessions:
        if s["external_id"] in sub_ids:
            continue
        sid = s["external_id"]
        bucket, series, group = classify(s, cfg)
        evs = sorted(by_sid.get(sid, []), key=lambda e: e["timestamp"])
        asks = [e["content"].strip() for e in evs if e["event_type"] == "user_message"]
        msgs = []
        for e in evs:
            if e["event_type"] not in ("user_message", "assistant_message"):
                continue
            t = local(e["timestamp"])
            msgs.append(("user" if e["event_type"] == "user_message" else "assistant",
                         t.strftime("%H:%M") if t else "", e["content"]))
        texts[sid] = msgs
        days = sorted({local(e["timestamp"]).strftime("%Y-%m-%d") for e in evs if local(e["timestamp"])})
        start = local(s["started_at"])
        out.append({
            "sid": sid,
            "bucket": bucket,
            "fallback": bucket == "nonwork" and group == "其他",
            "series": series,
            "group": group,
            "title": (s.get("title") or "").strip(),
            "agent": s.get("agent_key"),
            "project": s.get("project"),
            "cwd": base_path(s.get("cwd") or ""),
            "start": start.strftime("%Y-%m-%d %H:%M") if start else "",
            "week": week_start(start) if start else "",
            "days": days,
            "events": len(evs),
            "user_msgs": len(asks),
            "asks": asks[:10],
            "subagents": [x["external_id"] for x, y in ((sub, merge.get(sub["external_id"])) for sub in subs) if y == sid],
            "conclusions": pick_conclusions(msgs),
        })
    out.sort(key=lambda r: (r["week"], r["start"]))
    return {"bundle": ", ".join(names), "generated": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
            "sessions": out, "texts": texts,
            "orphan_subagents": [x["external_id"] for x in subs if x["external_id"] not in merge]}


def show(digest: dict, week: str | None, only: str, month: str | None = None) -> None:
    rows = [r for r in digest["sessions"] if (week is None or r["week"] == week)]
    if month:
        rows = [r for r in rows if r["start"].startswith(month)]
    if only == "unassigned":
        rows = [r for r in rows if r.get("fallback")]
    elif only != "all":
        rows = [r for r in rows if r["bucket"] == only]
    if not rows:
        print("没有匹配的会话")
        return
    cur = None
    for r in rows:
        if r["week"] != cur:
            cur = r["week"]
            print(f"\n{'='*70}\n周 {cur} 起\n{'='*70}")
        tag = {"work": f"{r['series']} · {r['group']}",
               "nonwork": ("非工作·兜底" if r.get("fallback") else "非工作") + f" · {r['group']}",
               "ignore": "忽略"}[r["bucket"]]
        print(f"\n[{tag}] {r['title']}")
        print(f"   {r['agent']} | {r['project']} | {r['start']} | 事件{r['events']} 提问{r['user_msgs']}"
              + (f" | 子会话{len(r['subagents'])}" if r["subagents"] else ""))
        for a in r["asks"][:4]:
            one = " ".join(a.split())
            print("   > " + (one[:180] + ("…" if len(one) > 180 else "")))


def main() -> int:
    ap = argparse.ArgumentParser(description="agenttrail 导出包 -> 报告素材")
    ap.add_argument("bundle", nargs="+")
    ap.add_argument("--week", help="只看这一周（周一日期，如 2026-10-26）")
    ap.add_argument("--month", help="只看这个月（如 2026-10）")
    ap.add_argument("--only", choices=["work", "nonwork", "unassigned", "all"], default="all",
                    help="unassigned = 非工作里靠兜底规则落下来的那部分")
    ap.add_argument("--json", help="把 digest 写到这个路径")
    ap.add_argument("--transcripts", help="把每条会话的用户消息与助手消息全文写到这个目录")
    args = ap.parse_args()

    bundles = [Path(b) for b in args.bundle]
    digest = build(bundles, load_config())
    texts = digest.pop("texts", {})
    if args.transcripts:
        n = write_transcripts(texts, digest["sessions"], Path(args.transcripts))
        print(f"会话全文 -> {args.transcripts}  ({n} 份)")
    if args.json:
        Path(args.json).write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"digest -> {args.json}")
    show(digest, args.week, args.only, args.month)
    if digest["orphan_subagents"]:
        print(f"\n未挂上父会话的子会话：{len(digest['orphan_subagents'])} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
