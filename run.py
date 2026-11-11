"""이슈 묶음 실행 스크립트.

사용법:
  python run.py            수집 → 묶기 → 댓글 반응 → site/issues.json 갱신
  python run.py --check    각 출처에서 글이 제대로 잡히는지만 확인 (저장 안 함)
  python run.py --no-ai    API 없이 단순 묶기만

환경변수:
  GEMINI_API_KEY    Google AI Studio 무료 키 (없으면 단순 묶기, 쉬운 설명·반응 없음)
  YOUTUBE_API_KEY   YouTube Data API v3 키 (없으면 유튜브 제외)
  GEMINI_MODEL      기본 gemini-2.5-flash-lite
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from issuebundle import cluster, collect, reactions, store, youtube
from issuebundle.sources import SOURCES, enabled_sources

ROOT = Path(__file__).parent
POSTS_PATH = ROOT / "data" / "posts.json"
OUT_PATH = ROOT / "site" / "issues.json"
TOP_N = 5


def env_key(name: str) -> str | None:
    """Secrets에 붙여넣을 때 섞여 들어간 줄바꿈·공백을 지운다."""
    value = (os.environ.get(name) or "").strip()
    return value or None


def collect_everything(yt_key: str | None) -> tuple[list[collect.Post], dict[str, str]]:
    posts, status = collect.collect_all(enabled_sources("web"))
    if enabled_sources("youtube"):
        if yt_key:
            yt_posts, status["youtube"] = youtube.fetch_popular(yt_key)
            posts.extend(yt_posts)
        else:
            status["youtube"] = "YOUTUBE_API_KEY 없음, 건너뜀"
    return posts, status


def check() -> None:
    posts, status = collect_everything(env_key("YOUTUBE_API_KEY"))
    for key, msg in status.items():
        print(f"\n== {key}: {msg}")
        for p in [p for p in posts if p.source == key][:5]:
            print(f"   {p.rank:>2}. {p.title}  →  {p.url}")


def build_tops(fresh: list[collect.Post], issues: list[dict], top_meta: dict[str, dict]) -> list[dict]:
    """출처별 현재 TOP 5. 각 글이 어떤 이슈에 속하는지(화제 중 여부)도 표시."""
    issue_of = {p["url"]: it for it in issues for p in it["posts"]}
    names = {s.key: s.name for s in SOURCES}
    tops = []
    for key in dict.fromkeys(p.source for p in fresh):
        items = []
        for p in sorted((p for p in fresh if p.source == key), key=lambda p: p.rank)[:TOP_N]:
            meta, it = top_meta.get(p.url, {}), issue_of.get(p.url)
            items.append({
                "title": p.title, "url": p.url,
                "easy": meta.get("easy", ""),
                "category": meta.get("category") or (it["category"] if it else ""),
                "issue_id": it["id"] if it else None,
                "hot": bool(it and it["hot"]),
                "comment_count": p.comment_count,
            })
        tops.append({"key": key, "name": names.get(key, key), "items": items})
    return tops


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-ai", action="store_true")
    args = parser.parse_args()

    yt_key = env_key("YOUTUBE_API_KEY")
    if args.check:
        check()
        return

    fresh, status = collect_everything(yt_key)
    for key, msg in status.items():
        print(f"[수집] {key}: {msg}")

    posts = store.prune(store.merge(store.load(POSTS_PATH), fresh))
    store.save(POSTS_PATH, posts)

    window = store.recent(posts)
    top_urls = {p.url for p in fresh if p.rank < TOP_N}
    gemini_key = env_key("GEMINI_API_KEY")
    llm = None if (args.no_ai or not gemini_key) else cluster.gemini_llm(gemini_key)

    issues, top_meta, method = cluster.make_issues(window, llm, top_urls)
    print(f"[묶기] 최근 글 {len(window)}개 → 이슈 {len(issues)}개, "
          f"화제 중 {sum(i['hot'] for i in issues)}개 ({method})")

    filled = reactions.add_reactions(issues, llm, yt_key)
    print(f"[반응] 댓글 반응 요약 {filled}건")

    names = {s.key: s.name for s in SOURCES}
    payload = {
        "updated_at": store.now_iso(),
        "method": method,
        "post_count": len(window),
        "sources": [{"key": k, "name": names.get(k, k), "status": v} for k, v in status.items()],
        "issues": issues[:30],
        "tops": build_tops(fresh, issues, top_meta),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[저장] {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
