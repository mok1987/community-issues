"""개발용 점검 도구 (2차): 댓글을 따로 불러오는 사이트의 호출 방식과 robots.txt 전체 규칙을 확인한다."""

import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from issuebundle.collect import USER_AGENT  # noqa: E402
from issuebundle import reactions  # noqa: E402

posts = json.loads(Path("data/posts.json").read_text(encoding="utf-8"))
S = requests.Session()
S.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})


def latest(source):
    rows = sorted((r for r in posts.values() if r["source"] == source), key=lambda r: r["last_seen"], reverse=True)
    return sorted(rows[:20], key=lambda r: r["best_rank"])[0]["url"]


def star_rules(host):
    text = S.get(f"https://{host}/robots.txt", timeout=15).text
    out, on = [], False
    for line in text.splitlines():
        l = line.strip()
        if l.lower().startswith("user-agent"):
            on = l.split(":", 1)[1].strip() == "*"
        elif on and l:
            out.append(l)
    print(f"  [{host}] User-agent: * 규칙 →", out[:30])


def grep(text, pat, n=12, w=160):
    for m in list(re.finditer(pat, text))[:n]:
        a = max(0, m.start() - w); print("   …", text[a:m.end() + w].replace("\n", " ")[:2 * w + 60])


print("\n######## robots (* 규칙)")
for h in ("gall.dcinside.com", "theqoo.net", "www.ppomppu.co.kr", "www.instiz.net", "www.bobaedream.co.kr", "bbs.ruliweb.com"):
    try:
        star_rules(h)
    except Exception as e:
        print(h, e)

print("\n######## 디시 comment.js")
js = S.get("https://gall.dcinside.com/_js/comment.js", timeout=20).text
grep(js, r"/board/comment/", 4, 400)

print("\n######## 디시 댓글 호출 시험")
url = latest("dcinside")
html = S.get(url, timeout=20).text
m_id = re.search(r"[?&]id=(\w+)", url); m_no = re.search(r"[?&]no=(\d+)", url)
esno = re.search(r"""name=["']e_s_n_o["'][^>]*value=["']([^"']*)""", html)
gtype = re.search(r"""name=["']_GALLTYPE_["'][^>]*value=["']([^"']*)""", html)
data = {"id": m_id.group(1), "no": m_no.group(1), "cmt_id": m_id.group(1), "cmt_no": m_no.group(1),
        "focus_cno": "", "focus_pno": "", "e_s_n_o": esno.group(1) if esno else "", "comment_page": "1",
        "sort": "", "prevCnt": "", "board_type": "", "_GALLTYPE_": gtype.group(1) if gtype else "G"}
r = S.post("https://gall.dcinside.com/board/comment/", data=data, timeout=20,
           headers={"X-Requested-With": "XMLHttpRequest", "Referer": url})
print("  ", url, "→ HTTP", r.status_code, r.text[:300].replace("\n", " "))

print("\n######## 더쿠 댓글 불러오기 스크립트")
url = latest("theqoo")
html = S.get(url, timeout=20).text
grep(html, r"(loadComment|getComment|CommentList|comment_list|cpage|procTheqoo|dispTheqoo|exec_json|\.ajax)", 15, 200)
for src in sorted(set(re.findall(r"""<script[^>]+src=["']([^"']+)""", html)))[:20]:
    print("   script:", src)

print("\n######## 뽐뿌 bbs_view_comment.js")
js = S.get("https://cdn3.ppomppu.co.kr/js/bbs_view_comment.js", timeout=20).text
print("  길이", len(js))
grep(js, r"(url\s*:|\.php|ajax|fetch\()", 15, 160)

print("\n######## 보배드림 reactions.gather 직접 시험")
url = latest("bobaedream")
issue = {"id": "i0", "communities": [{"key": "bobaedream"}], "posts": [{"url": url, "source": "bobaedream"}]}
texts = reactions.gather([issue], None)
print("  ", url, "→", {k: len(v) for k, v in texts.get("i0", {}).items()}, (texts.get("i0", {}).get("bobaedream", ""))[:200])
