"""화면 확인용 예시 데이터로 site/issues.json 을 만든다 (네트워크·API 키 불필요).

예시 내용은 전부 지어낸 것이며 링크는 example.com 이다. 첫 실제 실행(run.py)이 덮어쓴다.
"""

import json
from pathlib import Path

from issuebundle import cluster, store
from issuebundle.collect import Post
from issuebundle.sources import SOURCES
from run import build_tops

ROWS = [  # (출처, 제목, 순위, 댓글 수)
    ("dcinside", "[예시] 2호선 지금 개박살남", 0, None),
    ("dcinside", "[예시] B겜 출시일 떴는데 가격 실화냐", 1, None),
    ("dcinside", "[예시] 편의점 신상 먹어봄", 2, None),
    ("fmkorea", "[예시] 2호선 멈춤 지금 역 상황", 0, None),
    ("fmkorea", "[예시] 금리 동결 발표", 1, None),
    ("fmkorea", "[예시] B게임 신작 출시일 공개", 2, None),
    ("theqoo", "[예시] 지하철 2호선 운행 중단 공지 떴대", 0, None),
    ("theqoo", "[예시] A그룹 컴백 티저 공개", 1, None),
    ("clien", "[예시] 2호선 신호 장애로 운행 중단", 0, None),
    ("clien", "[예시] 한국은행 기준금리 동결", 1, None),
    ("youtube", "[예시] 2호선 운행 중단 현장 — 예시뉴스", 0, 1840),
    ("youtube", "[예시] A그룹 신곡 티저 — 예시엔터", 1, 5320),
    ("youtube", "[예시] 금리 동결, 내 대출은? — 예시경제", 2, 911),
]

CLUSTER = {
    "issues": [
        {"headline": "[예시] 지하철 2호선 출근길 운행 중단", "category": "사회",
         "summary": "출근 시간에 2호선이 신호 장애로 멈췄다는 글과 영상이 여러 곳에 올라왔다.",
         "why": "출근길 수많은 사람이 직접 영향을 받아서",
         "post_ids": ["p1", "p4", "p7", "p9", "p11"], "unverified": False,
         "framing": {"dcinside": "현장 상황을 과장 섞어 전함", "fmkorea": "역 상황 공유",
                     "theqoo": "공지 내용 정리", "clien": "원인 중심", "youtube": "현장 영상"}},
        {"headline": "[예시] 한국은행 기준금리 동결", "category": "경제",
         "summary": "한국은행이 기준금리를 그대로 두기로 했다.",
         "why": "대출 이자와 집값에 바로 연결되는 결정이라서",
         "post_ids": ["p5", "p10", "p13"], "unverified": False, "framing": {}},
        {"headline": "[예시] B게임 신작 출시일 발표", "category": "문화·연예",
         "summary": "B게임 신작 출시일이 공개됐고, 가격을 두고 말이 많다.",
         "why": "예상보다 가격이 높다는 반응이 많아서",
         "post_ids": ["p2", "p6"], "unverified": False, "framing": {}},
        {"headline": "[예시] A그룹 컴백 예고 영상 공개", "category": "문화·연예",
         "summary": "A그룹이 새 노래 예고 영상을 공개했다.", "why": "오랜만의 활동 소식이라서",
         "post_ids": ["p8", "p12"], "unverified": False, "framing": {}},
    ],
    "top": {
        "p1": {"category": "사회", "easy": "지하철 2호선이 멈춰서 혼란"},
        "p2": {"category": "문화·연예", "easy": "B게임 출시일 공개, 가격이 비싸다는 반응"},
        "p3": {"category": "생활", "easy": "편의점 새 상품 먹어본 후기"},
        "p4": {"category": "사회", "easy": "2호선 멈춘 역 현장 상황"},
        "p5": {"category": "경제", "easy": "기준금리 동결 발표"},
        "p6": {"category": "문화·연예", "easy": "B게임 신작 출시일 공개"},
        "p7": {"category": "사회", "easy": "2호선 운행 중단 공지"},
        "p8": {"category": "문화·연예", "easy": "A그룹 컴백 예고 영상 공개"},
        "p9": {"category": "사회", "easy": "2호선 신호 장애로 운행 중단"},
        "p10": {"category": "경제", "easy": "한국은행 기준금리 동결"},
        "p11": {"category": "사회", "easy": "2호선 운행 중단 현장 영상"},
        "p12": {"category": "문화·연예", "easy": "A그룹 새 노래 예고 영상"},
        "p13": {"category": "경제", "easy": "금리 동결로 대출 이자는 어떻게 되나"},
    },
}

if __name__ == "__main__":
    now = store.now_iso()
    fresh = [Post(url=f"https://example.com/{i}", title=t, source=s, rank=r, comment_count=c)
             for i, (s, t, r, c) in enumerate(ROWS)]
    rows = list(store.merge({}, fresh, at=now).values())
    def fake_llm(prompt: str) -> str:  # 묶기 호출과 TOP5 쉬운 제목 호출에 각각 답한다
        data = CLUSTER["top"] if "쉬운 말로 바꿔주는" in prompt else {"issues": CLUSTER["issues"]}
        return json.dumps(data, ensure_ascii=False)

    issues, top_meta = cluster.cluster_with_llm(rows, fake_llm, {p.url for p in fresh})
    names = {s.key: s.name for s in SOURCES}
    out = {"updated_at": now, "method": "demo", "post_count": len(rows),
           "sources": [{"key": "demo", "name": "예시 데이터", "status": "실제 수집 전"}],
           "issues": issues, "tops": build_tops(fresh, issues, top_meta),
           "people": [
               {"name": "[예시] 가수 A", "who": "대한민국의 가수", "why": "새 노래 예고 영상을 공개해서", "mentions": 3,
                "photo": None, "wiki": "https://ko.wikipedia.org/"},
               {"name": "[예시] 선수 B", "who": "대한민국의 축구 선수", "why": "경기에서 결승골을 넣어서", "mentions": 2,
                "photo": None, "wiki": "https://ko.wikipedia.org/"},
               {"name": "[예시] 대표 C", "who": "게임 회사 대표", "why": "신작 출시일을 발표해서", "mentions": 2,
                "photo": None, "wiki": "https://ko.wikipedia.org/"}],
           "words": [{"word": "실화냐", "meaning": "'정말이야?' 하고 놀랄 때 쓰는 말", "example": "이 가격 실화냐?"},
                     {"word": "B겜", "meaning": "B게임. '겜'은 '게임'을 줄인 말", "example": "주말에 겜 한 판 하자"}]}
    path = Path(__file__).parent / "site" / "issues.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"예시 이슈 {len(issues)}개 (화제 중 {sum(i['hot'] for i in issues)}개) → {path}")
