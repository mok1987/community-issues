"""같은 사건을 다룬 글을 '이슈'로 묶고 요약한다.

- 기본: Gemini API 한 번 호출로 묶기 + 요약 + 커뮤니티별 제목 분위기 정리
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

PROMPT = """너는 한국 온라인 커뮤니티의 인기글 제목을 보고 '같은 사건/화제'끼리 묶는 편집자다.

아래는 여러 커뮤니티의 최근 인기글 제목이다. 형식: [글ID] (커뮤니티) 제목

규칙:
1. 같은 사건·인물·발표·사고·논란을 다룬 글끼리 하나의 이슈로 묶어라. 애매하면 묶지 마라.
2. 두 개 이상의 커뮤니티에 등장한 이슈를 우선하고, 한 커뮤니티에만 있어도 글이 3개 이상이면 포함해라.
3. 단순 유머·짤·일상글처럼 사건이 아닌 글은 제외해라.
4. 요약은 제목들에서 알 수 있는 사실만 쓰고, 추측하지 마라. 확인되지 않은 주장은 "~라는 글이 퍼지고 있다"처럼 써라.
5. 일반인(공인이 아닌 사람)의 실명·얼굴·연락처·신상과 관련된 이슈는 제외해라.
6. 커뮤니티별 반응(framing)은 그 커뮤니티 '제목들의 분위기'를 중립적으로 한 줄로 써라. 욕설·비하 표현은 옮기지 마라.
7. 정치·젠더 이슈도 한쪽 편을 들지 말고 "각 커뮤니티가 이렇게 다룬다"로만 써라.

JSON으로만 답하라:
{{"issues": [{{
  "headline": "이슈 제목 (25자 이내, 중립적)",
  "summary": "무슨 일인지 1~2문장",
  "category": "연예|스포츠|사회|정치|경제|IT|게임|생활|기타 중 하나",
  "post_ids": ["p1", "p7"],
  "framing": {{"커뮤니티키": "그 커뮤니티 제목들의 분위기 한 줄"}},
  "unverified": true 또는 false (언론 보도로 확인된 사실이 아니라 소문·폭로 단계면 true)
}}]}}

커뮤니티키는 다음 중 하나다: {keys}

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
            resp = requests.post(url, json=body, timeout=120,
                                 headers={"x-goog-api-key": api_key})
            if resp.status_code in (429, 500, 503) and attempt < 3:
                time.sleep(10 * (attempt + 1))  # 무료 티어 분당 제한 대비
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        raise RuntimeError("Gemini 호출 재시도 초과")

    return call


def _ids(posts: list[dict]) -> dict[str, dict]:
    return {f"p{i + 1}": p for i, p in enumerate(posts)}


def build_prompt(posts: list[dict]) -> tuple[str, dict[str, dict]]:
    idmap = _ids(posts)
    lines = "\n".join(f"[{pid}] ({p['source']}) {p['title']}" for pid, p in idmap.items())
    keys = ", ".join(sorted({p["source"] for p in posts}))
    return PROMPT.format(lines=lines, keys=keys), idmap


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def score(posts: list[dict]) -> float:
    communities = {p["source"] for p in posts}
    rank_bonus = sum(max(0, 50 - p["best_rank"]) / 50 for p in posts)
    return round(len(communities) * 10 + len(posts) * 2 + rank_bonus, 2)


def _issue(headline: str, summary: str, category: str, members: list[dict],
           framing: dict[str, str], unverified: bool) -> dict:
    members = sorted(members, key=lambda p: (p["source"], p["best_rank"]))
    communities = sorted({p["source"] for p in members})
    return {
        "headline": headline.strip()[:60],
        "summary": summary.strip(),
        "category": category or "기타",
        "communities": [{"key": k, "name": NAMES.get(k, k),
                         "count": sum(1 for p in members if p["source"] == k),
                         "framing": (framing.get(k) or "").strip()} for k in communities],
        "posts": [{"title": p["title"], "url": p["url"], "source": p["source"],
                   "source_name": NAMES.get(p["source"], p["source"])} for p in members],
        "first_seen": min(p["first_seen"] for p in members),
        "unverified": bool(unverified),
        "score": score(members),
    }


def cluster_with_llm(posts: list[dict], llm: LLM) -> list[dict]:
    if not posts:
        return []
    prompt, idmap = build_prompt(posts)
    raw = _parse_json(llm(prompt))
    issues, used = [], set()
    for item in raw.get("issues", []):
        # 모델이 지어낸 ID나 이미 다른 이슈에 쓴 글은 버린다
        ids = [i for i in item.get("post_ids", []) if i in idmap and i not in used]
        members = [idmap[i] for i in ids]
        if not members:
            continue
        if len({p["source"] for p in members}) < 2 and len(members) < 3:
            continue
        used.update(ids)
        framing = {k: v for k, v in (item.get("framing") or {}).items()
                   if k in {p["source"] for p in members}}
        issues.append(_issue(item.get("headline", ""), item.get("summary", ""),
                             item.get("category", "기타"), members, framing,
                             item.get("unverified", True)))
    issues.sort(key=lambda x: x["score"], reverse=True)
    return issues


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
        issues.append(_issue(headline, "", "기타", members, {}, True))
    issues.sort(key=lambda x: x["score"], reverse=True)
    return issues


def make_issues(posts: list[dict], llm: LLM | None) -> tuple[list[dict], str]:
    """(이슈 목록, 사용한 방법)을 돌려준다."""
    if llm is not None:
        try:
            return cluster_with_llm(posts, llm), "ai"
        except Exception as e:  # noqa: BLE001 - 실패해도 페이지는 갱신되게
            print(f"[경고] AI 묶기 실패, 단순 묶기로 대체: {e}")
    return cluster_simple(posts), "simple"
