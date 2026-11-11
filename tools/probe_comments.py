"""개발용 점검 도구: 출처별로 최근 글 1개를 열어 댓글이 어디에 있는지 살펴본다.

GitHub Actions의 '댓글 점검' 워크플로에서 수동으로 돌린다. 결과는 로그로만 출력한다.
- 글 페이지가 robots.txt로 허용되는지
- 처음 받은 HTML 안에 댓글 영역이 있는지 (class/id에 comment·cmt·reply)
- 댓글을 따로 불러오는 주소 단서 (스크립트 안의 comment 관련 URL·함수)
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from issuebundle.collect import USER_AGENT  # noqa: E402
from issuebundle.reactions import comment_text  # noqa: E402

posts = json.loads(Path("data/posts.json").read_text(encoding="utf-8"))
session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})
robots_cache = {}

HINT = re.compile(r"""["'`]([^"'`\s]{0,80}(?:comment|cmt|reply|Comment)[^"'`\s]{0,80})["'`]""")


def robots(url: str) -> str:
    p = urlsplit(url)
    host = f"{p.scheme}://{p.netloc}"
    if host not in robots_cache:
        try:
            r = session.get(host + "/robots.txt", timeout=15)
            robots_cache[host] = (r.status_code, r.text)
        except requests.RequestException as e:
            robots_cache[host] = (0, str(e))
    code, text = robots_cache[host]
    rp = RobotFileParser()
    rp.parse(text.splitlines() if code == 200 else [])
    return f"robots {code}, 글 페이지 {'허용' if rp.can_fetch(USER_AGENT, url) else '금지'}"


def robots_rules(url: str) -> list[str]:
    p = urlsplit(url)
    code, text = robots_cache.get(f"{p.scheme}://{p.netloc}", (0, ""))
    return [l.strip() for l in text.splitlines() if re.match(r"\s*(user-agent|disallow|allow)", l, re.I)][:25]


by_source = {}
for row in sorted(posts.values(), key=lambda r: r["last_seen"], reverse=True):
    by_source.setdefault(row["source"], []).append(row)

for source, rows in by_source.items():
    if source == "youtube":
        continue
    sample = sorted(rows[:20], key=lambda r: r["best_rank"])[0]
    url = sample["url"]
    print(f"\n######## {source}: {url}")
    print("  ", robots(url))
    for rule in robots_rules(url):
        print("     ", rule)
    try:
        r = session.get(url, timeout=20)
    except requests.RequestException as e:
        print("   요청 실패", e)
        continue
    r.encoding = r.apparent_encoding or r.encoding
    html = r.text
    print(f"   HTTP {r.status_code}, {len(html)}자")
    text = comment_text(html, limit=400)
    print(f"   HTML 안 댓글 영역: {len(text)}자 → {text[:200]!r}")
    marks = sorted(set(re.findall(r"""(?:class|id)=["']([^"']*(?:comment|cmt|reply)[^"']*)["']""", html, re.I)))[:15]
    print("   댓글 관련 class/id:", marks)
    hints = sorted(set(HINT.findall(html)))[:25]
    print("   스크립트 단서:", hints)
    for m in re.finditer(r"(?:ajax|fetch|\$\.post|\$\.get|url\s*:)[^;\n]{0,160}(?:comment|cmt)[^;\n]{0,80}", html, re.I):
        print("   호출:", m.group(0)[:240])
    for name in ("e_s_n_o", "csrf", "_token", "document_srl", "comment_srl"):
        m = re.search(rf"""name=["']{name}["'][^>]*value=["']([^"']*)""", html)
        if m:
            print(f"   hidden {name} 있음 (길이 {len(m.group(1))})")
