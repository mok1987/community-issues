"""1~3면 기사에 붙일 유튜브 썸네일 (뉴스 사진 대신).

원칙
- 이슈에 이미 유튜브 인기 영상이 묶여 있으면 그 영상을 쓴다 (검색 없음, 가장 정확).
- 없으면 공식 API로 최근 2일 한국 영상을 검색하고, 영상 제목에 이슈 핵심 단어가 충분히 겹칠 때만 쓴다.
  애매하면 쓰지 않는다 (엉뚱한 썸네일보다 없는 게 낫다).
- '확인 안 됨' 여부와 상관없이 붙인다 (2026-11-18 사용자 결정).
- 검색 1회 = 할당량 100단위(하루 10,000). 그래서 같은 이슈는 처음 한 번만 찾고 결과를 data/thumbs.json 에 저장한다.
  이슈 이름은 매번 바뀔 수 있어 '겹치는 글 주소'로 같은 이슈를 알아본다. 한 번 실행에 새 검색은 최대 3번.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .youtube import API, TIMEOUT, video_id, watch_url

KEEP_HOURS = 48
MAX_SEARCHES = 3
NEWS_CHANNEL = re.compile(r"뉴스|NEWS|News|news|방송|YTN|KBS|MBC|SBS|JTBC|MBN|TV조선|채널A|연합|한겨레|조선|중앙|동아|경향")
# 검색어·비교에서 뺄 흔한 말 (기사 제목 꼬리말 등)
STOP = {"관련", "소식", "논란", "의혹", "이야기", "화제", "최근", "대한", "위한", "통해", "따른", "및", "등", "대책으로",
        "검토", "발표", "올해", "오늘", "내일", "어제", "이번", "공개", "확산", "제기", "주장", "이유", "사람들", "온라인", "커뮤니티"}
PARTICLES = ("으로", "에서", "에게", "까지", "부터", "이며", "이고", "과", "와", "을", "를", "이", "가", "은", "는", "의", "에", "로", "도", "만")


def keywords(text: str) -> list[str]:
    """제목에서 핵심 낱말(2글자 이상)을 순서대로. 조사·흔한 꼬리말은 뺀다."""
    out = []
    for w in re.split(r"[\s,·…\"'“”‘’()\[\]<>!?.:;/]+", text or ""):
        for p in PARTICLES:
            if len(w) > len(p) + 1 and w.endswith(p):
                w = w[: -len(p)]
                break
        if len(w) >= 2 and w not in STOP and w not in out:
            out.append(w)
    return out


def match_score(words: list[str], title: str) -> int:
    flat = re.sub(r"\s+", "", title or "").lower()
    return sum(1 for w in words if w.lower() in flat)


def pick(items: list[dict], words: list[str]) -> dict | None:
    """검색 결과 중 핵심 단어가 가장 많이 겹치는 영상. 2개 이상(핵심 단어가 1개뿐이면 그 1개) 겹쳐야 쓴다."""
    need = 2 if len(words) >= 2 else 1
    best, best_key = None, None
    for it in items:
        sn = it.get("snippet", {})
        vid = (it.get("id") or {}).get("videoId")
        if not vid:
            continue
        s = match_score(words, sn.get("title", ""))
        if s < need:
            continue
        key = (s, bool(NEWS_CHANNEL.search(sn.get("channelTitle", ""))))
        if best_key is None or key > best_key:
            best, best_key = it, key
    return best


def as_thumb(vid: str, title: str, channel: str) -> dict:
    return {"id": vid, "url": watch_url(vid), "title": title, "channel": channel,
            "img": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}


def search(api_key: str, query: str, now: datetime) -> list[dict]:
    after = (now - timedelta(hours=KEEP_HOURS)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resp = requests.get(f"{API}/search", timeout=TIMEOUT, params={
        "part": "snippet", "q": query, "type": "video", "regionCode": "KR", "relevanceLanguage": "ko",
        "publishedAfter": after, "maxResults": 10, "safeSearch": "strict", "order": "relevance", "key": api_key,
    })
    resp.raise_for_status()
    return resp.json().get("items", [])


def from_posts(it: dict) -> dict | None:
    """이슈에 묶인 유튜브 인기 영상이 있으면 그것 (제목 끝의 ' — 채널명'은 나눈다)."""
    for p in it.get("posts", []):
        if p.get("source") == "youtube" and video_id(p.get("url", "")):
            title, _, channel = p["title"].rpartition(" — ")
            return as_thumb(video_id(p["url"]), title or p["title"], channel if title else "")
    return None


def load(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def apply(issues: list[dict], api_key: str | None, path: Path, at_iso: str,
          searcher=None, lead: int = 3) -> int:
    """앞의 lead개 이슈에 thumb 를 붙인다. 새로 검색한 횟수를 돌려준다."""
    now = datetime.fromisoformat(at_iso)
    cache = [c for c in load(path) if _fresh(c, now)]
    searches = 0
    for it in issues[:lead]:
        urls = {p["url"] for p in it.get("posts", [])}
        direct = from_posts(it)
        if direct:
            it["thumb"] = direct
            continue
        hit = next((c for c in cache if urls & set(c.get("urls", []))), None)
        if hit is None and api_key and searches < MAX_SEARCHES:
            words = keywords(it.get("headline", ""))
            searches += 1
            try:
                items = (searcher or (lambda q: search(api_key, q, now)))(" ".join(words[:4]))
                chosen = pick(items, words)
            except Exception as e:  # noqa: BLE001 - 썸네일이 없어도 페이지는 갱신
                print(f"[썸네일] 검색 실패: {e}")
                continue
            thumb = None
            if chosen:
                sn = chosen["snippet"]
                thumb = as_thumb(chosen["id"]["videoId"], sn.get("title", ""), sn.get("channelTitle", ""))
            hit = {"at": at_iso, "urls": [], "thumb": thumb, "q": " ".join(words[:4])}
            cache.append(hit)
        if hit is not None:
            hit["urls"] = sorted(set(hit.get("urls", [])) | urls)
            if hit.get("thumb"):
                it["thumb"] = hit["thumb"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return searches


def _fresh(c: dict, now: datetime) -> bool:
    try:
        return now - datetime.fromisoformat(c["at"]) <= timedelta(hours=KEEP_HOURS)
    except (KeyError, ValueError):
        return False
