#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
search_kb.py — 搜尋 OpenAB 知識庫
======================================
跨 AI 和 PLA 兩個研究流的已歸檔內容。

用法：
    python3 search_kb.py "關鍵字"
    python3 search_kb.py "AI" --cat ai
    python3 search_kb.py "火箭軍" --cat pla
    python3 search_kb.py "agent" --from 2026-05 --limit 20
    python3 search_kb.py "模型" --fulltext          # 同時搜尋 MD 全文
    python3 search_kb.py --recent 30                # 最近 30 筆不分類
    python3 search_kb.py --atoms "GPT"              # 搜尋 atoms 裡的主張

環境變數（與 process_inbox.py 相同）：
    REPO_DIR_AI    agent-broker 本地路徑（預設 /home/node/repo_ai）
    REPO_DIR_PLA   pla-military-analysis 本地路徑（預設 /home/node/repo_pla）
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO_AI = Path(os.environ.get("REPO_DIR_AI", "/home/node/repo_ai"))
REPO_PLA = Path(os.environ.get("REPO_DIR_PLA", "/home/node/repo_pla"))

# ── CSV 欄位定義（與 process_inbox.py 一致） ───────────────────────────────
_AI_KEY_FIELDS = ["timestamp", "title", "summary_zh", "ai_subcategory",
                  "tools_or_entities", "atoms_count", "tags", "urls",
                  "source_tier", "confidence", "raw_md_path", "html_path"]
_PLA_KEY_FIELDS = ["timestamp", "title", "summary_zh", "chapter", "chapter_title",
                   "trigger_topic_id", "lake", "pool", "atoms_count", "entities",
                   "tags", "urls", "source_tier", "confidence", "raw_md_path", "html_path"]


# ── CSV 載入 ─────────────────────────────────────────────────────────────────

def _iter_csv_rows(repo: Path, subdir: str, prefix: str, month_filter: str | None):
    """Yield (row_dict, category_tag) from all matching CSV files."""
    cat = "pla" if repo == REPO_PLA else "ai"
    pattern = f"{prefix}_*.csv"
    candidates = sorted((repo / subdir).glob(pattern)) if (repo / subdir).exists() else []

    for csv_path in candidates:
        if month_filter and month_filter not in csv_path.name:
            continue
        try:
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row["_cat"] = cat
                    row["_csv"] = str(csv_path)
                    yield row
        except Exception:
            pass


def load_all_rows(cat_filter: str | None, month_filter: str | None) -> list[dict]:
    rows: list[dict] = []

    if cat_filter in (None, "ai", "other"):
        rows += list(_iter_csv_rows(REPO_AI, "_outputs/ai", "inbox_ai", month_filter))
        rows += list(_iter_csv_rows(REPO_AI, "_outputs/misc", "inbox_misc", month_filter))
    if cat_filter in (None, "pla"):
        rows += list(_iter_csv_rows(REPO_PLA, "_outputs/pla", "inbox_pla", month_filter))

    # Sort by timestamp descending
    rows.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return rows


# ── 搜尋邏輯 ─────────────────────────────────────────────────────────────────

def _row_matches(row: dict, keywords: list[str]) -> bool:
    haystack = " ".join([
        row.get("title", ""),
        row.get("summary_zh", ""),
        row.get("tags", ""),
        row.get("tools_or_entities", ""),
        row.get("entities", ""),
        row.get("ai_subcategory", ""),
        row.get("chapter_title", ""),
        row.get("urls", ""),
    ]).lower()
    return all(kw.lower() in haystack for kw in keywords)


def _md_matches(row: dict, keywords: list[str], repo_base: Path) -> bool:
    md_rel = row.get("raw_md_path", "")
    if not md_rel:
        return False
    md_path = repo_base / md_rel
    try:
        content = md_path.read_text("utf-8", errors="replace").lower()
        return all(kw.lower() in content for kw in keywords)
    except Exception:
        return False


def _atoms_match(row: dict, keywords: list[str], repo_base: Path) -> list[str]:
    """Return matching atom claims from the JSON atoms file if it exists."""
    md_rel = row.get("raw_md_path", "")
    if not md_rel:
        return []
    slug = Path(md_rel).stem
    atoms_path = repo_base / "_system" / "atoms" / f"{slug}__atoms.json"
    try:
        atoms = json.loads(atoms_path.read_text("utf-8"))
        matches = []
        for a in atoms if isinstance(atoms, list) else []:
            claim = a.get("claim", "")
            if all(kw.lower() in claim.lower() for kw in keywords):
                matches.append(claim)
        return matches
    except Exception:
        return []


def search(
    keywords: list[str],
    cat_filter: str | None = None,
    month_filter: str | None = None,
    fulltext: bool = False,
    atoms_only: bool = False,
    limit: int = 15,
) -> list[dict]:
    rows = load_all_rows(cat_filter, month_filter)
    results = []
    for row in rows:
        repo_base = REPO_PLA if row.get("_cat") == "pla" else REPO_AI
        if not keywords:
            results.append({**row, "_matched_atoms": []})
            continue
        matched = _row_matches(row, keywords)
        atom_hits: list[str] = []
        if not matched and fulltext:
            matched = _md_matches(row, keywords, repo_base)
        if atoms_only or not matched:
            atom_hits = _atoms_match(row, keywords, repo_base)
            if atom_hits:
                matched = True
        if matched:
            results.append({**row, "_matched_atoms": atom_hits})
        if len(results) >= limit:
            break
    return results


# ── 最近 N 筆 ────────────────────────────────────────────────────────────────

def recent(limit: int, cat_filter: str | None) -> list[dict]:
    return load_all_rows(cat_filter, None)[:limit]


# ── 輸出格式化 ───────────────────────────────────────────────────────────────

_CAT_ICON = {"ai": "🤖", "pla": "🪖", "other": "📁"}


def _format_row(idx: int, row: dict, show_atoms: bool = False) -> str:
    cat = row.get("_cat", "ai")
    icon = _CAT_ICON.get(cat, "📄")
    ts = row.get("timestamp", "—")[:16]
    title = row.get("title", "（無標題）")
    summary = row.get("summary_zh", "")[:100]
    sub = row.get("ai_subcategory") or (
        f"{row.get('chapter','')} {row.get('chapter_title','')}".strip()
    )
    html_rel = row.get("html_path", "")
    tags = row.get("tags", "")[:60]

    lines = [f"[{idx}] {icon} {ts}  {cat.upper()}" + (f" · {sub}" if sub else "")]
    lines.append(f"    📌 {title}")
    if summary:
        lines.append(f"    {summary}")
    if tags:
        lines.append(f"    🏷  {tags}")
    if html_rel:
        lines.append(f"    📄 {html_rel}")
    if show_atoms and row.get("_matched_atoms"):
        for claim in row["_matched_atoms"][:3]:
            lines.append(f"    ⚛  {claim}")
    return "\n".join(lines)


def print_results(keyword_str: str, results: list[dict], show_atoms: bool = False) -> None:
    if not results:
        print(f"🔍 找不到「{keyword_str}」的相關記錄。")
        return
    print(f"🔍 搜尋結果：「{keyword_str}」（{len(results)} 筆）\n")
    for i, row in enumerate(results, 1):
        print(_format_row(i, row, show_atoms=show_atoms))
        print()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="搜尋 OpenAB 知識庫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("keyword", nargs="?", default="", help="搜尋關鍵字（可含空格的多詞 AND 搜尋）")
    parser.add_argument("--cat", choices=["ai", "pla", "other"], help="限定分類")
    parser.add_argument("--from", dest="from_month", metavar="YYYY-MM", help="從指定月份起")
    parser.add_argument("--limit", type=int, default=15, help="最多顯示幾筆（預設 15）")
    parser.add_argument("--fulltext", action="store_true", help="也搜尋 Markdown 全文")
    parser.add_argument("--atoms", metavar="KEYWORD", help="搜尋 atoms 主張（覆蓋 keyword）")
    parser.add_argument("--recent", type=int, metavar="N", help="列出最近 N 筆（不搜尋）")
    parser.add_argument("--stats", action="store_true", help="顯示知識庫統計")
    args = parser.parse_args()

    # ── 統計模式 ──────────────────────────────────────────────────────────────
    if args.stats:
        _print_stats()
        return 0

    # ── 最近 N 筆 ──────────────────────────────────────────────────────────────
    if args.recent:
        rows = recent(args.recent, args.cat)
        print_results(f"最近 {args.recent} 筆", rows)
        return 0

    # ── 搜尋模式 ──────────────────────────────────────────────────────────────
    atoms_mode = bool(args.atoms)
    raw_keyword = args.atoms or args.keyword
    if not raw_keyword:
        parser.print_help()
        return 1

    keywords = raw_keyword.split()
    results = search(
        keywords=keywords,
        cat_filter=args.cat,
        month_filter=args.from_month,
        fulltext=args.fulltext,
        atoms_only=atoms_mode,
        limit=args.limit,
    )
    print_results(raw_keyword, results, show_atoms=atoms_mode)
    return 0


def _print_stats() -> None:
    total_ai = total_pla = total_other = 0
    months_seen: set[str] = set()

    for repo, prefix_dir, prefix, cat_label in [
        (REPO_AI, "_outputs/ai", "inbox_ai", "AI"),
        (REPO_PLA, "_outputs/pla", "inbox_pla", "PLA"),
        (REPO_AI, "_outputs/misc", "inbox_misc", "Other"),
    ]:
        d = repo / prefix_dir
        if not d.exists():
            continue
        for p in d.glob(f"{prefix}_*.csv"):
            try:
                with p.open(encoding="utf-8-sig", newline="") as f:
                    n = sum(1 for _ in csv.DictReader(f))
                m = re.search(r"(\d{4}-\d{2})", p.name)
                if m:
                    months_seen.add(m.group(1))
                if cat_label == "AI":
                    total_ai += n
                elif cat_label == "PLA":
                    total_pla += n
                else:
                    total_other += n
            except Exception:
                pass

    total = total_ai + total_pla + total_other
    print("📊 知識庫統計")
    print(f"   🤖 AI    : {total_ai:>5} 筆")
    print(f"   🪖 PLA   : {total_pla:>5} 筆")
    print(f"   📁 Other : {total_other:>5} 筆")
    print(f"   ─────────────")
    print(f"   合計     : {total:>5} 筆")
    if months_seen:
        span = f"{min(months_seen)} → {max(months_seen)}"
        print(f"   時間跨度 : {span}")


if __name__ == "__main__":
    sys.exit(main())
