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

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .youtube import API, TIMEOUT, video_id, watch_url

KEEP_HOURS = 48
DAILY_SEARCHES = 90  # 유튜브 검색은 하루 100번 따로 한도(미국 서부 자정, 한국 오후 4~5시에 초기화). 여유를 두고 90번에서 멈춘다
LA = ZoneInfo("America/Los_Angeles")
RETRY_HOURS = 2  # 못 찾은 이슈는 2시간 뒤 (그사이 영상이 올라왔을 수 있으니) 다시 찾아본다
MAX_SEARCHES = 3
# 검색으로 찾은 영상은 주요 언론사·방송사 채널 것만 쓴다 (이름에 '뉴스'만 들어간 개인 채널의 자극적인 썸네일 방지)
NEWS_CHANNEL = re.compile(r"YTN|KBS|MBC|SBS|JTBC|MBN|TV조선|채널A|연합뉴스|OBS|CBS|EBS|KTV|한겨레|경향신문|조선일보|중앙일보|"
                          r"동아일보|한국일보|국민일보|서울신문|세계일보|문화일보|한국경제|매일경제|머니투데이|뉴스1|뉴시스|노컷뉴스|"
                          r"이데일리|헤럴드경제|아시아경제|SPOTV|스포티비|tvN|티빙|쿠팡플레이|T1|LCK")
# 검색어·비교에서 뺄 흔한 말 (기사 제목 꼬리말 등)
STOP = {"관련", "소식", "논란", "의혹", "이야기", "화제", "최근", "대한", "위한", "통해", "따른", "및", "등", "대책으로",
        "검토", "발표", "앞두고", "강화", "우려", "혼란", "추진", "종합", "단독", "속보", "결국", "올해", "오늘", "내일", "어제", "이번", "공개", "확산", "제기", "주장", "이유", "사람들", "온라인", "커뮤니티"}
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


def topic_words(it: dict, n: int = 6) -> list[str]:
    """이슈의 핵심 단어: 묶인 글 제목들에 자주 나온 단어 순 (AI가 쓴 제목의 단어는 가산점)."""
    head = keywords(it.get("headline", ""))
    count: dict[str, float] = {w: 2.0 for w in head}
    for p in it.get("posts", []):
        title = p.get("title", "").rpartition(" — ")[0] or p.get("title", "")
        for w in set(keywords(title)):
            count[w] = count.get(w, 0) + 1
    ranked = sorted(count, key=lambda w: (-count[w], head.index(w) if w in head else 99))
    return [w for w in ranked if count[w] >= 2][:n] or head[:n]


def match_score(words: list[str], title: str) -> int:
    flat = re.sub(r"\s+", "", title or "").lower()
    return sum(1 for w in words if w.lower() in flat)


def pick(items: list[dict], words: list[str]) -> dict | None:
    """검색 결과 중 핵심 단어가 가장 많이 겹치는 영상.
    핵심 단어 2개 이상 겹치거나, 1개만 겹쳐도 그게 가장 자주 나온 단어 1~2위면 쓴다 (주요 언론사 채널만이라 이 정도로 충분)."""
    best, best_key = None, None
    for it in items:
        sn = it.get("snippet", {})
        vid = (it.get("id") or {}).get("videoId")
        if not vid:
            continue
        s = match_score(words, sn.get("title", ""))
        ok = s >= 2 or (s == 1 and match_score(words[:2], sn.get("title", "")) == 1)
        if not ok or not NEWS_CHANNEL.search(sn.get("channelTitle", "")):
            continue
        key = (s,)
        if best_key is None or key > best_key:
            best, best_key = it, key
    return best


def as_thumb(vid: str, title: str, channel: str) -> dict:
    # 유튜브 API는 제목을 &quot; 같은 HTML 글자로 준다 → 원래 글자로
    title, channel = html.unescape(title or ""), html.unescape(channel or "")
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


def _budget(path: Path, now: datetime) -> tuple[dict, int]:
    """오늘(유튜브 기준 날짜) 검색한 횟수 기록과 남은 횟수."""
    day = now.astimezone(LA).date().isoformat()
    try:
        rec = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (ValueError, OSError):
        rec = {}
    if rec.get("day") != day:
        rec = {"day": day, "n": 0}
    return rec, max(0, DAILY_SEARCHES - rec["n"])


def apply(issues: list[dict], api_key: str | None, path: Path, at_iso: str,
          searcher=None, lead: int = 3) -> int:
    """앞의 lead개 이슈에 thumb 를 붙인다. 새로 검색한 횟수를 돌려준다."""
    now = datetime.fromisoformat(at_iso)
    count_path = path.with_name("yt_search_count.json")
    rec, left = _budget(count_path, now)
    cache = [c for c in load(path) if _fresh(c, now)]
    # 못 찾았던 이슈는 2시간 지나면 기록을 지워서 다시 찾게 한다
    cache = [c for c in cache if c.get("thumb") or _age(c, now) < timedelta(hours=RETRY_HOURS)]
    searches, taken = 0, set()  # taken: 이미 다른 면에 쓴 영상 (같은 썸네일이 두 면에 나오지 않게)
    for it in issues[:lead]:
        urls = {p["url"] for p in it.get("posts", [])}
        direct = from_posts(it)
        if direct and direct["id"] not in taken:
            it["thumb"] = direct
            taken.add(direct["id"])
            continue
        # 같은 이슈 = 지금 글의 절반 이상이 그때 이슈에 있던 글
        hit = next((c for c in cache if len(urls & set(c.get("urls", []))) >= max(1, len(urls) / 2)
                    and (c.get("thumb") or {}).get("id") not in taken), None)
        if hit is None and api_key and searches < min(MAX_SEARCHES, left):
            words = topic_words(it)
            searches += 1
            try:
                items = (searcher or (lambda q: search(api_key, q, now)))(" ".join(words[:3]))
                chosen = pick([i for i in items if (i.get("id") or {}).get("videoId") not in taken], words)
            except Exception as e:  # noqa: BLE001 - 썸네일이 없어도 페이지는 갱신
                print(f"[썸네일] 검색 실패: {e}")
                continue
            thumb = None
            if chosen:
                sn = chosen["snippet"]
                thumb = as_thumb(chosen["id"]["videoId"], sn.get("title", ""), sn.get("channelTitle", ""))
            hit = {"at": at_iso, "urls": [], "thumb": thumb, "q": " ".join(words[:3])}
            cache.append(hit)
        if hit is not None:
            hit["urls"] = sorted(urls)  # 지금 이슈의 글로 바꿔 둔다 (계속 합치면 다른 이슈까지 같은 이슈로 보임)
            if hit.get("thumb"):
                t = hit["thumb"]
                it["thumb"] = hit["thumb"] = as_thumb(t["id"], t.get("title", ""), t.get("channel", ""))
                taken.add(t["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    rec["n"] += searches
    count_path.write_text(json.dumps(rec), encoding="utf-8")
    if searches:
        print(f"[썸네일] 오늘 유튜브 검색 {rec['n']}/{DAILY_SEARCHES}번")
    return searches


def _age(c: dict, now: datetime) -> timedelta:
    try:
        return now - datetime.fromisoformat(c["at"])
    except (KeyError, ValueError):
        return timedelta(days=999)


def _fresh(c: dict, now: datetime) -> bool:
    try:
        return now - datetime.fromisoformat(c["at"]) <= timedelta(hours=KEEP_HOURS)
    except (KeyError, ValueError):
        return False
