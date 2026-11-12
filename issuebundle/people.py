"""온라인에서 화제인 인물 TOP 3.

안전장치
- AI가 제목에서 '공인'(연예인·정치인·기업인·운동선수 등)만 고른다. 일반인·미성년자·사건 피해자는 제외.
- 한국어 위키백과에 문서가 있는 사람만 남긴다 (공인 여부 확인 + '누구인지' 설명을 위키백과에서 가져옴).
- 사진은 위키미디어 공용(Commons)에 올라온 자유 이용 사진만 쓴다. 출처 링크를 함께 보여준다.
  위키백과 자체에만 있는 사진(비자유 저작물 가능성)은 쓰지 않고, 사진이 없으면 화면에서 이름 첫 글자로 대신한다.
"""

from __future__ import annotations

import html
import os
import re
from typing import Callable
from urllib.parse import quote

import requests

from .cluster import LLM, parse_json

WIKI_API = "https://ko.wikipedia.org/api/rest_v1/page/summary/"
# 위키미디어 정책: 연락 가능한 User-Agent
WIKI_UA = "YojeummwoBot/0.1 (https://github.com/mok1987/community-issues)"

PROMPT = """너는 인터넷 커뮤니티를 안 보는 50~60대에게 '요즘 온라인에서 화제인 사람'을 알려주는 편집자다.

아래 제목들에서 지금 가장 많이 이야기되는 '공인'을 많이 언급된 순서로 최대 6명 골라라.

규칙:
- 공인만: 연예인, 방송인, 운동선수, 정치인, 기업인, 유명 유튜버 등 이미 널리 알려진 사람.
- 절대 넣지 말 것: 일반인, 미성년자(만 18세 미만), 사건·사고의 피해자, 이름이 알려지지 않은 사람, 가상 인물.
- name: 위키백과 문서 제목처럼 정확한 실명 또는 활동명 (예: 손흥민, 아이유)
- why: 왜 화제인지 한 문장 (35자 이내). 제목들에서 알 수 있는 사실만, 확인 안 된 소문은 "~라는 이야기가 돌고 있다"로.
- 비하·조롱 표현 없이 중립적으로. 정치인도 한쪽 편을 들지 말 것.

JSON으로만 답하라: {{"people": [{{"name": "...", "why": "..."}}]}}

제목:
{lines}
"""

Fetch = Callable[[str], dict | None]


def wiki_fetch(title: str) -> dict | None:
    try:
        resp = requests.get(WIKI_API + quote(title.replace(" ", "_")), timeout=15,
                            headers={"User-Agent": WIKI_UA, "Accept": "application/json"})
    except requests.RequestException:
        return None
    return resp.json() if resp.status_code == 200 else None


def commons_photo(summary: dict) -> str | None:
    """위키미디어 공용(자유 이용) 사진의 썸네일 주소만 돌려준다."""
    src = ((summary.get("thumbnail") or {}).get("source") or "")
    return src if "/wikipedia/commons/" in src else None


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def mentions(name: str, titles: list[str]) -> int:
    """'젠슨 황'과 '젠슨황'처럼 띄어쓰기가 달라도 같은 사람으로 센다."""
    key = _squash(name)
    return sum(1 for t in titles if key and key in _squash(t))


def titles_about(name: str, titles: list[str], limit: int = 25) -> list[str]:
    key = _squash(name)
    return [t for t in titles if key and key in _squash(t)][:limit]


# ---------- 인물 최신 소식: 네이버 뉴스 검색 공식 API (키가 있을 때만) ----------
NAVER_NEWS = "https://openapi.naver.com/v1/search/news.json"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


def naver_news(name: str, client_id: str | None = None, secret: str | None = None, n: int = 10) -> list[str]:
    """'제목 — 요약' 문자열 목록 (최신순). 키가 없거나 실패하면 빈 목록."""
    client_id = client_id or (os.environ.get("NAVER_CLIENT_ID") or "").strip()
    secret = secret or (os.environ.get("NAVER_CLIENT_SECRET") or "").strip()
    if not (client_id and secret):
        return []
    try:
        resp = requests.get(NAVER_NEWS, params={"query": name, "display": n, "sort": "date"}, timeout=15,
                            headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": secret})
        items = resp.json().get("items", []) if resp.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return []
    return [f"{_clean(i.get('title'))} — {_clean(i.get('description'))[:120]}" for i in items]


WHY_PROMPT = """너는 인터넷을 안 보는 50~60대에게 '이 사람이 왜 요즘 화제인지' 한두 문장으로 알려주는 기자다.

인물마다 [커뮤니티 글 제목]과 [최신 뉴스]가 주어진다. 이를 보고 '지금 가장 많이 이야기되는 구체적인 일'을 써라.

규칙:
- 막연하게 쓰지 말고 무슨 일인지 구체적으로 (예: "맥도날드에서 랩으로 주문하는 영상이 퍼지며 화제예요").
- 여러 이야기가 있으면 가장 많이 언급되고 최근인 것 하나를 고르고, 필요하면 두 번째를 짧게 덧붙여라.
- 제목과 뉴스에 있는 사실만 써라. 지어내지 마라.
- 확인되지 않은 의혹·소문은 단정하지 말고 "~라는 보도가 나와", "~ 의혹이 제기돼"처럼 써라.
- 비하·조롱·욕설 없이 중립적으로. 정치인도 한쪽 편을 들지 마라.
- 60자 이내. 문장 끝은 부드러운 존댓말(~했어요, ~화제예요, ~나왔어요)로 맺어라. 반말 금지.

JSON으로만 답하라: {{"인물이름": "왜 화제인지"}}

{blocks}
"""


def describe(people_list: list[dict], titles: list[str], llm: LLM, news_fn=naver_news) -> None:
    """인물별 관련 제목 + 최신 뉴스로 '왜 화제' 문장을 다시 쓴다 (실패하면 기존 문장 유지)."""
    if not people_list:
        return
    blocks = []
    for p in people_list:
        about = titles_about(p["name"], titles)
        news = news_fn(p["name"])
        p["news_used"] = bool(news)
        blocks.append(f"### {p['name']} ({p['who']})\n[커뮤니티 글 제목]\n" + "\n".join(f"- {t}" for t in about)
                      + "\n[최신 뉴스]\n" + ("\n".join(f"- {n}" for n in news) if news else "- (없음)"))
    try:
        raw = parse_json(llm(WHY_PROMPT.format(blocks="\n\n".join(blocks))))
    except Exception as e:  # noqa: BLE001
        print(f"[경고] 인물 '왜 화제' 다시 쓰기 실패: {e}")
        return
    if not isinstance(raw, dict):
        return
    by_key = {_squash(k): v for k, v in raw.items() if isinstance(v, str) and v.strip()}
    for p in people_list:
        why = by_key.get(_squash(p["name"]))
        if why:
            p["why"] = why.strip()[:80]


def pick(titles: list[str], llm: LLM, fetch: Fetch = wiki_fetch, limit: int = 3) -> list[dict]:
    titles = list(dict.fromkeys(t for t in titles if t))[:300]
    if not titles:
        return []
    try:
        raw = parse_json(llm(PROMPT.format(lines="\n".join(f"- {t}" for t in titles))))
    except Exception as e:  # noqa: BLE001
        print(f"[경고] 화제 인물 고르기 실패: {e}")
        return []
    out, seen = [], set()
    for p in (raw.get("people") or []) if isinstance(raw, dict) else []:
        name = (p.get("name") or "").strip() if isinstance(p, dict) else ""
        if not name or name in seen or len(name) > 20:
            continue
        seen.add(name)
        n = mentions(name, titles)
        if n == 0:          # 제목에 실제로 없는 이름(지어낸 이름)은 버림
            continue
        s = fetch(name)
        if not s or s.get("type") == "disambiguation" or not s.get("description"):
            continue        # 위키백과 문서가 없거나 동명이인 안내 문서면 버림 (공인 확인 실패)
        out.append({
            "name": s.get("title") or name,
            "who": re.sub(r"\s+", " ", s.get("description", "")).strip()[:40],
            "why": (p.get("why") or "").strip()[:60],
            "mentions": n,
            "photo": commons_photo(s),
            "wiki": ((s.get("content_urls") or {}).get("mobile") or {}).get("page")
                    or f"https://ko.wikipedia.org/wiki/{quote(name)}",
        })
    out.sort(key=lambda x: -x["mentions"])
    print(f"[인물] 화제 인물 {len(out[:limit])}명")
    return out[:limit]


# ── 구글 검색 연동(Grounding)으로 '왜 화제' 쓰기 ─────────────────────────────
# Gemini가 구글에서 최신 소식을 직접 찾아보고 문장을 쓴다.
# 약관상 응답에 딸려 오는 '구글 검색 추천'(searchEntryPoint)을 화면에 그대로 보여줘야 한다.
# 무료 사용량을 아끼려고 같은 인물은 CACHE_HOURS 동안 다시 검색하지 않는다.

Grounded = Callable[[str], dict]
CACHE_HOURS = 3

GROUND_PROMPT = """구글에서 '{name}'({who})의 최근 소식을 검색해서, 이 사람이 지금 왜 온라인에서 화제인지 알려줘.

참고: 지금 한국 온라인 커뮤니티에 올라온 관련 글 제목들
{titles}

규칙:
- 검색으로 확인한 최근(며칠 이내) 사실 중, 위 제목들과 맞는 가장 화제인 일 하나를 구체적으로.
  (예: "맥도날드에서 랩으로 주문하는 영상이 퍼지며 화제예요")
- 확인되지 않은 의혹·소문은 단정하지 말고 "~라는 보도가 나와"처럼. 비하·조롱 없이 중립적으로, 정치인도 편들지 말 것.
- 인터넷을 잘 안 보는 50~60대도 알아듣게 쉬운 말로, 60자 이내 한 문장, 부드러운 존댓말(~했어요, ~화제예요).
- 문장 하나만 답해. 따옴표·출처 표시·설명 붙이지 마."""


def gemini_grounded(api_key: str, model: str) -> Grounded:
    from .cluster import BASE  # 순환 import 피하려고 여기서
    import time
    url = f"{BASE}/models/{model}:generateContent"

    def call(prompt: str) -> dict:
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}],
                "generationConfig": {"temperature": 0.2}}
        for attempt in range(3):
            resp = requests.post(url, json=body, timeout=120, headers={"x-goog-api-key": api_key})
            if resp.status_code in (429, 500, 503) and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            cand = resp.json()["candidates"][0]
            text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
            meta = cand.get("groundingMetadata") or {}
            return {"text": text,
                    "suggest": (meta.get("searchEntryPoint") or {}).get("renderedContent", ""),
                    "queries": meta.get("webSearchQueries") or []}
        raise RuntimeError("Gemini 검색 호출 재시도 초과")

    return call


def _one_sentence(text: str) -> str:
    text = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", text or "")       # [1] 같은 출처 번호 제거
    line = next((l for l in text.strip().splitlines() if l.strip()), "")
    return line.strip().strip('"“”\'‘’ ').strip()[:80]


def _hours_since(iso: str, now: str) -> float:
    from datetime import datetime
    try:
        return (datetime.fromisoformat(now) - datetime.fromisoformat(iso)).total_seconds() / 3600
    except (TypeError, ValueError):
        return 1e9


def ground(people_list: list[dict], titles: list[str], grounded: Grounded, cache: dict, now: str) -> int:
    """구글 검색으로 '왜 화제'를 덮어쓴다. 캐시(3시간)를 쓰고, 실패한 사람은 기존 문장 유지.
    새로 검색한 횟수를 돌려준다. cache는 그 자리에서 갱신된다."""
    searched = 0
    for p in people_list:
        c = cache.get(p["name"])
        if not (c and _hours_since(c.get("at", ""), now) < CACHE_HOURS):
            about = titles_about(p["name"], titles)[:15]
            try:
                r = grounded(GROUND_PROMPT.format(name=p["name"], who=p.get("who", ""),
                                                  titles="\n".join(f"- {t}" for t in about)))
                searched += 1
            except Exception as e:  # noqa: BLE001
                print(f"[경고] {p['name']} 구글 검색 연동 실패: {e}")
                continue
            why = _one_sentence(r["text"])
            if not (why and r["suggest"]):   # 검색 추천을 못 받으면 약관상 쓸 수 없음
                print(f"[경고] {p['name']} 검색 결과 없음 (검색어 {len(r['queries'])}개)")
                continue
            c = cache[p["name"]] = {"why": why, "suggest": r["suggest"], "at": now}
        p["why"], p["suggest"], p["grounded"] = c["why"], c["suggest"], True
    for name in [n for n, c in cache.items() if _hours_since(c.get("at", ""), now) > 24]:
        del cache[name]
    return searched
