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

from issuebundle import reactions, youtube
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
    comments = {"items": [{"snippet": {"topLevelComment": {"snippet": {"textOriginal": "걱정되네요"}}}}]}
    assert youtube.parse_comments(comments) == ["걱정되네요"]


def test_comment_text_reads_only_comment_area():
    html = """<html><body><article>본문 내용이 아주 길게 있습니다 본문 본문 본문</article>
      <div class="comment_list"><p>첫 댓글입니다 정말 공감해요</p><p>두번째 댓글은 반대 의견</p></div>
      <script>var comment = 'x'</script></body></html>"""
    text = reactions.comment_text(html)
    assert "첫 댓글" in text and "두번째 댓글" in text and "본문" not in text
    assert reactions.comment_text("<div>댓글 없음</div>") == ""


def test_reactions_gather_and_summarize_end_to_end():
    issues, _ = cluster.cluster_with_llm(_rows(), lambda _: json.dumps({"issues": [
        {"headline": "손흥민", "summary": "", "why": "", "category": "스포츠",
         "post_ids": ["p1", "p2"], "framing": {}, "unverified": False}]}))
    page = '<div id="cmt_wrap">대단하다는 댓글이 정말 많음, 이번 경기 최고였다는 반응</div>'
    texts, _ = reactions.gather(issues, None, fetch_html=lambda url: page)
    assert set(texts["i0"]) == {"dcinside", "fmkorea"}
    llm = lambda _: json.dumps({"i0": {"dcinside": "칭찬 일색", "theqoo": "없는 출처"}, "i9": {"x": "y"}})
    summaries = reactions.summarize(texts, llm)
    assert summaries == {"i0": {"dcinside": "칭찬 일색"}}
    reactions.apply(issues, summaries)
    got = {c["key"]: c["reaction"] for c in issues[0]["communities"]}
    assert got == {"dcinside": "칭찬 일색", "fmkorea": ""}


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


# ---------- 사이트별 댓글 파서 ----------

def test_dc_comment_parser():
    data = {"total_cnt": "336", "comments": [
        {"memo": "<b>대단하다</b> 진짜", "del_yn": "N", "is_delete": "0", "name": "ㅇㅇ"},
        {"memo": "삭제된 댓글", "del_yn": "Y", "is_delete": "1", "name": "ㅇㅇ"},
        {"memo": "광고입니다", "del_yn": "N", "is_delete": "0", "name": "댓글돌이"}]}
    assert reactions.parse_dc_comments(data) == (["대단하다 진짜"], 336)


def test_theqoo_comment_parser_skips_member_only():
    data = {"comment_list": [
        {"ct": '<span class="commentWarningMessage">비회원은 작성한 지 1시간 이내의 댓글은 읽을 수 없습니다.</span>'},
        {"ct": "<p>너무 안타깝다</p>"}]}
    assert reactions.parse_theqoo_comments(data) == (["너무 안타깝다"], None)


def test_ppomppu_inline_json_parser():
    html = """<script> var initialCommentData = {"total_comment":26,"total_page":2,"comments":[
      {"no":1,"depth":0,"memo":"<div>비싸네요</div>","name":"a"},
      {"no":2,"depth":1,"name":"b","unknown_field":"이 가격이면 다른 차 사죠"}]}; var x = 1;</script>"""
    assert reactions.parse_ppomppu_page(html) == (["비싸네요", "이 가격이면 다른 차 사죠"], 26)
    assert reactions.parse_ppomppu_page("<html></html>") == ([], None)


def test_html_comment_parser_counts_and_hides_member_only():
    html = '<div class="cmt_list">댓글 (18) | 등록순 와 부부가 같이 저지른건 또 신박하네 답글 0 추천 5</div>'
    texts, n = reactions.parse_html_comments(html)
    assert n == 18 and "신박하네" in texts[0]
    hidden = '<div class="comment_line">임시글자임시글자임시글자 1시간 내 작성된 댓글은 회원만 볼 수 있어요, 로그인 후 이용해 주세요 정말 좋은 글이네요 공감합니다</div>'
    texts, _ = reactions.parse_html_comments(hidden)
    assert texts and "임시글자" not in texts[0] and "공감합니다" in texts[0]


def test_summarize_accepts_names_and_wrapped_answers():
    texts = {"i1": {"bobaedream": "댓글들", "theqoo": "댓글들"}}
    wrapped = json.dumps({"result": {"이슈 i1": {"보배드림": "분노가 큼", "theqoo": "안타까움"}}})
    assert reactions.summarize(texts, lambda _: wrapped) == {"i1": {"bobaedream": "분노가 큼", "theqoo": "안타까움"}}


def test_apply_sets_comment_counts():
    issues, _ = cluster.cluster_with_llm(_rows(), lambda _: json.dumps({"issues": [
        {"headline": "x", "summary": "", "why": "", "category": "사회", "post_ids": ["p1", "p2"], "framing": {}}]}))
    reactions.apply(issues, {"i0": {"dcinside": "요약"}}, {"i0": {"dcinside": 336}})
    dc = next(c for c in issues[0]["communities"] if c["key"] == "dcinside")
    assert dc["reaction"] == "요약" and dc["comment_count"] == 336
