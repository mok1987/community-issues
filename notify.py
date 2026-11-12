"""화제 알림 보내기 — GitHub Actions(notify.yml)가 아침 7시~밤 10시, 약 2시간 반마다 실행.

알림 구독자 관리와 발송은 OneSignal(무료 웹 푸시 서비스)이 맡는다.
필요한 비밀값: ONESIGNAL_APP_ID, ONESIGNAL_API_KEY (없으면 아무것도 안 함)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent
KST = timezone(timedelta(hours=9))
API = "https://api.onesignal.com/notifications?c=push"
TITLE = "실시간 화제를 확인해보세요"


def in_quiet_hours(now: datetime) -> bool:
    """밤 10시 반 이후 ~ 아침 7시 전은 보내지 않는다 (GitHub 예약 실행이 늦어지는 경우 대비)."""
    return now.hour < 7 or (now.hour == 22 and now.minute > 30) or now.hour > 22


def top_line(data: dict) -> str:
    hot = [i for i in data.get("issues", []) if i.get("hot")] or data.get("issues", [])
    return f"지금 1위: {hot[0]['headline']}" if hot else "지금 온라인에서 화제인 이야기를 모아뒀어요."


def build(app_id: str, line: str, url: str) -> dict:
    return {
        "app_id": app_id,
        "target_channel": "push",
        "included_segments": ["Total Subscriptions"],
        "headings": {"en": TITLE, "ko": TITLE},
        "contents": {"en": line, "ko": line},
        "url": url,
        "web_push_topic": "yojeummwo-hot",   # 새 알림이 앞 알림을 대체 (쌓이지 않게)
        "ttl": 2 * 60 * 60,                   # 폰이 꺼져 있다가 2시간 넘게 지난 알림은 버림
    }


def main() -> int:
    app_id = (os.environ.get("ONESIGNAL_APP_ID") or "").strip()
    key = (os.environ.get("ONESIGNAL_API_KEY") or "").strip()
    if not (app_id and key):
        print("[알림] OneSignal 키가 없어 건너뜀")
        return 0
    now = datetime.now(KST)
    if in_quiet_hours(now) and os.environ.get("FORCE") != "1":
        print(f"[알림] {now:%H:%M} 조용한 시간이라 건너뜀")
        return 0
    data = json.loads((ROOT / "site" / "issues.json").read_text(encoding="utf-8"))
    url = (os.environ.get("SITE_URL") or "https://hotnow.kr/").strip()
    body = build(app_id, top_line(data), url)
    resp = requests.post(API, json=body, timeout=30,
                         headers={"Authorization": f"Key {key}", "Content-Type": "application/json"})
    if resp.status_code == 200 and "Total Subscriptions" in resp.text and "invalid" in resp.text.lower():
        body["included_segments"] = ["Subscribed Users"]   # 예전 이름을 쓰는 앱 대비
        resp = requests.post(API, json=body, timeout=30,
                             headers={"Authorization": f"Key {key}", "Content-Type": "application/json"})
    print(f"[알림] {now:%H:%M} 발송 → HTTP {resp.status_code} {resp.text[:300]}")
    return 0 if resp.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
