"""개발용 점검 도구 (3차): 더쿠·뽐뿌 댓글을 불러오는 방식을 찾는다."""

import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from issuebundle.collect import USER_AGENT  # noqa: E402

posts = json.loads(Path("data/posts.json").read_text(encoding="utf-8"))
S = requests.Session()
S.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})


def latest(source):
    rows = sorted((r for r in posts.values() if r["source"] == source), key=lambda r: r["last_seen"], reverse=True)
    return sorted(rows[:20], key=lambda r: r["best_rank"])[0]["url"]


def grep(text, pat, n=10, w=220):
    for m in list(re.finditer(pat, text))[:n]:
        a = max(0, m.start() - w)
        print("   …", text[a:m.end() + w].replace("\n", " ")[:2 * w + 80])


print("\n######## 더쿠 board.js (스킨)")
js = S.get("https://theqoo.net/modules/board/skins/sketchbook5_ajax/js/board.js", timeout=20).text
print("  길이", len(js))
grep(js, r"(getComment|CommentPage|comment_list|cpage|exec_json|exec_xml|\$\.ajax|\.load\()", 12)

url = latest("theqoo")
html = S.get(url, timeout=20).text
doc = re.search(r"/(\d{6,})", url).group(1)
mid = re.search(r"theqoo\.net/(\w+)/", url).group(1)
print("\n######## 더쿠 후보 호출 시험", url, mid, doc)
tries = [
    ("GET", f"https://theqoo.net/index.php?mid={mid}&document_srl={doc}&cpage=1", None),
    ("POST", "https://theqoo.net/index.php", {"module": "board", "act": "getBoardCommentPage", "document_srl": doc, "mid": mid, "cpage": "1"}),
    ("POST", "https://theqoo.net/index.php", {"module": "board", "act": "dispBoardContentCommentList", "document_srl": doc, "mid": mid, "cpage": "1"}),
    ("POST", "https://theqoo.net/index.php", {"module": "theqoo", "act": "dispTheqooContentCommentListTheqoo", "document_srl": doc, "mid": mid, "cpage": "1"}),
]
for method, u, data in tries:
    try:
        r = S.request(method, u, data=data, timeout=20,
                      headers={"X-Requested-With": "XMLHttpRequest", "Referer": url, "Accept": "application/json, text/html"})
        body = r.text
        n = len(re.findall(r"comment_\d+|\"comment_srl\"", body))
        print(f"  {method} {u} {data and data.get('act')} → HTTP {r.status_code}, {len(body)}자, 댓글표시 {n}, 앞부분 {body[:160]!r}")
    except Exception as e:
        print("  실패", e)
grep(html, r"(cpage|comment_srl|getComment|loadComment|commentList|\.load\(|exec_json\()", 10, 160)

print("\n######## 뽐뿌 글 페이지 안 댓글 데이터")
url = latest("ppomppu")
html = S.get(url, timeout=20).content.decode("euc-kr", "replace")
print("  ", url, len(html))
grep(html, r"(G_BBS_ID|cmt_list|comment_list|commentList|var\s+\w*[cC]mt\w*\s*=|\.php\?[^\"']*(cmt|comment))", 12, 200)
js = S.get("https://cdn3.ppomppu.co.kr/js/bbs_view_comment.js", timeout=20).text
grep(js, r"(function\s+(load|get|render|fetch)\w*[Cc]o?m+\w*|\.php[^\"'`]*['\"`]|JSON\.parse)", 14, 200)
