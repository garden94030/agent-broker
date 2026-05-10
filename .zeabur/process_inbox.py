#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
process_inbox.py
================
Per-message handler for the OpenAB LINE bot (Zeabur side), v3 — two-repo split.

Called by the Gemini agent on every incoming LINE message via:
    python3 /opt/process_inbox.py "<message text>"

Two top-level categories. Each writes into a SEPARATE GitHub repo:
  - ai    → garden94030/agent-broker          (REPO_DIR_AI on disk)
  - pla   → garden94030/pla-military-analysis (REPO_DIR_PLA on disk)
  - other → garden94030/agent-broker (default to AI repo, keeps PLA repo pure)

Outputs per category:
  AI / other:
    REPO_DIR_AI/ai_wiki/raw/<TS>_*.md           (or _outputs/misc/raw for other)
    REPO_DIR_AI/_outputs/ai/inbox/<TS>_*.html   (or _outputs/misc/inbox)
    REPO_DIR_AI/_outputs/ai/inbox_ai_<YYYY-MM>.csv (or inbox_misc_<YYYY-MM>.csv)
  PLA:
    REPO_DIR_PLA/wiki/raw/<TS>_*.md             ← daily 5:30 pipeline picks up
    REPO_DIR_PLA/_outputs/pla/inbox/<TS>_*.html
    REPO_DIR_PLA/_outputs/pla/inbox_pla_<YYYY-MM>.csv

Then: git pull --rebase + add + commit + push (single repo per message).

Environment:
  GEMINI_API_KEY     Google AI Studio key (Flash Lite)
  REPO_DIR_AI        absolute path to local clone of agent-broker (default /home/node/repo_ai)
  REPO_DIR_PLA       absolute path to local clone of pla-military-analysis (default /home/node/repo_pla)
  GIT_USER_NAME      default openab-bot
  GIT_USER_EMAIL     default openab-bot@users.noreply.github.com
  DRY_RUN=1          skip git operations (for local testing)
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_AI = Path(os.environ.get("REPO_DIR_AI", "/home/node/repo_ai"))
REPO_PLA = Path(os.environ.get("REPO_DIR_PLA", "/home/node/repo_pla"))
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
GIT_NAME = os.environ.get("GIT_USER_NAME", "openab-bot")
GIT_EMAIL = os.environ.get("GIT_USER_EMAIL", "openab-bot@users.noreply.github.com")
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"

TS_NOW = dt.datetime.now()
TS_FILE = TS_NOW.strftime("%Y%m%d_%H%M%S")
TS_HUMAN = TS_NOW.strftime("%Y-%m-%d %H:%M:%S")
YEAR_MONTH = TS_NOW.strftime("%Y-%m")

URL_RE = re.compile(r"https?://[^\s　]+")
SLUG_RE = re.compile(r"[^\w一-鿿]+")
YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]{11})"
)

CATEGORY_LABELS = {
    "ai": "AI 教育與技巧",
    "pla": "中共軍事動態",
    "other": "其他",
}


def slugify(text: str, max_len: int = 30) -> str:
    s = SLUG_RE.sub("_", text).strip("_")
    return (s[:max_len].rstrip("_") if len(s) > max_len else s) or "msg"


# ----------------------------------------------------------------------------
# URL fetching
# ----------------------------------------------------------------------------

def fetch_youtube(video_id: str) -> dict[str, str]:
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": data.get("title", ""),
            "text": f"YouTube 影片：{data.get('title','')}（頻道：{data.get('author_name','')}）",
            "kind": "youtube",
            "error": "",
        }
    except Exception as exc:
        return {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": "", "text": "", "kind": "youtube", "error": str(exc),
        }


def fetch_html(url: str, timeout: int = 8) -> dict[str, str]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; openab-line-bot/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(800_000).decode("utf-8", errors="replace")
    except Exception as exc:
        return {"url": url, "title": "", "text": "", "kind": "web", "error": str(exc)}

    m = re.search(r"<title[^>]*>([^<]+)</title>", raw, re.I | re.S)
    title = m.group(1).strip() if m else ""
    body = re.sub(r"<script.*?</script>", " ", raw, flags=re.I | re.S)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return {"url": url, "title": title[:200], "text": body[:1500], "kind": "web", "error": ""}


def fetch_url(url: str) -> dict[str, str]:
    m = YOUTUBE_RE.search(url)
    if m:
        return fetch_youtube(m.group(1))
    return fetch_html(url)


# ----------------------------------------------------------------------------
# Gemini Flash Lite REST: dual-category classification + atoms
# ----------------------------------------------------------------------------

GEMINI_PROMPT_TEMPLATE = """You are an archivist classifying incoming LINE messages into one of two main research streams.

The user sent this LINE message at {ts}:
<<<MESSAGE>>>
{message}
<<<END>>>
{fetched_block}

STEP 1 — Top-level category (pick exactly one):
  - "ai"    : AI 教育/技巧/工具/工作流/模型/論文/Prompt/Agent
  - "pla"   : 中共軍事動態/解放軍/兩岸軍事/亞太安全/灰色地帶
  - "other" : 兩邊都不算（閒聊、私人筆記、其他主題）

STEP 2 — Sub-classification (only fill the block matching the chosen category):

  IF category="ai" → ai_subcategory in:
    "ai_workflow" 工作流自動化 / "ai_education" 教學/教育/培訓 /
    "ai_tools" 工具/平台/IDE / "ai_models" 模型發布評測 /
    "ai_prompting" Prompt engineering / "ai_agents" Agent 架構 /
    "ai_papers" 論文/研究 / "ai_news" 業界新聞 / "ai_other"

  IF category="pla" → pla_chapter ∈ {{s0,s1,s2,s3,s4,s5,s5a,s6,s7,s8,s9}}:
    s0=體制總論 s1=陸軍 s2=海軍 s3=空軍 s4=火箭軍
    s5=新域新質 s5a=太空 s6=武警 s7=聯合作戰 s8=智能化AI s9=灰色地帶
    pla_trigger_topic ∈ T01..T18 (or "")
    pla_lake ∈ L/A/K/E or ""; pla_pool ∈ P/O1/O2/L or ""

STEP 3 — Always extract: title, summary_zh, atoms, tags, tools_or_entities,
  source_tier (T1/T2/T3), overall_confidence (high/medium/low), references[].

Reply with ONE JSON object only. No markdown fences, no commentary.

{{
  "category": "ai" | "pla" | "other",
  "ai_subcategory": "" or one of the AI codes,
  "pla_chapter": "" or s-code,
  "pla_chapter_title_zh": "",
  "pla_trigger_topic": "",
  "pla_lake": "",
  "pla_pool": "",
  "title": "≤30 char Chinese title",
  "summary_zh": "≤200 char Traditional-Chinese summary",
  "atoms": [{{"claim":"","type":"數據|趨勢|事件|主張|引用","entities":[],"confidence":""}}],
  "tags": [],
  "tools_or_entities": [],
  "source_tier": "",
  "overall_confidence": "",
  "references": [{{"url":"","title":"","kind":""}}]
}}
"""


def call_gemini(message: str, fetched: list[dict[str, str]]) -> dict[str, Any]:
    if not GEMINI_KEY:
        return {"error": "GEMINI_API_KEY not set"}

    fetched_block = ""
    for f in fetched:
        if f.get("text"):
            fetched_block += f"\n--- Fetched ({f.get('kind','web')}): {f['url']}\nTitle: {f.get('title','')}\n{f.get('text','')}\n"

    prompt = GEMINI_PROMPT_TEMPLATE.format(
        ts=TS_HUMAN, message=message, fetched_block=fetched_block,
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "maxOutputTokens": 4096,
        },
    }).encode("utf-8")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
    )
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        return {"error": f"Gemini call failed: {exc}"}

    try:
        api_resp = json.loads(raw)
        text = api_resp["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except Exception as exc:
        return {"error": f"Gemini parse failed: {exc}", "raw": raw[:400]}


# ----------------------------------------------------------------------------
# Per-category routing: which repo + paths
# ----------------------------------------------------------------------------

def repo_for(category: str) -> Path:
    """Return the repo dir for a category. 'other' goes to AI repo by design."""
    return REPO_PLA if category == "pla" else REPO_AI


def paths_for(category: str, slug: str) -> dict[str, Any]:
    repo = repo_for(category)
    if category == "pla":
        return {
            "repo": repo,
            "md": repo / "wiki" / "raw" / f"{TS_FILE}_lineingest_{slug}.md",
            "html": repo / "_outputs" / "pla" / "inbox" / f"{TS_FILE}_{slug}.html",
            "csv": repo / "_outputs" / "pla" / f"inbox_pla_{YEAR_MONTH}.csv",
            "git_paths": ["wiki/raw", "_outputs/pla"],
        }
    if category == "ai":
        return {
            "repo": repo,
            "md": repo / "ai_wiki" / "raw" / f"{TS_FILE}_lineingest_{slug}.md",
            "html": repo / "_outputs" / "ai" / "inbox" / f"{TS_FILE}_{slug}.html",
            "csv": repo / "_outputs" / "ai" / f"inbox_ai_{YEAR_MONTH}.csv",
            "git_paths": ["ai_wiki", "_outputs/ai"],
        }
    return {
        "repo": repo,
        "md": repo / "_outputs" / "misc" / "raw" / f"{TS_FILE}_lineingest_{slug}.md",
        "html": repo / "_outputs" / "misc" / "inbox" / f"{TS_FILE}_{slug}.html",
        "csv": repo / "_outputs" / "misc" / f"inbox_misc_{YEAR_MONTH}.csv",
        "git_paths": ["_outputs/misc"],
    }


# ----------------------------------------------------------------------------
# Markdown writer
# ----------------------------------------------------------------------------

def write_markdown(message: str, fetched: list[dict[str, str]],
                   extracted: dict[str, Any], slug: str, paths: dict[str, Any]) -> Path:
    cat = extracted.get("category", "other")
    fm = [
        "---",
        f'title: "{(extracted.get("title") or "LINE 收件").replace(chr(34), chr(39))}"',
        "type: raw",
        "status: draft",
        f"date: {TS_NOW.strftime('%Y-%m-%d')}",
        f"updated: {TS_NOW.strftime('%Y-%m-%d')}",
        f'ingested_at: "{TS_HUMAN} (UTC+8)"',
        "ingest_source: line",
        f"ingest_extractor: {GEMINI_MODEL}",
        f"category: {cat}",
    ]
    if cat == "ai":
        fm.append(f"ai_subcategory: {extracted.get('ai_subcategory','')}")
    elif cat == "pla":
        fm += [
            f"chapter_suggested: {extracted.get('pla_chapter','')}",
            f"chapter_title: {extracted.get('pla_chapter_title_zh','')}",
            f"trigger_topic_id: {extracted.get('pla_trigger_topic','')}",
            f"lake: {extracted.get('pla_lake','')}",
            f"pool: {extracted.get('pla_pool','')}",
        ]
    fm += [
        f"source_tier: {extracted.get('source_tier','')}",
        f"confidence: {extracted.get('overall_confidence','medium')}",
        f"tags: [{', '.join(extracted.get('tags', []) or [])}]",
        "reviewer: 待指派",
        "---",
        "",
    ]

    body = [
        f"# {extracted.get('title', 'LINE 收件')}",
        "",
        f"**分類**：{cat} ({CATEGORY_LABELS.get(cat,'')})",
        "",
        "> [!summary]",
        f"> {extracted.get('summary_zh', '(no summary)')}",
        "",
        "## 原文",
        "",
        "```",
        message,
        "```",
        "",
    ]

    if fetched:
        body += ["## 抓取的網頁/影片資訊", ""]
        for f in fetched:
            if f.get("error"):
                body.append(f"- ❌ {f['url']} — {f['error']}")
            else:
                body += [
                    f"### {f.get('title') or f['url']}",
                    f"- URL: {f['url']}",
                    f"- 類型: {f.get('kind','web')}",
                    "",
                    f.get("text", ""),
                    "",
                ]

    atoms = extracted.get("atoms", []) or []
    if atoms:
        body += ["## 萃取的 atoms", "", "| 類型 | 主張 | 實體 | 信心 |", "|---|---|---|---|"]
        for a in atoms:
            body.append(
                f"| {a.get('type','')} | {a.get('claim','')} | "
                f"{', '.join(a.get('entities', []) or [])} | {a.get('confidence','')} |"
            )
        body.append("")

    tools = extracted.get("tools_or_entities", []) or []
    if tools:
        body += ["## 提及的工具 / 人物 / 機構", ""]
        for t in tools:
            body.append(f"- {t}")
        body.append("")

    refs = extracted.get("references", []) or []
    if refs:
        body += ["## 引用", ""]
        for r in refs:
            body.append(
                f"- [{r.get('title') or r.get('url')}]({r.get('url')}) ({r.get('kind','')})"
            )
        body.append("")

    paths["md"].parent.mkdir(parents=True, exist_ok=True)
    paths["md"].write_text("\n".join(fm + body) + "\n", encoding="utf-8")
    return paths["md"]


# ----------------------------------------------------------------------------
# HTML writer (per-category color theme)
# ----------------------------------------------------------------------------

HTML_CSS_BASE = """body{font-family:-apple-system,Segoe UI,"PingFang TC","Noto Sans TC",sans-serif;
max-width:780px;margin:24px auto;padding:0 20px;line-height:1.7;background:#fafafa;color:#222}
h1{font-size:22px;border-bottom:3px solid var(--accent);padding-bottom:8px;margin-bottom:4px}
.meta{color:#666;font-size:13px;margin-bottom:18px}
.meta span{margin-right:14px}
.cat-banner{display:inline-block;background:var(--accent);color:#fff;padding:4px 14px;
border-radius:99px;font-weight:600;font-size:13px;margin-bottom:10px}
.summary{background:#fff;border-left:4px solid var(--accent);padding:12px 16px;border-radius:4px;
margin:14px 0;font-size:15px}
section{background:#fff;border:1px solid #e0e0e0;border-radius:6px;padding:14px 18px;margin:14px 0}
section h2{font-size:16px;margin:0 0 10px;color:#333;letter-spacing:.04em}
.atoms{display:grid;gap:8px}
.atom{padding:10px 12px;border-left:3px solid var(--accent);background:#f8f9fb;border-radius:3px}
.atom .type{font-size:11px;background:var(--accent);color:#fff;padding:2px 8px;border-radius:99px;
margin-right:6px;letter-spacing:.05em}
.atom .claim{font-weight:600}
.atom .ent{color:#666;font-size:13px;margin-top:4px}
.tags span{display:inline-block;background:#eef;color:#446;font-size:12px;
padding:2px 10px;border-radius:99px;margin:2px 4px 2px 0}
.tools{display:flex;flex-wrap:wrap;gap:6px}
.tools span{display:inline-block;background:#fff7e0;color:#a55;font-size:13px;
padding:3px 10px;border-radius:4px;border:1px solid #f0d8a0}
table{width:100%;border-collapse:collapse;font-size:14px;margin:6px 0}
th,td{border:1px solid #ddd;padding:6px 10px;text-align:left}
th{background:#f4f4f4}
details{background:#f5f5f5;border-radius:4px;padding:8px 12px;margin-top:10px}
details summary{cursor:pointer;color:#555;font-size:13px}
pre{white-space:pre-wrap;word-break:break-word;font-size:13px;background:#fafafa;
padding:10px;border-radius:4px;border:1px solid #eee}
a{color:var(--accent)}
.badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:3px;
background:#333;color:#fff;margin-right:4px;letter-spacing:.05em}"""

CATEGORY_THEMES = {"ai": "#7b3fbe", "pla": "#c63d36", "other": "#555555"}


def write_html(message: str, fetched: list[dict[str, str]],
               extracted: dict[str, Any], slug: str, paths: dict[str, Any]) -> Path:
    e = lambda s: html.escape(str(s or ""), quote=True)
    cat = extracted.get("category", "other")
    accent = CATEGORY_THEMES.get(cat, "#555")
    css = f":root{{--accent:{accent}}}\n" + HTML_CSS_BASE
    title = extracted.get("title", "LINE 收件")
    atoms = extracted.get("atoms", []) or []
    tools = extracted.get("tools_or_entities", []) or []
    refs = extracted.get("references", []) or []

    badges = [f'<span class="badge">{e(cat.upper())} · {e(CATEGORY_LABELS.get(cat,""))}</span>']
    if cat == "ai" and extracted.get("ai_subcategory"):
        badges.append(f'<span class="badge">{e(extracted["ai_subcategory"])}</span>')
    if cat == "pla":
        if extracted.get("pla_chapter"):
            badges.append(
                f'<span class="badge">{e(extracted["pla_chapter"])} '
                f'{e(extracted.get("pla_chapter_title_zh",""))}</span>'
            )
        if extracted.get("pla_trigger_topic"):
            badges.append(f'<span class="badge">{e(extracted["pla_trigger_topic"])}</span>')
    if extracted.get("source_tier"):
        badges.append(f'<span class="badge">來源 {e(extracted["source_tier"])}</span>')
    if extracted.get("overall_confidence"):
        badges.append(f'<span class="badge">信心 {e(extracted["overall_confidence"])}</span>')

    tags_html = " ".join(f"<span>{e(t)}</span>" for t in (extracted.get("tags") or []))
    tools_html = "".join(f"<span>{e(t)}</span>" for t in tools)

    atoms_html = ""
    for a in atoms:
        ents = ", ".join(a.get("entities", []) or [])
        atoms_html += (
            f'<div class="atom">'
            f'<span class="type">{e(a.get("type",""))}</span>'
            f'<span class="claim">{e(a.get("claim",""))}</span>'
            f'<div class="ent">實體：{e(ents) or "—"}　·　信心：{e(a.get("confidence",""))}</div>'
            f'</div>'
        )

    fetched_html = ""
    for f in fetched:
        if f.get("error"):
            fetched_html += f'<p>❌ <a href="{e(f["url"])}">{e(f["url"])}</a> — {e(f["error"])}</p>'
        else:
            kind_label = "🎬 YouTube 影片" if f.get("kind") == "youtube" else "🌐 網頁"
            fetched_html += (
                f'<h3>{kind_label}：<a href="{e(f["url"])}">{e(f.get("title") or f["url"])}</a></h3>'
                f'<p style="color:#666;font-size:14px">{e(f.get("text",""))[:600]}…</p>'
            )

    refs_html = "".join(
        f'<li><a href="{e(r.get("url",""))}">{e(r.get("title") or r.get("url"))}</a> · {e(r.get("kind",""))}</li>'
        for r in refs
    )

    repo_name = "agent-broker" if paths["repo"] == REPO_AI else "pla-military-analysis"

    page = f"""<!DOCTYPE html><html lang="zh-Hant"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} — LINE 收件</title>
<style>{css}</style></head><body>
<div class="cat-banner">{e(CATEGORY_LABELS.get(cat,""))}</div>
<h1>{e(title)}</h1>
<div class="meta">
  <span>📅 {e(TS_HUMAN)}</span>
  <span>📥 LINE</span>
  <span>📂 {e(repo_name)}</span>
  <span>🤖 {e(GEMINI_MODEL)}</span>
</div>
<div>{"".join(badges)}</div>
<div class="summary">{e(extracted.get("summary_zh", ""))}</div>

{f'<section><h2>🧬 萃取的關鍵主張（atoms）</h2><div class="atoms">{atoms_html}</div></section>' if atoms else ""}

{f'<section><h2>🛠 工具 / 人物 / 機構</h2><div class="tools">{tools_html}</div></section>' if tools_html else ""}

{f'<section><h2>🌐 抓取內容</h2>{fetched_html}</section>' if fetched_html else ""}

{f'<section><h2>🔖 引用</h2><ul>{refs_html}</ul></section>' if refs_html else ""}

{f'<section><h2>🏷 標籤</h2><div class="tags">{tags_html}</div></section>' if tags_html else ""}

<section><h2>📜 原始訊息</h2>
<details open><summary>展開原文</summary><pre>{e(message)}</pre></details></section>

</body></html>"""

    paths["html"].parent.mkdir(parents=True, exist_ok=True)
    paths["html"].write_text(page, encoding="utf-8")
    return paths["html"]


# ----------------------------------------------------------------------------
# CSV writer (per-category schema)
# ----------------------------------------------------------------------------

CSV_HEADERS_AI = [
    "timestamp", "title", "summary_zh", "ai_subcategory",
    "tools_or_entities", "atoms_count", "tags", "urls",
    "source_tier", "confidence", "raw_md_path", "html_path",
]
CSV_HEADERS_PLA = [
    "timestamp", "title", "summary_zh", "chapter", "chapter_title",
    "trigger_topic_id", "lake", "pool", "atoms_count", "entities", "tags",
    "urls", "source_tier", "confidence", "raw_md_path", "html_path",
]
CSV_HEADERS_OTHER = [
    "timestamp", "title", "summary_zh", "tags", "atoms_count",
    "urls", "confidence", "raw_md_path", "html_path",
]


def append_csv(extracted: dict[str, Any], fetched: list[dict[str, str]],
               paths: dict[str, Any]) -> Path:
    cat = extracted.get("category", "other")
    repo = paths["repo"]
    atoms = extracted.get("atoms", []) or []
    urls = "; ".join(f["url"] for f in fetched)
    tags_str = "; ".join(extracted.get("tags", []) or [])

    paths["csv"].parent.mkdir(parents=True, exist_ok=True)
    new_file = not paths["csv"].exists()

    with paths["csv"].open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        if cat == "ai":
            if new_file:
                w.writerow(CSV_HEADERS_AI)
            tools_str = "; ".join(extracted.get("tools_or_entities", []) or [])
            w.writerow([
                TS_HUMAN, extracted.get("title", ""), extracted.get("summary_zh", ""),
                extracted.get("ai_subcategory", ""), tools_str, len(atoms),
                tags_str, urls, extracted.get("source_tier", ""),
                extracted.get("overall_confidence", ""),
                str(paths["md"].relative_to(repo)),
                str(paths["html"].relative_to(repo)),
            ])
        elif cat == "pla":
            if new_file:
                w.writerow(CSV_HEADERS_PLA)
            ents = sorted({ent for a in atoms for ent in (a.get("entities") or [])})
            w.writerow([
                TS_HUMAN, extracted.get("title", ""), extracted.get("summary_zh", ""),
                extracted.get("pla_chapter", ""), extracted.get("pla_chapter_title_zh", ""),
                extracted.get("pla_trigger_topic", ""), extracted.get("pla_lake", ""),
                extracted.get("pla_pool", ""), len(atoms), "; ".join(ents), tags_str,
                urls, extracted.get("source_tier", ""),
                extracted.get("overall_confidence", ""),
                str(paths["md"].relative_to(repo)),
                str(paths["html"].relative_to(repo)),
            ])
        else:
            if new_file:
                w.writerow(CSV_HEADERS_OTHER)
            w.writerow([
                TS_HUMAN, extracted.get("title", ""), extracted.get("summary_zh", ""),
                tags_str, len(atoms), urls,
                extracted.get("overall_confidence", ""),
                str(paths["md"].relative_to(repo)),
                str(paths["html"].relative_to(repo)),
            ])
    return paths["csv"]


# ----------------------------------------------------------------------------
# Git (operates on the SINGLE repo for this category)
# ----------------------------------------------------------------------------

def git(repo: Path, *args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def git_publish(paths: dict[str, Any], summary: str) -> str:
    if DRY_RUN:
        return "dry-run (skipped)"
    repo = paths["repo"]
    git(repo, "config", "user.name", GIT_NAME)
    git(repo, "config", "user.email", GIT_EMAIL)
    git(repo, "pull", "--rebase", "--autostash")
    git(repo, "add", *paths["git_paths"])
    code, out, err = git(repo, "commit", "-m", f"line ingest {TS_FILE}: {summary[:60]}")
    if code != 0 and "nothing to commit" not in (out + err).lower():
        return f"git commit failed: {err.strip()[:160]}"
    code, out, err = git(repo, "push")
    if code != 0:
        return f"git push failed: {err.strip()[:160]}"
    return "ok"


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) > 1:
        message = sys.argv[1]
    else:
        message = sys.stdin.read()
    message = message.strip()
    if not message:
        print("(empty message; skipped)")
        return 0

    urls = URL_RE.findall(message)
    fetched = [fetch_url(u) for u in urls[:3]]

    extracted = call_gemini(message, fetched)
    if extracted.get("error"):
        print(f"⚠️ 萃取失敗：{extracted['error']}（仍會原文歸檔到 other）")
        extracted = {
            "category": "other",
            "title": message[:30],
            "summary_zh": "(萃取失敗，僅保留原文)",
            "atoms": [], "tags": [], "tools_or_entities": [], "references": [],
            "source_tier": "", "overall_confidence": "low",
        }

    cat = extracted.get("category", "other")
    if cat not in ("ai", "pla", "other"):
        cat = "other"
        extracted["category"] = cat

    slug = slugify(extracted.get("title", "msg")) or hashlib.md5(message.encode()).hexdigest()[:8]
    paths = paths_for(cat, slug)

    md_path = write_markdown(message, fetched, extracted, slug, paths)
    html_path = write_html(message, fetched, extracted, slug, paths)
    csv_path = append_csv(extracted, fetched, paths)

    summary = extracted.get("summary_zh", "")[:60]
    git_status = git_publish(paths, summary)

    n_atoms = len(extracted.get("atoms", []) or [])
    repo_name = "agent-broker" if paths["repo"] == REPO_AI else "pla-military-analysis"

    if cat == "ai":
        sub = extracted.get("ai_subcategory", "")
        cat_line = f"分類：AI · {sub}" if sub else "分類：AI"
    elif cat == "pla":
        chap = extracted.get("pla_chapter", "")
        chap_zh = extracted.get("pla_chapter_title_zh", "")
        cat_line = f"分類：PLA · {chap} {chap_zh}".strip()
    else:
        cat_line = "分類：其他"

    title = extracted.get("title", "")
    reply_lines = [
        f"✅ 已歸檔：{title}" if title else "✅ 已歸檔",
        f"{cat_line} → {repo_name}",
        f"萃取：{n_atoms} atoms · git {git_status}",
        f"HTML：{paths['html'].relative_to(paths['repo'])}",
    ]
    print("\n".join(reply_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
