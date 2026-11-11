"""화제 이슈의 '댓글 반응'을 출처별로 한 줄 요약한다.

- 상위 이슈 몇 개만, 출처별로 글 1~2개만 읽는다 (요청 수 최소화).
- 웹 커뮤니티: 원문 페이지에서 '댓글 영역'(class/id에 comment·reply·cmt 등)만 텍스트로 읽는다.
  댓글을 자바스크립트로 따로 불러오는 사이트는 비어 있을 수 있고, 그때는 제목 분위기(framing)로 대신한다.
- 유튜브: 공식 API로 인기 댓글을 가져온다.
- 화면에는 댓글 원문을 옮기지 않고 AI가 쓴 요약 한 줄만 보여준다 (저작권·개인정보).
"""

from __future__ import annotations

import json
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

이슈ID(예: i0)와 출처키(예: dcinside)를 그대로 키로 써서 JSON으로만 답하라:
{{"i0": {{"dcinside": "반응 한 줄", "youtube": "반응 한 줄"}}}}

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


# ---------- 사이트별 댓글 읽기 ----------
# 각 함수는 (댓글 문장 목록, 전체 댓글 수 또는 None)을 돌려준다.

_TAG = re.compile(r"<[^>]+>")
_HIDDEN = re.compile(r"(임시글자|회원만 볼 수|비회원은|로그인 후)")
SKIP_NAMES = {"댓글돌이"}  # 디시 광고성 자동 댓글


def _plain(html_text: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", html_text or "")).strip()


def parse_dc_comments(data: dict) -> tuple[list[str], int | None]:
    texts = []
    for c in data.get("comments") or []:
        if c.get("del_yn") == "Y" or c.get("is_delete") not in (None, "0", 0) or c.get("name") in SKIP_NAMES:
            continue
        t = _plain(str(c.get("memo") or ""))
        if t and not t.startswith("dccon"):
            texts.append(t[:200])
    total = data.get("total_cnt")
    return texts, int(total) if str(total or "").isdigit() else None


def parse_theqoo_comments(data: dict) -> tuple[list[str], int | None]:
    texts = []
    for c in data.get("comment_list") or []:
        raw = str(c.get("ct") or "")
        if "commentWarningMessage" in raw:  # 비회원에게 가려진 최근 댓글은 건너뛴다
            continue
        t = _plain(raw)
        if t and not _HIDDEN.search(t):
            texts.append(t[:200])
    total = data.get("comment_count") or data.get("total_count")
    return texts, int(total) if str(total or "").isdigit() else None


def parse_ppomppu_page(html: str) -> tuple[list[str], int | None]:
    m = re.search(r"initialCommentData\s*=\s*", html)
    if not m:
        return [], None
    try:
        data, _ = json.JSONDecoder().raw_decode(html[m.end():])
    except ValueError:
        return [], None
    texts = []
    for c in data.get("comments") or []:
        body = next((c[k] for k in ("memo", "comment", "content", "body", "text", "c_memo") if isinstance(c.get(k), str)), None)
        if body is None:  # 필드 이름을 모르면 가장 긴 문자열 값을 댓글로 본다
            strings = [v for v in c.values() if isinstance(v, str)]
            body = max(strings, key=len) if strings else ""
        t = _plain(body)
        if t:
            texts.append(t[:200])
    total = data.get("total_comment")
    return texts, int(total) if str(total or "").isdigit() else None


_COUNT = re.compile(r"(?:댓글\s*[\(\[]?\s*|총\s*)(\d[\d,]*)\s*(?:개|[\)\]])")


def parse_html_comments(html: str) -> tuple[list[str], int | None]:
    text = comment_text(html)
    if _HIDDEN.search(text):  # 인스티즈: 회원 전용 안내·가림 글자 제거
        text = _HIDDEN.sub(" ", re.sub(r"(임시글자)+", " ", text))
    m = _COUNT.search(text)
    count = int(m.group(1).replace(",", "")) if m else None
    return ([text] if len(text.strip()) >= 20 else []), count


class CommentReader:
    """출처별 방식으로 댓글을 읽는다. robots.txt가 막는 주소는 읽지 않는다."""

    def __init__(self, yt_key: str | None = None, session: requests.Session | None = None):
        self.yt_key = yt_key
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.robots = RobotsCache(self.session)

    def _get(self, url: str) -> requests.Response | None:
        if not self.robots.allowed(url):
            print(f"[반응] robots.txt 금지라 건너뜀: {url}")
            return None
        time.sleep(DELAY)
        try:
            resp = self.session.get(url, timeout=TIMEOUT)
        except requests.RequestException as e:
            print(f"[반응] 요청 실패 {e.__class__.__name__}: {url}")
            return None
        if resp.status_code != 200:
            print(f"[반응] HTTP {resp.status_code}: {url}")
            return None
        return resp

    def _post_json(self, url: str, data: dict, referer: str) -> dict | None:
        if not self.robots.allowed(url):
            print(f"[반응] robots.txt 금지라 건너뜀: {url}")
            return None
        time.sleep(DELAY)
        try:
            resp = self.session.post(url, data=data, timeout=TIMEOUT,
                                     headers={"X-Requested-With": "XMLHttpRequest", "Referer": referer})
            if resp.status_code != 200:
                print(f"[반응] HTTP {resp.status_code}: {url}")
                return None
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"[반응] 댓글 응답 해석 실패 {e.__class__.__name__}: {url}")
            return None

    def read(self, source: str, url: str) -> tuple[list[str], int | None]:
        try:
            if source == "youtube":
                vid = youtube.video_id(url)
                return (youtube.fetch_comments(self.yt_key, vid), None) if self.yt_key and vid else ([], None)
            if source == "dcinside":
                return self._dc(url)
            if source == "theqoo":
                return self._theqoo(url)
            resp = self._get(url)
            if resp is None:
                return [], None
            if source == "ppomppu":
                return parse_ppomppu_page(resp.content.decode("euc-kr", "replace"))
            resp.encoding = resp.apparent_encoding or resp.encoding
            return parse_html_comments(resp.text)
        except Exception as e:  # noqa: BLE001 - 한 사이트 실패가 전체를 멈추지 않게
            print(f"[경고] 댓글 읽기 실패 {source}: {e.__class__.__name__}")
            return [], None

    def _dc(self, url: str) -> tuple[list[str], int | None]:
        resp = self._get(url)
        if resp is None:
            return [], None
        html = resp.text
        gid, no = re.search(r"[?&]id=(\w+)", url), re.search(r"[?&]no=(\d+)", url)
        esno = re.search(r"""name=["']e_s_n_o["'][^>]*value=["']([^"']*)""", html)
        gtype = re.search(r"""name=["']_GALLTYPE_["'][^>]*value=["']([^"']*)""", html)
        if not (gid and no and esno):
            print(f"[반응] 디시 글 정보(id/no/e_s_n_o) 못 찾음: {url}")
            return [], None
        data = self._post_json("https://gall.dcinside.com/board/comment/", {
            "id": gid.group(1), "no": no.group(1), "cmt_id": gid.group(1), "cmt_no": no.group(1),
            "focus_cno": "", "focus_pno": "", "e_s_n_o": esno.group(1), "comment_page": "1",
            "sort": "", "prevCnt": "", "board_type": "", "_GALLTYPE_": gtype.group(1) if gtype else "G",
        }, referer=url)
        return parse_dc_comments(data) if data else ([], None)

    def _theqoo(self, url: str) -> tuple[list[str], int | None]:
        doc = re.search(r"/(\d{6,})", url)
        if not doc:
            return [], None
        data = self._post_json("https://theqoo.net/index.php", {
            "module": "theqoo", "act": "dispTheqooContentCommentListTheqoo",
            "document_srl": doc.group(1), "cpage": "1",
        }, referer=url)
        return parse_theqoo_comments(data) if data else ([], None)


def gather(issues: list[dict], yt_key: str | None, session: requests.Session | None = None,
           fetch_html=None) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, int]]]:
    """({이슈ID: {출처키: 댓글 텍스트}}, {이슈ID: {출처키: 댓글 수}})

    fetch_html 을 주면 (테스트용) 모든 출처를 그 HTML로 읽는다.
    """
    reader = CommentReader(yt_key, session)
    out: dict[str, dict[str, str]] = {}
    counts: dict[str, dict[str, int]] = {}
    for it in issues[:MAX_ISSUES]:
        per_source: dict[str, str] = {}
        for c in it["communities"]:
            posts = [p for p in it["posts"] if p["source"] == c["key"]][:POSTS_PER_SOURCE]
            texts, total = [], 0
            for p in posts:
                if fetch_html is not None:
                    found, n = parse_html_comments(fetch_html(p["url"]))
                else:
                    found, n = reader.read(c["key"], p["url"])
                texts.extend(found)
                total += n or 0
            joined = " / ".join(t for t in texts if t)[:EXCERPT_CHARS * 2]
            if joined:
                per_source[c["key"]] = joined
            if total:
                counts.setdefault(it["id"], {})[c["key"]] = total
            print(f"[반응] {it['id']} {c['key']}: 댓글 {len(texts)}개 읽음" + (f", 전체 {total}개" if total else ""))
        if per_source:
            out[it["id"]] = per_source
    return out, counts


def _norm_issue(key: str, valid: set[str]) -> str | None:
    if key in valid:
        return key
    m = re.search(r"i\d+", key)
    return m.group(0) if m and m.group(0) in valid else None


def _norm_source(key: str, valid: set[str]) -> str | None:
    if key in valid:
        return key
    for k in valid:  # 모델이 출처 키 대신 '보배드림' 같은 이름으로 답한 경우
        if NAMES.get(k) and NAMES[k] in key:
            return k
    return None


def summarize(texts: dict[str, dict[str, str]], llm: LLM) -> dict[str, dict[str, str]]:
    if not texts:
        return {}
    blocks = []
    for iid, per in texts.items():
        for key, text in per.items():
            blocks.append(f"### 이슈ID {iid} / 출처키 {key} ({NAMES.get(key, key)})\n{text}")
    raw = parse_json(llm(PROMPT.format(blocks="\n\n".join(blocks))))
    if isinstance(raw, dict) and len(raw) == 1 and not _norm_issue(next(iter(raw)), set(texts)):
        inner = next(iter(raw.values()))  # {"result": {...}} 처럼 한 겹 싸서 답한 경우
        raw = inner if isinstance(inner, dict) else raw
    clean: dict[str, dict[str, str]] = {}
    for key, per in (raw or {}).items():
        iid = _norm_issue(str(key), set(texts))
        if not iid or not isinstance(per, dict):
            continue
        for skey, v in per.items():
            sk = _norm_source(str(skey), set(texts[iid]))
            if sk and v:
                clean.setdefault(iid, {})[sk] = str(v).strip()[:80]
    if not clean:
        print(f"[경고] 반응 요약 결과를 해석하지 못함: {str(raw)[:200]}")
    return clean


def apply(issues: list[dict], summaries: dict[str, dict[str, str]],
          counts: dict[str, dict[str, int]] | None = None) -> None:
    for it in issues:
        for c in it["communities"]:
            c["reaction"] = summaries.get(it["id"], {}).get(c["key"], "")
            n = (counts or {}).get(it["id"], {}).get(c["key"])
            if n:
                c["comment_count"] = n


def add_reactions(issues: list[dict], llm: LLM | None, yt_key: str | None) -> int:
    """반응 요약을 채우고, 채운 출처 수를 돌려준다. 실패해도 페이지 갱신은 계속된다."""
    if llm is None or not issues:
        return 0
    try:
        texts, counts = gather(issues, yt_key)
        summaries = summarize(texts, llm)
    except Exception as e:  # noqa: BLE001
        print(f"[경고] 댓글 반응 요약 실패: {e}")
        return 0
    apply(issues, summaries, counts)
    return sum(len(v) for v in summaries.values())
