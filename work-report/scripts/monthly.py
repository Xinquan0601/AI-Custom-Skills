#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""周报 -> 月报草稿，并核对哪些会话没被写进月报。

  python scripts/monthly.py <报告目录> --month 2026-10 --digest digest.json
  python scripts/monthly.py <报告目录> --month 2026-10 --out 月报/202610-月报.md

月报是周报的合集：先合并去重出草稿，再用 digest 里没用上的会话核对补漏。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG = SKILL_DIR / "config" / "report-config.json"
TITLE = re.compile(r"^#\s+((?:非)?工作[周月]报)\s*\|\s*(\d{4}\.\d{2}\.\d{2})\s*[–—-]\s*(\d{4}\.\d{2}\.\d{2})")
ITEM = re.compile(r"^-\s+(.+)$")
STATUS = re.compile(r"^(完成|未完成|进行中)")
EVID = re.compile(r"(\d+(?:\.\d+)?\s*(?:MB/s|GB/s|MiB/s|Gbps|GT/s|Mbps|Kbps|GiB|ms|%))"
                  r"|(0x[0-9A-Fa-f]{2,})|(\d{4,5}\s*8N1)|(AA\s*55)|(CRC16?)", re.I)


def load_sections(md_path: Path) -> tuple[str, str, list[tuple[str, str, str]]]:
    """读一份周报 -> (标题词, 周期起始, [(系列, 客户组, 条目)...])"""
    text = md_path.read_text(encoding="utf-8")
    m = TITLE.search(text)
    label = m.group(1) if m else ""
    start = m.group(2) if m else ""
    rows, series, group = [], "", ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            series, group = line[3:].strip(), ""
        elif line.startswith("### "):
            group = line[4:].strip()
            group = re.sub(r"^\d+\.\s*", "", group)
        elif ITEM.match(line):
            rows.append((series, group, ITEM.match(line).group(1).strip()))
    return label, start, rows


def group_key(name: str) -> tuple:
    base = re.sub(r"^DV\d{3}-", "", name or "")
    base = base.replace("客户", "")
    low = base.strip().lower()
    return (0 if low[:1].isalpha() and low[:1].isascii() else 1, low)


def body_key(item: str) -> str:
    return re.sub(r"\W+", "", STATUS.sub("", item))[:28]


def merge(parts: list[tuple[str, list[tuple[str, str, str]]]]) -> list[tuple[str, str, list[str]]]:
    order: list[tuple[str, str]] = []
    items: dict[tuple[str, str], list[str]] = {}
    seen: dict[tuple[str, str], dict[str, int]] = {}
    for _start, rows in parts:
        for series, group, item in rows:
            key = (series, group)
            if key not in items:
                items[key] = []
                seen[key] = {}
                order.append(key)
            k = body_key(item)
            if k in seen[key]:
                idx = seen[key][k]
                if len(item) > len(items[key][idx]):
                    items[key][idx] = item
                continue
            seen[key][k] = len(items[key])
            items[key].append(item)
    return [(s, g, items[(s, g)]) for s, g in order]


def render(month: str, blocks, cfg: dict, prefix: str = "工作") -> str:
    start = f"{month[:4]}.{month[4:6]}.01"
    y, mo = int(month[:4]), int(month[4:6])
    last = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]
    out = [f"# {prefix}月报 | {start} – {month[:4]}.{month[4:6]}.{last:02d}", ""]
    rank = {name: i for i, name in enumerate(cfg.get("series_order", []))}
    blocks = sorted(blocks, key=lambda b: (rank.get(b[0], 99), group_key(b[1])))
    for series, group, items in blocks:
        if series and (not out or out[-1] != f"## {series}"):
            if f"## {series}" not in out:
                out += [f"## {series}", ""]
        if group:
            out += [f"### {group}", ""]
        for it in items:
            out.append(f"- {it}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


IDENT = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{2,}|\d{2,}")


def audit(blocks, digest: dict, month: str, bucket: str = "work") -> list[tuple[str, str, int]]:
    """核对：本月工作会话里，哪些在月报中连标题关键词都找不到。"""
    text = " ".join(it for _s, _g, items in blocks for it in items).lower()
    gaps = []
    for s in digest.get("sessions", []):
        if s.get("bucket") != bucket or not str(s.get("start", "")).startswith(month[:4] + "-" + month[4:6]):
            continue
        title = s.get("title", "")
        toks = {t.lower() for t in IDENT.findall(title) if len(t) >= 3}
        for run in re.findall(r"[\u4e00-\u9fff]{3,}", title):
            toks |= {run[i:i + 3] for i in range(len(run) - 2)}
        nums = {m.group(0).lower() for c in s.get("conclusions", []) for m in EVID.finditer(c)}
        hit = sum(1 for t in toks if t in text) + sum(1 for t in nums if t in text)
        if hit == 0:
            gaps.append((s["start"], s["title"], len(toks | nums)))
    return gaps


def main() -> int:
    ap = argparse.ArgumentParser(description="周报 -> 月报草稿")
    ap.add_argument("dir")
    ap.add_argument("--month", required=True, help="2026-10")
    ap.add_argument("--digest", help="digest.json，用于核对漏写")
    ap.add_argument("--out", help="写到这个 .md；不给就打到标准输出")
    ap.add_argument("--bucket", choices=["work", "nonwork"], default="work", help="核对哪些会话")
    args = ap.parse_args()

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    month = args.month.replace("-", "")
    want = f"{month[:4]}.{month[4:6]}"
    root = Path(args.dir)
    parts = []
    prefix = "工作"
    for p in sorted(root.rglob("*.md")):
        if "_历史" in p.parts or "数据源" in p.parts or p.name.startswith("_"):
            continue
        if "月报" in p.parts or "月报" in p.name:
            continue
        label, start, rows = load_sections(p)
        if rows and start.startswith(want):
            parts.append((start, rows))
            prefix = "非工作" if label.startswith("非") else "工作"
            print(f"  收 {p.name}  {len(rows)} 条")
    if not parts:
        print(f"{want} 没有周报")
        return 2
    parts.sort(key=lambda x: x[0])
    blocks = merge(parts)
    total = sum(len(i) for _s, _g, i in blocks)
    print(f"  周报条目 {sum(len(r) for _s, r in parts)} 条 -> 合并去重 {total} 条")

    if args.digest:
        digest = json.loads(Path(args.digest).read_text(encoding="utf-8"))
        gaps = audit(blocks, digest, month, args.bucket)
        if gaps:
            print(f"\n  可能漏写的会话 {len(gaps)} 个（标题关键词和数字都没出现在草稿里）：")
            for start, title, n in gaps:
                print(f"    {start}  {title[:40]}  ({n} 个可核对数字)")
        else:
            print("\n  本月工作会话的数字都能在月报里找到")

    md = render(month, blocks, cfg, prefix)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"\n月报草稿 -> {args.out}")
    else:
        print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())