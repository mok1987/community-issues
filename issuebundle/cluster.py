"""같은 사건을 다룬 글을 '이슈'로 묶고, 커뮤니티를 안 보는 사람도 이해하게 쉽게 설명한다.

- 기본: Gemini API 한 번 호출로 묶기 + 카테고리 + 쉬운 요약 + TOP5 글 쉬운 제목
- API 키가 없거나 실패하면: 글자 유사도로 단순 묶기 (요약 없음)
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Callable

import requests

from .sources import SOURCES

NAMES = {s.key: s.name for s in SOURCES}
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
CATEGORIES = ["정치", "경제", "사회", "문화·연예", "스포츠", "IT·과학", "생활"]
DEFAULT_CATEGORY = "생활"

PROMPT = """너는 인터넷 커뮤니티를 전혀 안 보는 50~60대 독자를 위해 '요즘 화제'를 정리하는 신문 편집자다.

아래는 여러 커뮤니티와 유튜브의 최근 인기글·인기 영상 제목이다. 형식: [글ID] (출처) 제목
★ 표시는 각 출처의 현재 TOP 5 글이다.

할 일 1 — 이슈 묶기:
1. 같은 사건·인물·발표·사고·논란을 다룬 글끼리 하나의 이슈로 묶어라. 애매하면 묶지 마라.
2. 두 곳 이상의 출처에 등장한 이슈를 우선하고, 한 곳에만 있어도 글이 3개 이상이면 포함해라.
3. 사건이 아닌 단순 유머·짤·일상글·음악 영상은 이슈에서 제외해라.
4. 일반인(공인이 아닌 사람)의 실명·얼굴·연락처·신상과 관련된 이슈는 제외해라.

할 일 2 — 쉽게 쓰기 (가장 중요):
- 신조어·줄임말·커뮤니티 은어·밈을 쓰지 마라. 제목에 그런 말이 있으면 풀어서 써라.
- headline: 신문 제목처럼 누가/무엇이 어떻게 됐는지 (25자 이내, 중립적)
- summary: 무슨 일인지 1~2문장. 제목들에서 알 수 있는 사실만, 추측 금지.
- why: 사람들이 왜 이 얘기를 많이 하는지 한 문장 (예: "출근 시간에 수십만 명이 영향을 받아서")
- 확인되지 않은 주장은 "~라는 이야기가 퍼지고 있다"처럼 쓰고 unverified를 true로.
- framing: 출처별로 그 출처 제목들의 분위기를 중립적으로 한 줄. 욕설·비하 표현은 옮기지 마라.
- 정치·젠더 이슈도 한쪽 편을 들지 말고 "각 출처가 이렇게 다룬다"로만 써라.

할 일 3 — ★ 표시된 TOP 5 글 전부에 대해:
- category와, 이 글이 무슨 내용인지 쉬운 말로 바꾼 easy 제목(30자 이내)을 달아라.
- 일반인 신상이 걸린 글이면 easy를 "개인 관련 글"로만 써라.

category는 반드시 다음 중 하나: {categories}
출처 키는 다음 중 하나: {keys}

JSON으로만 답하라:
{{"issues": [{{"headline": "...", "summary": "...", "why": "...", "category": "...",
   "post_ids": ["p1", "p7"], "framing": {{"출처키": "..."}}, "unverified": false}}],
  "top": {{"p3": {{"category": "...", "easy": "..."}}}}}}

제목 목록:
{lines}
"""

LLM = Callable[[str], str]


def gemini_llm(api_key: str, model: str = DEFAULT_MODEL) -> LLM:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def call(prompt: str) -> str:
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        }
        for attempt in range(4):
            resp = requests.post(url, json=body, timeout=180,
                                 headers={"x-goog-api-key": api_key})
            if resp.status_code in (429, 500, 503) and attempt < 3:
                time.sleep(10 * (attempt + 1))  # 무료 티어 분당 제한 대비
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        raise RuntimeError("Gemini 호출 재시도 초과")

    return call


def parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def build_prompt(posts: list[dict], top_urls: set[str]) -> tuple[str, dict[str, dict]]:
    idmap = {f"p{i + 1}": p for i, p in enumerate(posts)}
    lines = "\n".join(
        f"[{pid}] ({p['source']}){' ★' if p['url'] in top_urls else ''} {p['title']}"
        for pid, p in idmap.items())
    keys = ", ".join(sorted({p["source"] for p in posts}))
    prompt = PROMPT.format(lines=lines, keys=keys, categories=", ".join(CATEGORIES))
    return prompt, idmap


def fix_category(value: str | None) -> str:
    value = (value or "").strip()
    if value in CATEGORIES:
        return value
    for c in CATEGORIES:  # "문화" "연예" "IT" 처럼 일부만 온 경우
        if value and (value in c or c.split("·")[0] in value):
            return c
    return DEFAULT_CATEGORY


def score(posts: list[dict]) -> float:
    sources = {p["source"] for p in posts}
    rank_bonus = sum(max(0, 50 - p["best_rank"]) / 50 for p in posts)
    return round(len(sources) * 10 + len(posts) * 2 + rank_bonus, 2)


def _issue(headline: str, summary: str, why: str, category: str, members: list[dict],
           framing: dict[str, str], unverified: bool) -> dict:
    members = sorted(members, key=lambda p: (p["source"], p["best_rank"]))
    keys = sorted({p["source"] for p in members})
    return {
        "headline": headline.strip()[:60],
        "summary": summary.strip(),
        "why": why.strip(),
        "category": fix_category(category),
        "hot": len(keys) >= 2,
        "communities": [{
            "key": k, "name": NAMES.get(k, k),
            "count": sum(1 for p in members if p["source"] == k),
            "framing": (framing.get(k) or "").strip(),
            "reaction": "",          # reactions.py 가 댓글을 읽고 채운다
            "comment_count": sum(p.get("comment_count") or 0 for p in members if p["source"] == k) or None,
        } for k in keys],
        "posts": [{"title": p["title"], "url": p["url"], "source": p["source"],
                   "source_name": NAMES.get(p["source"], p["source"])} for p in members],
        "first_seen": min(p["first_seen"] for p in members),
        "unverified": bool(unverified),
        "score": score(members),
    }


def _finish(issues: list[dict]) -> list[dict]:
    issues.sort(key=lambda x: (x["hot"], x["score"]), reverse=True)
    for i, it in enumerate(issues):
        it["id"] = f"i{i}"
    return issues


def cluster_with_llm(posts: list[dict], llm: LLM, top_urls: set[str] | None = None
                     ) -> tuple[list[dict], dict[str, dict]]:
    """(이슈 목록, {글 url: {category, easy}})"""
    if not posts:
        return [], {}
    top_urls = top_urls or set()
    prompt, idmap = build_prompt(posts, top_urls)
    raw = parse_json(llm(prompt))

    issues, used = [], set()
    for item in raw.get("issues", []):
        # 모델이 지어낸 ID나 이미 다른 이슈에 쓴 글은 버린다
        ids = [i for i in item.get("post_ids", []) if i in idmap and i not in used]
        members = [idmap[i] for i in ids]
        if not members:
            continue
        sources = {p["source"] for p in members}
        if len(sources) < 2 and len(members) < 3:
            continue
        used.update(ids)
        framing = {k: v for k, v in (item.get("framing") or {}).items() if k in sources}
        issues.append(_issue(item.get("headline", ""), item.get("summary", ""), item.get("why", ""),
                             item.get("category"), members, framing, item.get("unverified", True)))

    top_meta = {}
    for pid, meta in (raw.get("top") or {}).items():
        if pid in idmap and isinstance(meta, dict):
            top_meta[idmap[pid]["url"]] = {"category": fix_category(meta.get("category")),
                                           "easy": (meta.get("easy") or "").strip()[:60]}
    return _finish(issues), top_meta


# ---------- API 없이 쓰는 단순 묶기 (대체용) ----------

def _bigrams(title: str) -> set[str]:
    s = re.sub(r"[^0-9A-Za-z가-힣]", "", title.lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def cluster_simple(posts: list[dict], threshold: float = 0.3) -> list[dict]:
    grams = [_bigrams(p["title"]) for p in posts]
    parent = list(range(len(posts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(posts)):
        for j in range(i + 1, len(posts)):
            a, b = grams[i], grams[j]
            if a and b and len(a & b) / len(a | b) >= threshold:
                parent[find(i)] = find(j)

    groups: dict[int, list[dict]] = {}
    for i, p in enumerate(posts):
        groups.setdefault(find(i), []).append(p)

    issues = []
    for members in groups.values():
        if len({p["source"] for p in members}) < 2:
            continue
        headline = min((p["title"] for p in members), key=len)
        issues.append(_issue(headline, "", "", DEFAULT_CATEGORY, members, {}, True))
    return _finish(issues)


def make_issues(posts: list[dict], llm: LLM | None, top_urls: set[str] | None = None
                ) -> tuple[list[dict], dict[str, dict], str]:
    """(이슈 목록, TOP5 글 정보, 사용한 방법)"""
    if llm is not None:
        try:
            issues, top_meta = cluster_with_llm(posts, llm, top_urls)
            return issues, top_meta, "ai"
        except Exception as e:  # noqa: BLE001 - 실패해도 페이지는 갱신되게
            print(f"[경고] AI 묶기 실패, 단순 묶기로 대체: {e}")
    return cluster_simple(posts), {}, "simple"
