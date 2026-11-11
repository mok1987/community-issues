"""유튜브 공식 API(YouTube Data API v3)로 한국 인기 영상과 상위 댓글을 가져온다.

- 크롤링이 아니라 공식 API라서 약관상 안전하다. 무료 할당량은 하루 10,000 단위.
  인기 영상 목록 1회 = 1단위, 영상 1개 댓글 = 1단위 → 30분마다 돌려도 하루 수백 단위.
- 키 발급: Google Cloud Console → API 및 서비스 → YouTube Data API v3 사용 설정 → 사용자 인증 정보 → API 키
"""

from __future__ import annotations

import requests

from .collect import Post

API = "https://www.googleapis.com/youtube/v3"
SKIP_CATEGORIES = {"10"}  # 10 = 음악. 뮤직비디오·음원은 '이슈'가 아니라서 뺀다
TIMEOUT = 20


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def video_id(url: str) -> str | None:
    marker = "watch?v="
    return url.split(marker, 1)[1].split("&", 1)[0] if marker in url else None


def parse_popular(data: dict) -> list[Post]:
    posts = []
    for item in data.get("items", []):
        snip, stats = item.get("snippet", {}), item.get("statistics", {})
        title = (snip.get("title") or "").strip()
        if not title or snip.get("categoryId") in SKIP_CATEGORIES:
            continue
        channel = (snip.get("channelTitle") or "").strip()
        posts.append(Post(
            url=watch_url(item["id"]),
            title=f"{title} — {channel}" if channel else title,
            source="youtube",
            rank=len(posts),
            comment_count=int(stats["commentCount"]) if "commentCount" in stats else None,
        ))
    return posts


def fetch_popular(api_key: str, limit: int = 50) -> tuple[list[Post], str]:
    try:
        resp = requests.get(f"{API}/videos", timeout=TIMEOUT, params={
            "part": "snippet,statistics", "chart": "mostPopular",
            "regionCode": "KR", "maxResults": min(limit, 50), "key": api_key,
        })
    except requests.RequestException as e:
        return [], f"요청 실패: {e.__class__.__name__}"
    if resp.status_code != 200:
        return [], f"API 오류 HTTP {resp.status_code}"
    posts = parse_popular(resp.json())
    return posts, f"{len(posts)}개"


def parse_comments(data: dict) -> list[str]:
    out = []
    for item in data.get("items", []):
        top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        text = (top.get("textOriginal") or "").strip()
        if text:
            out.append(text[:300])
    return out


def fetch_comments(api_key: str, vid: str, n: int = 20) -> list[str]:
    """인기순 상위 댓글. 댓글이 꺼진 영상은 빈 목록."""
    try:
        resp = requests.get(f"{API}/commentThreads", timeout=TIMEOUT, params={
            "part": "snippet", "videoId": vid, "order": "relevance",
            "maxResults": n, "textFormat": "plainText", "key": api_key,
        })
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    return parse_comments(resp.json())
