#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告构建器 / 校验器。

  python render.py <报告目录>            生成 索引.html（含快照），并在生成前校验
  python render.py <报告目录> --check    只校验，不写文件

正文永远是 .md，索引.html 只是壳。壳页连上文件夹之后自己读 md，不再需要这里。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SKILL_DIR = Path(__file__).resolve().parent.parent
HUB_TEMPLATE = SKILL_DIR / "templates" / "hub.html"
CONFIG = SKILL_DIR / "config" / "report-config.json"

FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
PATH_WIN = re.compile(r"[A-Za-z]:[\\/]")
PATH_UNIX = re.compile(r"(?<!/)/(home|Users|mnt|opt|var)/")
HEX_HASH = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
ITEM_RE = re.compile(r"^(?:- |\d+[.)]\s)")
H1_RE = re.compile(r"^#\s+(.+)$", re.M)
TITLE_RE = re.compile(r"^#\s+((?:非)?工作[周月]报)\s*\|\s*(\d{4}\.\d{2}\.\d{2})\s*[–—-]\s*(\d{4}\.\d{2}\.\d{2})\s*$")


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def split_front(text: str) -> tuple[dict, str]:
    m = FRONT_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def guess_kind(path: Path, meta: dict) -> str:
    kind = (meta.get("kind") or "").lower()
    if kind in ("weekly", "monthly"):
        return kind
    if any(tag in path.stem for tag in ("月报", "monthly")):
        return "monthly"
    return "weekly"


def period_of(body: str) -> str:
    m = H1_RE.search(body)
    if not m:
        return ""
    parts = m.group(1).split("|")
    return parts[1].strip() if len(parts) > 1 else ""


def sort_key(path: Path) -> int:
    digits = re.sub(r"\D", "", path.stem)
    return int(digits) if digits else 0


def is_work_dir(target: Path, profile: str = "auto") -> bool:
    if profile == "work":
        return True
    if profile == "nonwork":
        return False
    return "工作" in target.name


def group_key(name: str) -> tuple:
    """客户组排序键：拉丁字母在前按字母序，中文在后按字序。"""
    base = re.sub(r"^DV\d{3}-", "", name)
    for tail in ("客户",):
        base = base.replace(tail, "")
    low = base.strip().lower()
    return (0 if low[:1].isalpha() and low[:1].isascii() else 1, low)


MAX_ITEM = 120
MIN_ITEM = 60   # 默认下限 = 60，配置文件 limit.min_chars 可覆盖（非工作设 0 关闭）


def check(md: str, kind: str, cfg: dict, work: bool) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    series = {k.lower(): v for k, v in cfg["series"].items()}
    limits = cfg["limits"] if work else cfg["limits_nonwork"]
    limit = limits["weekly_item_chars" if kind == "weekly" else "monthly_item_chars"]
    floor = limits.get("min_chars", MIN_ITEM)
    lines = [l.strip() for l in md.splitlines() if l.strip()]

    if "</script" in md.lower():
        issues.append(("error", "正文含 </script，会破坏单文件结构"))
    h1 = next((l for l in lines if l.startswith("# ")), "")
    if not h1:
        issues.append(("error", "缺少一级标题： # 工作周报 | 2026.10.26 – 2026.11.01"))
    else:
        m = TITLE_RE.match(h1)
        if not m:
            issues.append(("warn", "标题格式应为： # 工作周报 | 2026.10.08 – 2026.10.12"))
        else:
            name, start, end = m.group(1), m.group(2), m.group(3)
            prefix = "工作" if work else "非工作"
            want = prefix + {"weekly": "周报", "monthly": "月报"}[kind]
            if name != want:
                issues.append(("error", f"标题写的是「{name}」，按文件名应该是「{want}」"))
            try:
                a = datetime.strptime(start, "%Y.%m.%d")
                b = datetime.strptime(end, "%Y.%m.%d")
                if b < a:
                    issues.append(("error", f"周期起止颠倒：{start} – {end}"))

            except ValueError:
                issues.append(("error", f"日期格式不对：{start} – {end}"))

    h2 = [l[3:].strip() for l in lines if l.startswith("## ")]
    if not h2:
        issues.append(("error", "没有任何 ## 一级分组"))

    current = None
    groups_by_series: dict[str, list[str]] = {}
    for l in lines:
        if l.startswith("## "):
            current = l[3:].strip()
            low = current.lower()
            if work and current not in (current.upper(),):
                issues.append(("error", f"系列名要大写：{current.upper()}，不是 {current}"))
            if work and low not in series:
                issues.append(("error", f"系列「{current}」不在配置里：{', '.join(series)}"))
            if not work and low in series:
                issues.append(("error", f"非工作报告里出现了工作系列「{current}」"))
            continue
        if l.startswith("### ") and work and current:
            group = l[4:].strip()
            allowed = series.get(current.lower(), {}).get("groups")
            if allowed and group not in allowed:
                issues.append(("error", f"{current} 只允许 {' / '.join(allowed)}，出现「{group}」"))
            groups_by_series.setdefault(current, []).append(group)
            continue
        if not ITEM_RE.match(l):
            continue
        body = ITEM_RE.sub("", l)
        if len(body) > limit:
            issues.append(("warn", f"条目 {len(body)} 字，超出 {limit}，看是否装了两件事：{body[:18]}…"))
        if floor and len(body) < floor:
            issues.append(("warn", f"条目 {len(body)} 字，低于 {floor} 的下限，确认是素材不足还是缺细节：{body[:18]}…"))
        if not re.match("^(完成|未完成|进行中)", body):
            issues.append(("warn", f"条目没以状态词开头：{body[:18]}…"))

    for series_name, groups in groups_by_series.items():
        keys = [group_key(g) for g in groups]
        if keys != sorted(keys):
            want = [g for _k, g in sorted(zip(keys, groups))]
            issues.append(("warn", f"{series_name} 客户组要按首字母排：{' → '.join(want)}"))

    for l in lines:
        if PATH_WIN.search(l) or PATH_UNIX.search(l):
            issues.append(("error", f"出现文件路径：{l[:28]}…"))
        elif HEX_HASH.search(l):
            issues.append(("warn", f"疑似裸提交号：{l[:28]}…"))
        for w in cfg["forbidden_words"]:
            if w in l:
                issues.append(("warn", f"AI 腔词「{w}」：{l[:20]}…"))
    return issues


def collect(target: Path, cfg: dict, profile: str = "auto") -> tuple[list[dict], int]:
    work = is_work_dir(target, profile)
    files = [p for p in sorted(target.rglob("*.md"))
             if not any(part.startswith("_") for part in p.parts)
             and "数据源" not in p.parts]
    records: list[dict] = []
    errors = 0
    for md_path in files:
        text = md_path.read_text(encoding="utf-8")
        meta, body = split_front(text)
        kind = guess_kind(md_path, meta)
        issues = check(body, kind, cfg, work)
        for level, msg in issues:
            print(f"  [{level}] {md_path.name}: {msg}")
        if any(lv == "error" for lv, _ in issues):
            print(f"  跳过 {md_path.name}")
            errors += 1
            continue
        try:
            rel = md_path.relative_to(target).as_posix()
        except ValueError:
            rel = md_path.name
        m = TITLE_RE.match((H1_RE.search(body) or [None, ""])[1] if H1_RE.search(body) else "")
        span = (m.group(2), m.group(3)) if m else ("", "")
        records.append({"file": rel, "md": text, "sort": sort_key(md_path),
                        "kind": kind, "span": span})
    records.sort(key=lambda r: -r["sort"])

    starts: dict[str, list[tuple[str, str]]] = {}
    for rec in records:
        if rec["kind"] != "weekly" or not rec["span"][0]:
            continue
        starts.setdefault(rec["span"][0][:7], []).append((rec["span"][0], rec["file"]))
    for month, items in starts.items():
        items.sort()
        first = items[0][0]
        for start, name in items[1:]:
            try:
                d = datetime.strptime(start, "%Y.%m.%d")
            except ValueError:
                continue
            if d.weekday() != 1:
                print(f"  [warn] {name}: 周报应从周二起算，{start} 是"
                      f"周{'一二三四五六日'[d.weekday()]}（本月首份是 {first}）")

    seen: dict[tuple[str, str], str] = {}
    for rec in records:
        for line in rec["md"].splitlines():
            line = line.strip()
            if not ITEM_RE.match(line):
                continue
            body = ITEM_RE.sub("", line)[:40]
            if len(body) < 12:
                continue
            key = (rec["kind"], body)   # 月报本来就是周报的合集，不跨类型比
            if key in seen and seen[key] != rec["file"]:
                print(f"  [warn] {rec['file']}: 与 {seen[key]} 有重复条目：{body}…")
            seen.setdefault(key, rec["file"])
    return records, errors


def build_hub(target: Path, cfg: dict, profile: str = "auto") -> int:
    records, errors = collect(target, cfg, profile)
    if errors:
        print(f"{errors} 份有错误，已跳过；其余照常生成")
    if not records:
        print("目录里还没有 .md，仍会生成空壳")
    payload = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "reports": [{"file": r["file"], "md": r["md"]} for r in records],
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    stamp = hashlib.sha1(data.encode("utf-8")).hexdigest()[:12]
    title = "工作报告" if is_work_dir(target, profile) else "非工作记录"
    html = (HUB_TEMPLATE.read_text(encoding="utf-8")
            .replace("{{TITLE}}", title)
            .replace("{{DATA}}", data))
    html = html.replace("<!doctype html>",
                        f"<!doctype html>\n<!-- work-report snapshot {stamp} "
                        f"{payload['generated']} {len(records)} files -->", 1)
    out_path = target / "索引.html"
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    print(f"索引页 -> {out_path}  ({len(records)} 份, {out_path.stat().st_size} 字节)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="报告目录 -> 索引.html")
    ap.add_argument("dir", help="报告目录（含 周报 / 月报 或其他子目录）")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    ap.add_argument("--profile", choices=["auto", "work", "nonwork"], default="auto",
                    help="work=只用四个 dv 系列；nonwork=禁止出现 dv 系列")
    args = ap.parse_args()

    cfg = load_config()
    target = Path(args.dir)
    if not target.is_dir():
        print(f"目录不存在：{target}")
        return 2
    if args.check:
        records, errors = collect(target, cfg, args.profile)
        print(f"{len(records)} 份通过，{errors} 份有错误")
        return 1 if errors else 0
    return build_hub(target, cfg, args.profile)


if __name__ == "__main__":
    sys.exit(main())
