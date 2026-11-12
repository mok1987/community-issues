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
        "youtube": "https://www.youtube.com/watch?v=abc",
        "instiz": "https://www.instiz.net/pt/7612345",
        "ppomppu": "view.php?id=freeboard&no=9123456",
        "bobaedream": "/view?code=best&No=812345",
        "navernews": "https://n.news.naver.com/article/001/0015123456",
        "daumnews": "https://v.daum.net/v/20261111120012345",
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
    issues, _ = cluster.cluster_with_llm(_rows(), lambda prompt: fake)
    assert len(issues) == 1
    it = issues[0]
    assert len(it["posts"]) == 3
    assert {c["key"] for c in it["communities"]} == {"dcinside", "fmkorea", "theqoo"}
    assert "clien" not in [c["key"] for c in it["communities"]]
    assert it["unverified"] is False


def test_prompt_contains_every_title_once():
    prompt, idmap = cluster.build_prompt(_rows(), set())
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
    issues, _, method = cluster.make_issues(_rows(), broken)
    assert method == "simple" and issues


# ---------- 카테고리, TOP5, 유튜브, 댓글 반응 ----------

from issuebundle import youtube
from run import build_tops


def test_fix_category_maps_partial_and_unknown():
    assert cluster.fix_category("연예") == "문화·연예"
    assert cluster.fix_category("IT") == "IT·과학"
    assert cluster.fix_category("정치") == "정치"
    assert cluster.fix_category("아무거나") == cluster.DEFAULT_CATEGORY
    assert cluster.fix_category(None) == cluster.DEFAULT_CATEGORY


def test_top_meta_and_hot_flag():
    rows = _rows()
    fake_issues = json.dumps({"issues": [
        {"headline": "아이폰 18 가격", "summary": "", "why": "비싸서", "category": "IT",
         "post_ids": ["p5", "p6"], "framing": {}, "unverified": False}]})
    # TOP5 호출에서는 TOP 글만 p1부터 다시 번호가 매겨진다
    fake_top = json.dumps({"p1": {"category": "IT", "easy": "아이폰 18 가격 공개"},
                           "p99": {"easy": "가짜"}, "p2": {"category": "IT", "easy": ""}})
    llm = lambda prompt: fake_top if "쉬운 말로 바꿔주는" in prompt else fake_issues
    issues, top_meta = cluster.cluster_with_llm(rows, llm, {rows[4]["url"]})
    assert issues[0]["hot"] is True and issues[0]["category"] == "IT·과학" and issues[0]["id"] == "i0"
    assert top_meta == {rows[4]["url"]: {"category": "IT·과학", "easy": "아이폰 18 가격 공개"}}
    fresh = [_p(r["url"], r["title"], r["source"], r["best_rank"]) for r in rows]
    tops = build_tops(fresh, issues, top_meta)
    clien = next(t for t in tops if t["key"] == "clien")["items"][0]
    assert clien["hot"] and clien["issue_id"] == "i0" and clien["easy"] == "아이폰 18 가격 공개"
    nate = next(t for t in tops if t["key"] == "natepann")["items"][0]
    assert not nate["hot"] and nate["issue_id"] is None


def test_prompt_marks_top_posts():
    rows = _rows()
    prompt, _ = cluster.build_prompt(rows, {rows[0]["url"]})
    assert "(dcinside) ★ 손흥민" in prompt and "(fmkorea) 손흥민" in prompt


def test_youtube_parsers():
    popular = {"items": [
        {"id": "v1", "snippet": {"title": "뉴스 특보", "channelTitle": "방송사"}, "statistics": {"commentCount": "120"}},
        {"id": "v2", "snippet": {"title": "", "channelTitle": "x"}, "statistics": {}},
        {"id": "v3", "snippet": {"title": "뮤비"}, "statistics": {}},
    ]}
    posts = youtube.parse_popular(popular)
    assert [p.title for p in posts] == ["뉴스 특보 — 방송사", "뮤비"]
    assert posts[0].comment_count == 120 and posts[1].comment_count is None
    assert posts[0].url == "https://www.youtube.com/watch?v=v1" and youtube.video_id(posts[0].url) == "v1"


# ---------- 첫 실제 실행에서 나온 문제들 ----------

DC = next(s for s in SOURCES if s.key == "dcinside")


def test_notices_and_count_links_are_skipped():
    html = """<div class="notice_wrap_outer"><table><tbody>
      <tr class="ub-content us-post" data-type="icon_notice"><td><a href="/board/view/?id=dcbest&no=1">실시간베스트 갤러리 이용 안내</a></td></tr>
      <tr class="ub-content us-post" data-type="icon_txt"><td>
        <a href="/board/view/?id=dcbest&no=555&page=1">[박갤] 화재 현장 후기</a>
        <a href="/board/view/?id=dcbest&no=555&t=cv&page=1">[6571/2]</a></td></tr>
      <tr class="notice"><td><a href="/board/view/?id=dcbest&no=2">이벤트 당첨자 발표</a></td></tr>
      <tr><td><a href="/board/view/?id=dcbest&no=777">[필독] 로그인 보안 강화</a></td></tr>
      <tr><td><a href="/board/view/?id=dcbest&no=888">공지 없는 진짜 인기글 제목</a></td></tr>
    </tbody></table></div>"""
    posts = collect.extract_posts(html, DC)
    assert [p.title for p in posts] == ["[박갤] 화재 현장 후기", "공지 없는 진짜 인기글 제목"]
    assert posts[0].url == "https://gall.dcinside.com/board/view/?id=dcbest&no=555"


def test_youtube_music_is_skipped():
    data = {"items": [
        {"id": "m", "snippet": {"title": "노래", "channelTitle": "가수 - Topic", "categoryId": "10"}, "statistics": {}},
        {"id": "n", "snippet": {"title": "뉴스", "channelTitle": "방송", "categoryId": "25"}, "statistics": {}},
    ]}
    assert [p.url for p in youtube.parse_popular(data)] == ["https://www.youtube.com/watch?v=n"]


def test_env_key_strips_newlines(monkeypatch):
    import run
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.abc\n")
    monkeypatch.setenv("YOUTUBE_API_KEY", "  \n")
    assert run.env_key("GEMINI_API_KEY") == "AQ.abc"
    assert run.env_key("YOUTUBE_API_KEY") is None


def test_pick_model_prefers_newest_stable_flash_lite():
    gen = ["generateContent"]
    models = [
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": gen},
        {"name": "models/gemini-3.1-flash-lite", "supportedGenerationMethods": gen},
        {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": gen},
        {"name": "models/gemini-3.8-flash-lite-preview", "supportedGenerationMethods": gen},
        {"name": "models/gemini-4.0-flash-lite", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": gen},
    ]
    assert cluster.pick_model(models) == "gemini-3.5-flash-lite"
    no_lite = [m for m in models if "lite" not in m["name"]]
    assert cluster.pick_model(no_lite) == "gemini-3.6-flash"
    assert cluster.pick_model([]) is None


def test_blocked_sources_appear_in_tops_with_state():
    fresh = [_p("https://x/1", "글", "dcinside", 0)]
    status = {"dcinside": "1개", "fmkorea": "robots.txt가 막고 있어 건너뜀", "clien": "HTTP 403"}
    tops = build_tops(fresh, [], {}, status)
    assert [(t["key"], t["state"], len(t["items"])) for t in tops] == [
        ("dcinside", "ok", 1), ("fmkorea", "blocked", 0), ("clien", "error", 0)]


def test_source_specific_cleanup():
    instiz = next(s for s in SOURCES if s.key == "instiz")
    html = """<a href="https://www.instiz.net/name/67949695">일상 신상빼빼로 26 ㄷㄱㄷㄱ 12:47 l 조회 894</a>
      <a href="/pt/7924553">정보·기타 입사 일주일만에 3개월치 월급 줄테니 퇴사 하라네요 19 11:37 l</a>
      <a href="/pt/7924530">2026 월드컵 4강 18 미리보기</a>"""
    assert [p.title for p in collect.extract_posts(html, instiz)] == [
        "신상빼빼로", "입사 일주일만에 3개월치 월급 줄테니 퇴사 하라네요", "2026 월드컵 4강"]
    pp = next(s for s in SOURCES if s.key == "ppomppu")
    html = """<a href="/zboard/view.php?id=pmarket7&no=1">겨울철 제동거리 116</a>
      <a href="/zboard/view.php?id=baby&no=54473">'탈락'이라는 단어자체도 기분나쁜 학부모들.jpg 109</a>
      <a href="/zboard/view.php?id=ppomppu&no=747872">[G마켓] 운동화 7</a>
      <a href="/zboard/view.php?id=freeboard&no=9">AD [박리다매] 인터넷 가입</a>"""
    assert [p.title for p in collect.extract_posts(html, pp)] == ["'탈락'이라는 단어자체도 기분나쁜 학부모들.jpg"]
    bobae = next(s for s in SOURCES if s.key == "bobaedream")
    posts = collect.extract_posts('<a href="/view?code=best&No=1046725&vdate=">근황 소식</a>', bobae)
    assert posts[0].url == "https://www.bobaedream.co.kr/view?code=best&No=1046725"


def test_daum_titles_drop_lede_and_press():
    daum = next(s for s in SOURCES if s.key == "daumnews")
    html = """<a href="https://v.daum.net/v/20261111124324925">"美상무장관도 '젠슨황 첩보' 듣고도 中기업 AI칩 수출승인"(종합) [서울=뉴시스] 김승민 기자 = 도널드 트럼프 미국 대통령이 ... 액시오스 뉴시스 34분 전</a>
      <a href="https://v.daum.net/v/20261111123800726">中, 엔비디아 칩 10조원대 밀수 의혹…美中 관계 얼어붙나? 파이낸셜뉴스 40분 전</a>
      <a href="https://v.daum.net/v/20261111114757123"><strong class="tit_txt">한-우크라 첫 외교장관 회담</strong><p class="desc">본문 요약</p></a>"""
    assert [p.title for p in collect.extract_posts(html, daum)] == [
        '"美상무장관도 \'젠슨황 첩보\' 듣고도 中기업 AI칩 수출승인"(종합)',
        "中, 엔비디아 칩 10조원대 밀수 의혹…美中 관계 얼어붙나?",
        "한-우크라 첫 외교장관 회담"]




def test_explain_words_keeps_only_words_in_titles():
    titles = ["2호선 멈춤 실화냐", "B게임 출시일 떴다 ㄹㅇ 갓겜 예약"]
    fake = json.dumps({"words": [
        {"word": "실화냐", "meaning": "정말이냐는 놀람의 표현", "example": "이 가격 실화냐?"},
        {"word": "갓겜", "meaning": "아주 잘 만든 게임", "example": "이건 갓겜이야"},
        {"word": "없는말", "meaning": "제목에 없음"},
        {"word": "갓겜", "meaning": "중복"},
        {"word": "", "meaning": "빈 단어"}]})
    words = cluster.explain_words(titles, lambda _: fake)
    assert [w["word"] for w in words] == ["실화냐", "갓겜"]
    assert cluster.explain_words(titles, lambda _: "망가진 JSON") == []
    assert cluster.explain_words([], lambda _: fake) == []


def test_tops_carry_list_url_for_direct_links():
    tops = build_tops([], [], {}, {"fmkorea": "robots.txt가 막고 있어 건너뜀"})
    assert tops[0]["list_url"] == "https://www.fmkorea.com/best" and tops[0]["state"] == "blocked"


def test_make_issues_retries_once_on_broken_json():
    good = json.dumps({"issues": [{"headline": "손흥민", "summary": "", "why": "", "category": "스포츠",
                                   "post_ids": ["p1", "p2"], "framing": {}}]})
    calls = []
    def flaky(prompt):
        calls.append(1)
        return "{망가진" if len(calls) == 1 else good
    issues, _, method = cluster.make_issues(_rows(), flaky)
    assert method == "ai" and issues and len(calls) == 2


def test_explain_words_drops_rough_origins():
    titles = ["완전 엄미새네", "주가 떡상"]
    fake = json.dumps({"words": [
        {"word": "엄미새", "origin": "엄마 미친 새끼", "meaning": "엄마를 지나치게 따르는 사람"},
        {"word": "떡상", "origin": "떡처럼 위로 솟음", "meaning": "갑자기 크게 오름"}]})
    assert [w["word"] for w in cluster.explain_words(titles, lambda _: fake)] == ["떡상"]


def test_label_tops_accepts_list_or_wrapped_answers_and_batches():
    rows = _rows()
    as_list = json.dumps([{"id": "p1", "category": "스포츠", "easy": "쉬운 제목"}])
    wrapped = json.dumps({"items": {"p2": {"category": "IT", "easy": "또 다른 제목"}}})
    assert list(cluster.label_tops(rows[:1], lambda _: as_list).values())[0]["easy"] == "쉬운 제목"
    assert list(cluster.label_tops(rows[:2], lambda _: wrapped).values())[0]["category"] == "IT·과학"
    many = [dict(r, url=f"https://x/{i}") for i, r in enumerate(rows * 15)]  # 90개 → 3번 나눠 요청
    calls = []
    cluster.label_tops(many, lambda p: calls.append(1) or json.dumps({"p1": {"easy": "a"}}))
    assert len(calls) == 3


def test_wordbook_find_and_candidates(tmp_path):
    from issuebundle import words as wordbook
    d = [{"word": "실화냐", "meaning": "놀람"}, {"word": "찐", "meaning": "진짜"}, {"word": "떡상", "meaning": "급등"}]
    titles = ["이 가격 실화냐", "찐빵 맛집", "주가 떡상 ㄷㄷ 떡상", "찐 맛집 발견"]
    found = wordbook.find(titles, d)
    assert [w["word"] for w in found] == ["떡상", "실화냐", "찐"]  # 찐빵의 '찐'은 한 번만 안 셈
    path = tmp_path / "cands.json"
    assert wordbook.update_candidates(path, [{"word": "실화냐"}, {"word": "새말", "meaning": "AI 초안"}], d, "t1") == 1
    assert wordbook.update_candidates(path, [{"word": "새말"}], d, "t2") == 0
    cands = json.loads(path.read_text(encoding="utf-8"))
    assert cands == [{"word": "새말", "ai_meaning": "AI 초안", "example": "", "seen": 2, "first_seen": "t1", "last_seen": "t2"}]


def test_real_dictionary_is_clean():
    from pathlib import Path
    from issuebundle import words as wordbook
    entries = wordbook.load(Path(__file__).resolve().parent.parent / "data" / "words.json")
    assert len(entries) >= 50
    for e in entries:
        assert not cluster._ROUGH.search(e["word"] + e["meaning"] + e.get("example", "")), e["word"]
    assert len({e["word"] for e in entries}) == len(entries)


def test_people_pick_filters_and_ranks():
    from issuebundle import people
    titles = ["손흥민 해트트릭", "손흥민 또 골", "아이유 신곡 공개", "김철수 씨 사건", "지어낸사람 등장"]
    fake = json.dumps({"people": [
        {"name": "아이유", "why": "신곡을 공개해서"},
        {"name": "손흥민", "why": "해트트릭을 기록해서"},
        {"name": "김철수", "why": "일반인"},
        {"name": "없는이름", "why": "제목에 없음"}]})
    wiki = {
        "손흥민": {"title": "손흥민", "description": "대한민국의 축구 선수", "type": "standard",
                 "thumbnail": {"source": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/x.jpg"}},
        "아이유": {"title": "아이유", "description": "대한민국의 가수", "type": "standard",
                 "thumbnail": {"source": "https://upload.wikimedia.org/wikipedia/ko/thumb/nonfree.jpg"}},
        "김철수": {"title": "김철수", "type": "disambiguation", "description": "동명이인"},
    }
    got = people.pick(titles, lambda _: fake, fetch=lambda n: wiki.get(n))
    assert [p["name"] for p in got] == ["손흥민", "아이유"]           # 언급 수 순, 일반인·지어낸 이름 제외
    assert got[0]["photo"].startswith("https://upload.wikimedia.org/wikipedia/commons/")
    assert got[1]["photo"] is None                                   # 위키백과 자체 사진(비자유 가능)은 안 씀
    assert got[0]["who"] == "대한민국의 축구 선수" and got[0]["mentions"] == 2


def test_people_mentions_ignore_spaces_and_describe_uses_news():
    from issuebundle import people
    titles = ["젠슨황 추가 의혹", "젠슨 황 스캔들", "넉살: 존박은 랩을 하면 안된다", "존박 생라면"]
    assert people.mentions("젠슨 황", titles) == 2 and people.mentions("존 박", titles) == 2
    ps = [{"name": "존 박", "who": "가수", "why": "생라면"}]
    seen = {}
    def llm(prompt):
        seen["prompt"] = prompt
        return json.dumps({"존박": "맥도날드에서 랩으로 주문하는 영상이 퍼지며 화제"})
    people.describe(ps, titles, llm, news_fn=lambda n: ["존박, 맥도날드 랩 주문 영상 화제 — 예능 출연 중"])
    assert ps[0]["why"].startswith("맥도날드") and ps[0]["news_used"] is True
    assert "넉살: 존박은 랩을 하면 안된다" in seen["prompt"] and "맥도날드 랩 주문" in seen["prompt"]


def test_naver_news_without_keys_returns_empty(monkeypatch):
    from issuebundle import people
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    assert people.naver_news("아무개") == []


def test_people_ground_uses_cache_and_requires_suggestions():
    from issuebundle import people
    ps = [{"name": "존박", "who": "가수", "why": "옛"}, {"name": "손흥민", "who": "축구 선수", "why": "원래"}]
    calls = []

    def g(prompt):
        calls.append(prompt)
        if "손흥민" in prompt:
            return {"text": "문장", "suggest": "", "queries": []}  # 검색 추천 없음 → 쓰지 않음
        return {"text": '"맥도날드에서 랩으로 주문해 화제예요[1]"', "suggest": "<div>chip</div>", "queries": ["존박"]}

    cache = {}
    assert people.ground(ps, ["존박 맥도날드"], g, cache, "2026-11-12T11:00:00+09:00") == 2
    assert ps[0]["why"] == "맥도날드에서 랩으로 주문해 화제예요" and ps[0]["suggest"]
    assert ps[1]["why"] == "원래" and "suggest" not in ps[1]
    people.ground(ps, [], g, cache, "2026-11-12T12:00:00+09:00")
    assert len(calls) == 3  # 존박은 캐시 사용, 손흥민만 다시 시도


def test_notify_quiet_hours_and_message():
    from datetime import datetime
    import notify
    k = notify.KST
    assert notify.in_quiet_hours(datetime(2026, 11, 12, 6, 59, tzinfo=k))
    assert not notify.in_quiet_hours(datetime(2026, 11, 12, 7, 3, tzinfo=k))
    assert not notify.in_quiet_hours(datetime(2026, 11, 12, 22, 20, tzinfo=k))
    assert notify.in_quiet_hours(datetime(2026, 11, 12, 22, 45, tzinfo=k))
    line = notify.top_line({"issues": [{"hot": False, "headline": "B"}, {"hot": True, "headline": "A"}]})
    assert line == "지금 1위: A"
    b = notify.build("app", line, "https://hotnow.kr/")
    assert b["headings"]["en"] == "실시간 화제를 확인해보세요" and b["web_push_topic"]


def test_safe_why_blocks_rumors_but_not_ordinary_words():
    from issuebundle.people import safe_why, NEUTRAL_WHY
    assert safe_why("사내 불륜 의혹으로 화제예요") == NEUTRAL_WHY
    assert safe_why("열애설이 돌아요") == NEUTRAL_WHY
    assert safe_why("연설이 화제예요") == "연설이 화제예요"


def test_people_pick_resolves_disambiguation_with_job():
    from issuebundle import people
    pages = {"조이": {"type": "disambiguation", "title": "조이", "description": "동음이의"},
             "조이 (가수)": {"type": "standard", "title": "조이 (가수)", "description": "대한민국의 가수"}}
    llm = lambda prompt: '{"people": [{"name": "조이", "job": "가수", "why": "새 노래를 냈어요"}]}'
    out = people.pick(["조이 신곡 공개"], llm, fetch=pages.get)
    assert out and out[0]["name"] == "조이" and out[0]["who"] == "대한민국의 가수"


def test_by_job_picks_korean_same_job_page():
    from issuebundle import people
    pages = [{"title": "김민재", "description": "동음이의"},
             {"title": "김민재 (배우)", "description": "대한민국의 배우"},
             {"title": "김민재 (1996년)", "description": "대한민국의 축구 선수"},
             {"title": "김민재희", "description": "대한민국의 축구 선수"}]
    assert people.by_job("김민재", "축구 선수", search=lambda q: pages) == "김민재 (1996년)"
    assert people.by_job("김민재", "가수", search=lambda q: pages) is None
