"""화제 이슈의 '댓글 반응'을 출처별로 한 줄 요약한다.

- 상위 이슈 몇 개만, 출처별로 글 1~2개만 읽는다 (요청 수 최소화).
- 웹 커뮤니티: 원문 페이지에서 '댓글 영역'(class/id에 comment·reply·cmt 등)만 텍스트로 읽는다.
  댓글을 자바스크립트로 따로 불러오는 사이트는 비어 있을 수 있고, 그때는 제목 분위기(framing)로 대신한다.
- 유튜브: 공식 API로 인기 댓글을 가져온다.
- 화면에는 댓글 원문을 옮기지 않고 AI가 쓴 요약 한 줄만 보여준다 (저작권·개인정보).
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from . import youtube
from .cluster import LLM, NAMES, parse_json
from .collect import TIMEOUT, USER_AGENT

COMMENT_HINT = re.compile(r"(comment|reply|cmt|repl|댓글)", re.I)
MAX_ISSUES = 6
POSTS_PER_SOURCE = 2
EXCERPT_CHARS = 1500
DELAY = 2

PROMPT = """너는 인터넷 커뮤니티를 안 보는 50~60대 독자에게 '사람들 반응'을 전해주는 기자다.

아래는 이슈별·출처별로 모은 댓글 텍스트 일부다. 출처마다 반응을 한 줄(40자 이내)로 요약해라.
규칙:
- 댓글 문장을 그대로 옮기지 말고 네 말로 요약해라.
- 신조어·은어·욕설·비하 표현을 쓰지 마라.
- 찬반이 갈리면 "찬성과 반대가 갈림, 주로 ~" 처럼 균형 있게 써라. 한쪽 편을 들지 마라.
- 개인의 실명·신상은 쓰지 마라.
- 텍스트가 댓글이 아니거나 내용이 없으면 그 출처는 빼라.

JSON으로만 답하라: {{"이슈ID": {{"출처키": "반응 한 줄"}}}}

{blocks}
"""


class RobotsCache:
    def __init__(self, session: requests.Session):
        self.session, self.cache = session, {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self.cache:
            rp = RobotFileParser()
            try:
                resp = self.session.get(host + "/robots.txt", timeout=TIMEOUT)
                if resp.status_code >= 500:
                    rp = None
                elif resp.status_code >= 400:
                    rp.parse([])
                else:
                    rp.parse(resp.text.splitlines())
            except requests.RequestException:
                rp = None
            self.cache[host] = rp
        rp = self.cache[host]
        return bool(rp and rp.can_fetch(USER_AGENT, url))


def comment_text(html: str, limit: int = EXCERPT_CHARS) -> str:
    """페이지에서 댓글 영역 텍스트만 뽑는다. 못 찾으면 빈 문자열."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "form", "button"]):
        tag.decompose()
    candidates = []
    for el in soup.find_all(True):
        marks = " ".join(el.get("class", [])) + " " + (el.get("id") or "")
        if COMMENT_HINT.search(marks):
            text = re.sub(r"\s+", " ", el.get_text(" ")).strip()
            if len(text) >= 20:
                candidates.append(text)
    if not candidates:
        return ""
    # 가장 긴 댓글 영역 하나 (보통 댓글 목록 전체를 감싸는 요소)
    return max(candidates, key=len)[:limit]


def gather(issues: list[dict], yt_key: str | None, session: requests.Session | None = None,
           fetch_html=None) -> dict[str, dict[str, str]]:
    """{이슈ID: {출처키: 댓글 텍스트}}"""
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT)
    robots = RobotsCache(session)

    def default_fetch(url: str) -> str:
        if not robots.allowed(url):
            return ""
        time.sleep(DELAY)
        try:
            resp = session.get(url, timeout=TIMEOUT)
        except requests.RequestException:
            return ""
        if resp.status_code != 200:
            return ""
        resp.encoding = resp.apparent_encoding or resp.encoding
        return resp.text

    fetch_html = fetch_html or default_fetch
    out: dict[str, dict[str, str]] = {}
    for it in issues[:MAX_ISSUES]:
        per_source: dict[str, str] = {}
        for c in it["communities"]:
            posts = [p for p in it["posts"] if p["source"] == c["key"]][:POSTS_PER_SOURCE]
            texts = []
            for p in posts:
                if c["key"] == "youtube":
                    vid = youtube.video_id(p["url"])
                    if yt_key and vid:
                        texts.append(" / ".join(youtube.fetch_comments(yt_key, vid)))
                else:
                    html = fetch_html(p["url"])
                    if html:
                        texts.append(comment_text(html))
            joined = " / ".join(t for t in texts if t)[:EXCERPT_CHARS * 2]
            if joined:
                per_source[c["key"]] = joined
        if per_source:
            out[it["id"]] = per_source
    return out


def summarize(texts: dict[str, dict[str, str]], llm: LLM) -> dict[str, dict[str, str]]:
    if not texts:
        return {}
    blocks = []
    for iid, per in texts.items():
        for key, text in per.items():
            blocks.append(f"### 이슈 {iid} / 출처 {key} ({NAMES.get(key, key)})\n{text}")
    raw = parse_json(llm(PROMPT.format(blocks="\n\n".join(blocks))))
    clean: dict[str, dict[str, str]] = {}
    for iid, per in raw.items():
        if iid in texts and isinstance(per, dict):
            clean[iid] = {k: str(v).strip()[:80] for k, v in per.items() if k in texts[iid] and v}
    return clean


def apply(issues: list[dict], summaries: dict[str, dict[str, str]]) -> None:
    for it in issues:
        for c in it["communities"]:
            c["reaction"] = summaries.get(it["id"], {}).get(c["key"], "")


def add_reactions(issues: list[dict], llm: LLM | None, yt_key: str | None) -> int:
    """반응 요약을 채우고, 채운 출처 수를 돌려준다. 실패해도 페이지 갱신은 계속된다."""
    if llm is None or not issues:
        return 0
    try:
        summaries = summarize(gather(issues, yt_key), llm)
    except Exception as e:  # noqa: BLE001
        print(f"[경고] 댓글 반응 요약 실패: {e}")
        return 0
    apply(issues, summaries)
    return sum(len(v) for v in summaries.values())
