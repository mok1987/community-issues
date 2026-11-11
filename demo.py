"""화면 확인용 예시 데이터로 site/issues.json 을 만든다 (네트워크·API 키 불필요).

예시 내용은 전부 지어낸 것이며 링크는 example.com 이다. 첫 실제 실행(run.py)이 덮어쓴다.
"""

import json
from pathlib import Path

from issuebundle import cluster, store

ROWS = [
    ("dcinside", "[예시] OO시 지하철 2호선 출근길 운행 중단"),
    ("fmkorea", "[예시] 2호선 멈춤 지금 역 상황"),
    ("theqoo", "[예시] 지하철 2호선 운행 중단 공지 떴대"),
    ("clien", "[예시] 2호선 신호 장애로 운행 중단"),
    ("theqoo", "[예시] A그룹 신곡 티저 공개"),
    ("natepann", "[예시] A그룹 컴백 티저 반응"),
    ("ruliweb", "[예시] B게임 신작 출시일 발표"),
    ("fmkorea", "[예시] B게임 신작 출시일 떴다"),
    ("dcinside", "[예시] B게임 출시일 발표 근데 가격이"),
]

FAKE = {"issues": [
    {"headline": "[예시] 지하철 2호선 출근길 운행 중단", "category": "사회",
     "summary": "출근 시간대 2호선이 신호 장애로 멈췄다는 글이 여러 커뮤니티에 올라왔다.",
     "post_ids": ["p1", "p2", "p3", "p4"], "unverified": False,
     "framing": {"dcinside": "현장 상황 공유 위주", "fmkorea": "지각 걱정과 불만",
                 "theqoo": "공지 내용 정리", "clien": "원인(신호 장애) 중심"}},
    {"headline": "[예시] B게임 신작 출시일 발표", "category": "게임",
     "summary": "B게임 신작 출시일이 발표됐고, 가격을 두고 반응이 갈린다.",
     "post_ids": ["p7", "p8", "p9"], "unverified": False,
     "framing": {"ruliweb": "기대감", "fmkorea": "출시일 공유", "dcinside": "가격 비판"}},
    {"headline": "[예시] A그룹 컴백 티저 공개", "category": "연예",
     "summary": "A그룹이 신곡 티저를 공개했다.", "post_ids": ["p5", "p6"], "unverified": False,
     "framing": {"theqoo": "콘셉트 호평", "natepann": "스타일 호불호"}},
]}

if __name__ == "__main__":
    now = store.now_iso()
    rows = [{"url": f"https://example.com/{i}", "title": t, "source": s, "best_rank": i,
             "first_seen": now, "last_seen": now} for i, (s, t) in enumerate(ROWS)]
    issues = cluster.cluster_with_llm(rows, lambda _: json.dumps(FAKE, ensure_ascii=False))
    out = {"updated_at": now, "method": "demo", "post_count": len(rows),
           "sources": [{"key": "demo", "name": "예시 데이터", "status": "실제 수집 전"}],
           "issues": issues}
    path = Path(__file__).parent / "site" / "issues.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"예시 이슈 {len(issues)}개 → {path}")
