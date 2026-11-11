"""네트워크 없이 돌아가는 테스트: 링크 추출, 누적 저장, AI 결과 검증, 단순 묶기."""

import json
from datetime import datetime

from issuebundle import cluster, collect, store
from issuebundle.sources import Source, SOURCES

LIST_HTML = """
<html><body>
<div class="nav"><a href="/hot">HOT</a><a href="/notice/1">공지</a></div>
<ul>
  <li><a href="/hot/3001234567">손흥민 해트트릭 [128]</a><a href="/hot/3001234567#comment">128</a></li>
  <li><a href="/hot/3001234570">  오늘 날씨   미쳤다 (45)</a></li>
  <li><a href="/hot/3001234571">12</a></li>
  <li><a href="https://theqoo.net/hot/3001234572">아이폰 18 가격 공개</a></li>
</ul></body></html>
"""

THEQOO = next(s for s in SOURCES if s.key == "theqoo")


def test_extract_posts_picks_post_links_and_cleans_titles():
    posts = collect.extract_posts(LIST_HTML, THEQOO)
    assert [p.title for p in posts] == ["손흥민 해트트릭", "오늘 날씨 미쳤다", "아이폰 18 가격 공개"]
    assert posts[0].url == "https://theqoo.net/hot/3001234567"
    assert [p.rank for p in posts] == [0, 1, 2]


def test_every_source_pattern_compiles_and_matches_example():
    examples = {
        "dcinside": "/board/view/?id=dcbest&no=123456",
        "fmkorea": "/best/8123456789",
        "theqoo": "/hot/3001234567",
        "ruliweb": "https://bbs.ruliweb.com/best/board/300143/read/71234567",
        "natepann": "/talk/374512345",
        "clien": "/service/board/park/19123456",
    }
    import re
    for s in SOURCES:
        assert re.search(s.post_pattern, examples[s.key]), s.key


def _p(url, title, source, rank=0):
    return collect.Post(url=url, title=title, source=source, rank=rank)


def test_merge_keeps_first_seen_and_best_rank():
    db = store.merge({}, [_p("u1", "제목", "dcinside", 5)], at="2026-11-11T10:00:00+09:00")
    db = store.merge(db, [_p("u1", "제목", "dcinside", 2)], at="2026-11-11T11:00:00+09:00")
    row = db["u1"]
    assert row["first_seen"] == "2026-11-11T10:00:00+09:00"
    assert row["last_seen"] == "2026-11-11T11:00:00+09:00"
    assert row["best_rank"] == 2


def test_recent_and_prune_use_time_window():
    db = store.merge({}, [_p("old", "a", "dcinside")], at="2026-11-08T10:00:00+09:00")
    db = store.merge(db, [_p("new", "b", "dcinside")], at="2026-11-11T10:00:00+09:00")
    at = datetime.fromisoformat("2026-11-11T12:00:00+09:00")
    assert [r["url"] for r in store.recent(db, at=at)] == ["new"]
    assert set(store.prune(db, at=at)) == {"new"}


def _rows():
    rows = []
    data = [
        ("dcinside", "손흥민 해트트릭 미쳤다"), ("fmkorea", "손흥민 해트트릭 ㄷㄷ"),
        ("theqoo", "손흥민 오늘 해트트릭 했대"), ("natepann", "시어머니가 이상해요"),
        ("clien", "아이폰 18 가격 공개"), ("ruliweb", "아이폰18 가격 공개됨"),
    ]
    for i, (src, title) in enumerate(data):
        rows.append({"url": f"https://x/{i}", "title": title, "source": src, "best_rank": i,
                     "first_seen": "2026-11-11T10:00:00+09:00", "last_seen": "2026-11-11T10:00:00+09:00"})
    return rows


def test_cluster_with_llm_drops_invented_ids_and_single_source_pairs():
    fake = json.dumps({"issues": [
        {"headline": "손흥민 해트트릭", "summary": "손흥민이 해트트릭을 기록했다.", "category": "스포츠",
         "post_ids": ["p1", "p2", "p3", "p99"],
         "framing": {"dcinside": "감탄", "fmkorea": "감탄", "theqoo": "축하", "clien": "엉뚱한 키"},
         "unverified": False},
        {"headline": "단독 글", "summary": "", "category": "생활", "post_ids": ["p4"], "framing": {}},
        {"headline": "중복 사용", "summary": "", "category": "기타", "post_ids": ["p1", "p2"], "framing": {}},
    ]})
    issues = cluster.cluster_with_llm(_rows(), lambda prompt: fake)
    assert len(issues) == 1
    it = issues[0]
    assert len(it["posts"]) == 3
    assert {c["key"] for c in it["communities"]} == {"dcinside", "fmkorea", "theqoo"}
    assert "clien" not in [c["key"] for c in it["communities"]]
    assert it["unverified"] is False


def test_prompt_contains_every_title_once():
    prompt, idmap = cluster.build_prompt(_rows())
    assert len(idmap) == 6
    for row in _rows():
        assert prompt.count(row["title"]) == 1


def test_simple_cluster_groups_cross_community_titles():
    issues = cluster.cluster_simple(_rows())
    titles = sorted(sorted(p["title"] for p in it["posts"]) for it in issues)
    assert sorted(["손흥민 오늘 해트트릭 했대", "손흥민 해트트릭 미쳤다", "손흥민 해트트릭 ㄷㄷ"]) in titles
    assert ["아이폰 18 가격 공개", "아이폰18 가격 공개됨"] in titles


def test_make_issues_falls_back_when_llm_fails():
    def broken(_):
        raise RuntimeError("quota")
    issues, method = cluster.make_issues(_rows(), broken)
    assert method == "simple" and issues
