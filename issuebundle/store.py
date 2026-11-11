"""수집한 글을 data/posts.json 에 누적한다 (DB 대신 JSON 파일, 0단계용)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .collect import Post

KST = timezone(timedelta(hours=9))
WINDOW_HOURS = 24  # 이 시간 안에 인기 목록에 보인 글만 이슈 묶기에 쓴다


def now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, posts: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(posts, ensure_ascii=False, indent=1), encoding="utf-8")


def merge(existing: dict[str, dict], fresh: list[Post], at: str | None = None) -> dict[str, dict]:
    """새로 본 글은 추가하고, 이미 있던 글은 last_seen 과 최고 순위만 갱신한다."""
    at = at or now_iso()
    for p in fresh:
        row = existing.get(p.url)
        if row is None:
            existing[p.url] = {
                "url": p.url, "title": p.title, "source": p.source,
                "best_rank": p.rank, "first_seen": at, "last_seen": at,
            }
        else:
            row["last_seen"] = at
            row["best_rank"] = min(row["best_rank"], p.rank)
            row["title"] = p.title or row["title"]
    return existing


def prune(posts: dict[str, dict], keep_hours: int = 72, at: datetime | None = None) -> dict[str, dict]:
    """오래된 글은 파일에서 지운다 (원문이 지워졌을 수도 있으므로 오래 보관하지 않는다)."""
    at = at or datetime.now(KST)
    cutoff = at - timedelta(hours=keep_hours)
    return {u: r for u, r in posts.items() if datetime.fromisoformat(r["last_seen"]) >= cutoff}


def recent(posts: dict[str, dict], hours: int = WINDOW_HOURS, at: datetime | None = None,
           max_posts: int = 400) -> list[dict]:
    at = at or datetime.now(KST)
    cutoff = at - timedelta(hours=hours)
    rows = [r for r in posts.values() if datetime.fromisoformat(r["last_seen"]) >= cutoff]
    rows.sort(key=lambda r: (r["last_seen"], -r["best_rank"]), reverse=True)
    return rows[:max_posts]
