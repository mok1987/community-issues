"""온라인에서 화제인 인물 TOP 3.

안전장치
- AI가 제목에서 '공인'(연예인·정치인·기업인·운동선수 등)만 고른다. 일반인·미성년자·사건 피해자는 제외.
- 한국어 위키백과에 문서가 있는 사람만 남긴다 (공인 여부 확인 + '누구인지' 설명을 위키백과에서 가져옴).
- 사진은 위키미디어 공용(Commons)에 올라온 자유 이용 사진만 쓴다. 출처 링크를 함께 보여준다.
  위키백과 자체에만 있는 사진(비자유 저작물 가능성)은 쓰지 않고, 사진이 없으면 화면에서 이름 첫 글자로 대신한다.
"""

from __future__ import annotations

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


def mentions(name: str, titles: list[str]) -> int:
    return sum(1 for t in titles if name in t)


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
