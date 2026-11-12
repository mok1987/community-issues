"""'이게 무슨 말이에요?' — 사람이 검수한 요즘 말 사전(data/words.json)에서 지금 제목에 나온 말만 고른다.

AI가 찾아낸 새 말은 바로 화면에 내보내지 않고 data/word_candidates.json 에 '검토 후보'로만 쌓는다.
(AI는 뜻을 그럴듯하게 지어내거나 욕이 섞인 말을 순화해 버리는 일이 있어서, 사람이 확인한 뒤 사전에 옮긴다)
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [w for w in json.loads(path.read_text(encoding="utf-8")) if w.get("word") and w.get("meaning")]


def _pattern(word: str) -> re.Pattern:
    w = re.escape(word)
    if len(word) == 1:  # '찐', '짤', '밈' 같은 한 글자는 다른 낱말 속 글자와 헷갈리지 않게 앞뒤가 한글이 아닐 때만
        return re.compile(rf"(?<![가-힣]){w}(?![가-힣])")
    return re.compile(w, re.I)


def find(titles: list[str], dictionary: list[dict], limit: int = 10) -> list[dict]:
    """제목들에 나온 사전 단어를 많이 나온 순으로."""
    text = "\n".join(titles)
    hits = []
    for entry in dictionary:
        n = len(_pattern(entry["word"]).findall(text))
        if n:
            hits.append((n, entry))
    hits.sort(key=lambda x: -x[0])
    return [{"word": e["word"], "meaning": e["meaning"], "example": e.get("example", "")} for _, e in hits[:limit]]


def update_candidates(path: Path, proposals: list[dict], dictionary: list[dict], at: str) -> int:
    """AI가 제안한 새 말을 검토 후보 파일에 쌓는다. 이미 사전에 있는 말은 제외. 새로 추가된 수를 돌려준다."""
    known = {w["word"] for w in dictionary}
    cands = {c["word"]: c for c in (json.loads(path.read_text(encoding="utf-8")) if path.exists() else [])}
    added = 0
    for p in proposals:
        word = p.get("word")
        if not word or word in known:
            continue
        if word in cands:
            cands[word]["seen"] = cands[word].get("seen", 1) + 1
            cands[word]["last_seen"] = at
        else:
            cands[word] = {"word": word, "ai_meaning": p.get("meaning", ""), "example": p.get("example", ""),
                           "seen": 1, "first_seen": at, "last_seen": at}
            added += 1
    ordered = sorted(cands.values(), key=lambda c: (-c.get("seen", 1), c["word"]))[:200]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding="utf-8")
    return added
