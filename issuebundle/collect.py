"""인기글 목록에서 '제목 + 링크'만 수집한다."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .sources import Source

# 정체를 숨기지 않는 User-Agent (판례상 우회 수집은 불리하다). 연락처는 저장소 주소로 바꿔 쓸 것.
USER_AGENT = "IssueBundleBot/0.1 (+https://github.com/YOUR_ID/community-issues)"
TIMEOUT = 15
DELAY_BETWEEN_SITES = 3  # 초. 사이트당 30분에 1번만 요청한다.

_NOISE = re.compile(r"\s*[\[\(]\s*\d+\s*[\]\)]\s*$")  # 제목 끝 댓글 수 "[12]" "(12)"
_SPACES = re.compile(r"\s+")


@dataclass
class Post:
    url: str
    title: str
    source: str   # Source.key
    rank: int     # 목록에서의 순서 (0 = 맨 위)
    comment_count: int | None = None  # 알 수 있을 때만 (유튜브)


def clean_title(text: str) -> str:
    text = _SPACES.sub(" ", text).strip()
    text = _NOISE.sub("", text).strip()
    return text


def normalize_url(href: str, base: str) -> str:
    absolute = urljoin(base, href)
    parts = urlsplit(absolute)
    # 추적용 fragment 제거, 쿼리는 게시글 번호가 들어있을 수 있어 유지
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def extract_posts(html: str, source: Source, limit: int = 50) -> list[Post]:
    """목록 HTML에서 게시글 링크를 골라낸다. 같은 글에 링크가 여러 개면 가장 긴 텍스트를 제목으로 쓴다."""
    pattern = re.compile(source.post_pattern)
    soup = BeautifulSoup(html, "html.parser")
    best: dict[str, str] = {}
    order: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not pattern.search(href):
            continue
        url = normalize_url(href, source.list_url)
        title = clean_title(a.get_text(" "))
        if url not in best:
            order.append(url)
            best[url] = title
        elif len(title) > len(best[url]):
            best[url] = title
    posts = []
    for url in order:
        title = best[url]
        if len(title) < 4 or title.isdigit():
            continue
        posts.append(Post(url=url, title=title, source=source.key, rank=len(posts)))
        if len(posts) >= limit:
            break
    return posts


def robots_check(source: Source, session: requests.Session) -> str | None:
    """수집해도 되면 None, 아니면 건너뛰는 이유를 돌려준다."""
    parts = urlsplit(source.list_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        resp = session.get(robots_url, timeout=TIMEOUT)
    except requests.RequestException as e:
        return f"사이트 접속 실패({e.__class__.__name__}), 건너뜀"  # 확인 못 하면 보수적으로
    if resp.status_code >= 500:
        return f"robots.txt 확인 실패(HTTP {resp.status_code}), 건너뜀"
    if resp.status_code >= 400:
        return None  # robots.txt가 없으면 제한 없음 (관례)
    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())
    if not rp.can_fetch(USER_AGENT, source.list_url):
        return "robots.txt가 막고 있어 건너뜀"
    return None


def fetch_source(source: Source, session: requests.Session) -> tuple[list[Post], str]:
    """(수집한 글, 상태 메시지)를 돌려준다. 실패해도 예외 대신 빈 목록을 준다."""
    reason = robots_check(source, session)
    if reason:
        return [], reason
    try:
        resp = session.get(source.list_url, timeout=TIMEOUT)
    except requests.RequestException as e:
        return [], f"요청 실패: {e.__class__.__name__}"
    if resp.status_code != 200:
        return [], f"HTTP {resp.status_code}"
    resp.encoding = resp.apparent_encoding or resp.encoding
    posts = extract_posts(resp.text, source)
    if not posts:
        return [], "글 링크를 찾지 못함 (post_pattern 확인 필요)"
    return posts, f"{len(posts)}개"


def collect_all(sources: list[Source]) -> tuple[list[Post], dict[str, str]]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})
    all_posts: list[Post] = []
    status: dict[str, str] = {}
    for i, source in enumerate(sources):
        if i:
            time.sleep(DELAY_BETWEEN_SITES)
        posts, msg = fetch_source(source, session)
        all_posts.extend(posts)
        status[source.key] = msg
    return all_posts, status


def to_dict(post: Post) -> dict:
    return asdict(post)
