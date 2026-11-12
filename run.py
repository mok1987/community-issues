"""요즘뭐 실행 스크립트.

사용법:
  python run.py            수집 → 묶기 → site/issues.json 갱신
  python run.py --check    각 출처에서 글이 제대로 잡히는지만 확인 (저장 안 함)
  python run.py --no-ai    API 없이 단순 묶기만

환경변수:
  GEMINI_API_KEY    Google AI Studio 무료 키 (없으면 단순 묶기, 쉬운 설명·반응 없음)
  YOUTUBE_API_KEY   YouTube Data API v3 키 (없으면 유튜브 제외)
  GEMINI_MODEL      비워두면 쓸 수 있는 가장 새 Flash-Lite 모델을 자동 선택
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from issuebundle import cluster, collect, store, words as wordbook, youtube
from issuebundle.sources import SOURCES, enabled_sources

ROOT = Path(__file__).parent
POSTS_PATH = ROOT / "data" / "posts.json"
WORDS_PATH = ROOT / "data" / "words.json"            # 사람이 검수한 요즘 말 사전 (화면에 나가는 것)
CANDIDATES_PATH = ROOT / "data" / "word_candidates.json"  # AI가 찾은 새 말 (검토 후보, 화면에 안 나감)
OUT_PATH = ROOT / "site" / "issues.json"
TOP_N = 10


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


def build_tops(fresh: list[collect.Post], issues: list[dict], top_meta: dict[str, dict],
               status: dict[str, str] | None = None) -> list[dict]:
    """출처별 현재 TOP 10. 각 글이 어떤 이슈에 속하는지(화제 중 여부)도 표시.
    status 를 주면 수집 못 한 출처도 빈 목록 + 상태로 넣는다 (화면에 '수집 불가' 표시용)."""
    issue_of = {p["url"]: it for it in issues for p in it["posts"]}
    names = {s.key: s.name for s in SOURCES}
    urls = {s.key: s.list_url for s in SOURCES}  # 수집 불가 출처는 이 주소로 '직접 보러 가기'
    tops = []
    keys = list(dict.fromkeys([*(status or {}), *(p.source for p in fresh)]))
    for key in keys:
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
        msg = (status or {}).get(key, f"{len(items)}개")
        tops.append({"key": key, "name": names.get(key, key), "items": items,
                     "list_url": urls.get(key, ""),
                     "state": collect.status_kind(msg), "status": msg})
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
    llm = None
    if gemini_key and not args.no_ai:
        try:
            llm = cluster.gemini_llm(gemini_key)
        except Exception as e:  # noqa: BLE001 - 모델 조회 실패해도 페이지는 갱신
            print(f"[경고] Gemini 모델 확인 실패: {e}")

    issues, top_meta, method = cluster.make_issues(window, llm, top_urls)
    print(f"[묶기] 최근 글 {len(window)}개 → 이슈 {len(issues)}개, "
          f"화제 중 {sum(i['hot'] for i in issues)}개 ({method})")

    # "이게 무슨 말이에요?" — 지금 화제인 글 제목에 나온 요즘 말 풀이
    titles = [p.title for p in fresh if p.rank < TOP_N] + [p["title"] for it in issues if it["hot"] for p in it["posts"]]
    dictionary = wordbook.load(WORDS_PATH)
    words = wordbook.find(titles, dictionary)
    print(f"[요즘 말] 사전에서 {len(words)}개 찾음")
    if llm:
        added = wordbook.update_candidates(CANDIDATES_PATH, cluster.explain_words(titles, llm), dictionary, store.now_iso())
        print(f"[요즘 말] 새 검토 후보 {added}개 (data/word_candidates.json)")

    names = {s.key: s.name for s in SOURCES}
    payload = {
        "updated_at": store.now_iso(),
        "method": method,
        "post_count": len(window),
        "sources": [{"key": k, "name": names.get(k, k), "status": v, "state": collect.status_kind(v)}
                    for k, v in status.items()],
        "issues": issues[:30],
        "tops": build_tops(fresh, issues, top_meta, status),
        "words": words,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[저장] {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
