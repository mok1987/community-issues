"""화제도 기록: 30분마다 이슈별 글 수를 남겨 두고, 최근 6시간 흐름(그래프·배지)을 만든다.

이슈는 실행할 때마다 AI가 새로 묶기 때문에 이름이 매번 다를 수 있다.
그래서 '같은 이슈'는 겹치는 글 주소로 찾는다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

KEEP_HOURS = 6
POINTS = 13  # 6시간 전부터 지금까지 30분 간격 13칸


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def save(path: Path, snaps: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snaps, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def snapshot(issues: list[dict], at: str) -> dict:
    return {"at": at, "issues": [{"urls": [p["url"] for p in it["posts"]], "n": len(it["posts"])}
                                 for it in issues]}


def _match(urls: set[str], snap: dict) -> int:
    """그 시점에 이 이슈와 글이 가장 많이 겹친 이슈의 글 수 (없으면 0)."""
    best, n = 0, 0
    for it in snap.get("issues", []):
        overlap = len(urls & set(it.get("urls", [])))
        if overlap > best:
            best, n = overlap, it.get("n", 0)
    return n


def series(urls: set[str], snaps: list[dict], at: datetime) -> list[int]:
    """6시간 전 → 지금, 30분 칸마다 글 수. 그 칸에 기록이 없으면 앞 칸 값을 이어 쓴다."""
    slots: list[int | None] = [None] * POINTS
    for s in snaps:
        try:
            t = datetime.fromisoformat(s["at"])
        except (KeyError, ValueError):
            continue
        back = round((at - t).total_seconds() / 1800)  # 몇 칸 전인지
        if 0 <= back < POINTS:
            slots[POINTS - 1 - back] = _match(urls, s)
    out, last = [], 0
    for v in slots:
        last = v if v is not None else last
        out.append(last)
    return out


def label(values: list[int], age_hours: float | None = None) -> tuple[str, str]:
    """(배지 글자, 방향 up/down/flat/new) — 지금 값과 3시간 전 값을 비교.
    앞선 기록이 없을 때는 처음 보인 지 2시간 안쪽이면 '새로 떠오름', 아니면 그냥 '화제 중'
    (기록을 막 쌓기 시작했을 때 오래된 이슈가 '새로 떠오름'으로 나오지 않게)."""
    now, before = values[-1], values[len(values) // 2]
    earlier = [v for v in values[:-1] if v > 0]
    if not earlier:
        if age_hours is not None and age_hours > 2:
            return "화제 중", "flat"
        return "새로 떠오름", "new"
    if before == 0:
        before = earlier[0]
    ratio = now / before if before else 1
    if ratio >= 1.5:
        return "급상승", "up"
    if ratio >= 1.1:
        return "상승", "up"
    if ratio <= 0.7:
        return "주춤", "down"
    return "유지", "flat"


def hours_label(first_seen: str | None, at: datetime) -> str:
    if not first_seen:
        return ""
    try:
        h = (at - datetime.fromisoformat(first_seen)).total_seconds() / 3600
    except ValueError:
        return ""
    if h < 1:
        return "방금 떠오른 화제"
    if h < 24:
        return f"{int(h)}시간째 화제"
    return f"{int(h // 24)}일째 화제"


def apply(issues: list[dict], path: Path, at_iso: str) -> None:
    """issues 에 trend 항목을 붙이고 기록 파일을 갱신한다."""
    at = datetime.fromisoformat(at_iso)
    cutoff = at - timedelta(hours=KEEP_HOURS, minutes=20)
    snaps = [s for s in load(path) if _after(s, cutoff)]
    for it in issues:
        urls = {p["url"] for p in it["posts"]}
        values = series(urls, snaps, at)
        values[-1] = len(it["posts"])
        text, direction = label(values, _age(it.get("first_seen"), at))
        it["trend"] = {"series": values, "label": text, "dir": direction,
                       "hours": hours_label(it.get("first_seen"), at)}
    snaps.append(snapshot(issues, at_iso))
    save(path, snaps)


def _age(first_seen: str | None, at: datetime) -> float | None:
    try:
        return (at - datetime.fromisoformat(first_seen)).total_seconds() / 3600 if first_seen else None
    except ValueError:
        return None


def _after(snap: dict, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(snap["at"]) >= cutoff
    except (KeyError, ValueError):
        return False
