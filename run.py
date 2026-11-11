"""이슈 묶음 0단계 실행 스크립트.

사용법:
  python run.py            수집 → 묶기 → site/issues.json 갱신
  python run.py --check    각 커뮤니티에서 글이 제대로 잡히는지만 확인 (저장 안 함)
  python run.py --no-ai    API 없이 단순 묶기만

환경변수:
  GEMINI_API_KEY   Google AI Studio에서 받은 무료 키 (없으면 단순 묶기)
  GEMINI_MODEL     기본 gemini-2.5-flash-lite
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from issuebundle import cluster, collect, store
from issuebundle.sources import enabled_sources, SOURCES

ROOT = Path(__file__).parent
POSTS_PATH = ROOT / "data" / "posts.json"
OUT_PATH = ROOT / "site" / "issues.json"


def check() -> None:
    posts, status = collect.collect_all(enabled_sources())
    for s in enabled_sources():
        print(f"\n== {s.name} ({s.key}): {status[s.key]}")
        for p in [p for p in posts if p.source == s.key][:5]:
            print(f"   {p.rank:>2}. {p.title}  →  {p.url}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-ai", action="store_true")
    args = parser.parse_args()

    if args.check:
        check()
        return

    fresh, status = collect.collect_all(enabled_sources())
    for key, msg in status.items():
        print(f"[수집] {key}: {msg}")

    posts = store.merge(store.load(POSTS_PATH), fresh)
    posts = store.prune(posts)
    store.save(POSTS_PATH, posts)

    window = store.recent(posts)
    api_key = os.environ.get("GEMINI_API_KEY")
    llm = None if (args.no_ai or not api_key) else cluster.gemini_llm(api_key)
    issues, method = cluster.make_issues(window, llm)
    print(f"[묶기] 최근 글 {len(window)}개 → 이슈 {len(issues)}개 ({method})")

    names = {s.key: s.name for s in SOURCES}
    payload = {
        "updated_at": store.now_iso(),
        "method": method,
        "post_count": len(window),
        "sources": [{"key": k, "name": names.get(k, k), "status": v} for k, v in status.items()],
        "issues": issues[:40],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[저장] {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
