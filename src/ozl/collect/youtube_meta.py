#!/usr/bin/env python3
"""YouTube Data API v3 로 채널 업로드 전수 메타데이터를 수집한다 (OZL Phase 1A).

사용:
    python -m ozl.collect.youtube_meta --handle syukaworld
    python -m ozl.collect.youtube_meta --handle moneymoneycomics --out private/meta/moneycomics_videos.jsonl

비용: playlistItems.list 1유닛/50편 + videos.list 1유닛/50편 → 2,500편 ≈ 100유닛 (일 한도 10,000).
정책: API 데이터는 private/meta/ 에만 저장(30일 주기 재조회·갱신), 공개는 집계만.
키: 환경변수 YOUTUBE_API_KEY 또는 저장소 루트 .env.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

import requests

from ozl.research import ledger

ROOT = pathlib.Path(__file__).resolve().parents[3]
API = "https://www.googleapis.com/youtube/v3"
SLEEP = 0.2  # 호출 간격(초) — 부하·429 회피


def load_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("YOUTUBE_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("YOUTUBE_API_KEY 없음 (.env 또는 환경변수)")
    return key


class Quota:
    units = 0


def get(path: str, key: str, **params) -> dict:
    ledger.require("youtube_data_api_meta")   # 대장에서 collect 가 허용이 아니면 Blocked — 요청하지 않는다
    params["key"] = key
    for attempt in range(5):
        r = requests.get(f"{API}/{path}", params=params, timeout=30)
        Quota.units += 1
        if r.status_code == 200:
            time.sleep(SLEEP)
            return r.json()
        try:
            err = r.json().get("error", {})
        except Exception:  # noqa: BLE001
            err = {"message": r.text[:200]}
        reason = ";".join(e.get("reason", "") for e in err.get("errors", [])) or err.get("status", "")
        if "quotaExceeded" in reason or "dailyLimitExceeded" in reason:
            sys.exit(f"[quota] 일일 할당량 소진 — 중단 (누적 {Quota.units}유닛): {err.get('message')}")
        if r.status_code in (429, 500, 503) and attempt < 4:
            wait = 2 ** attempt
            print(f"[retry] {r.status_code} {reason} → {wait}s 대기", file=sys.stderr)
            time.sleep(wait)
            continue
        sys.exit(f"[error] {r.status_code} {reason}: {err.get('message')}")
    raise RuntimeError("unreachable")


def channel_by_handle(handle: str, key: str) -> dict:
    d = get("channels", key, part="id,snippet,statistics,contentDetails", forHandle=handle)
    items = d.get("items") or []
    if not items:
        sys.exit(f"채널 없음: @{handle}")
    it = items[0]
    return {
        "channel_id": it["id"],
        "title": it["snippet"]["title"],
        "uploads": it["contentDetails"]["relatedPlaylists"]["uploads"],
        "video_count": int(it["statistics"].get("videoCount", 0)),
        "subscriber_count": int(it["statistics"].get("subscriberCount", 0)),
    }


def playlist_video_ids(playlist_id: str, key: str) -> list[str]:
    ids: list[str] = []
    token = None
    while True:
        params = dict(part="contentDetails", playlistId=playlist_id, maxResults=50)
        if token:
            params["pageToken"] = token
        d = get("playlistItems", key, **params)
        ids.extend(i["contentDetails"]["videoId"] for i in d.get("items", []))
        token = d.get("nextPageToken")
        print(f"\r[playlist] {len(ids)}개 수집", end="", file=sys.stderr)
        if not token:
            break
    print(file=sys.stderr)
    return ids


def videos_detail(ids: list[str], key: str):
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        d = get(
            "videos", key,
            part="snippet,contentDetails,statistics,liveStreamingDetails,topicDetails",
            id=",".join(chunk), maxResults=50,
        )
        for it in d.get("items", []):
            yield it
        print(f"\r[videos] {min(i + 50, len(ids))}/{len(ids)}", end="", file=sys.stderr)
    print(file=sys.stderr)


def iso_duration_to_sec(s: str) -> int:
    # PT1H2M3S
    import re
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def flatten(it: dict, fetched_at: str) -> dict:
    sn, cd, st = it.get("snippet", {}), it.get("contentDetails", {}), it.get("statistics", {})
    live = it.get("liveStreamingDetails") or {}
    dur = iso_duration_to_sec(cd.get("duration", ""))
    kind = "live" if live else ("short" if dur and dur <= 60 else "video")
    return {
        "video_id": it["id"],
        "title": sn.get("title"),
        "published_at": sn.get("publishedAt"),
        "duration_sec": dur,
        "kind": kind,
        "view_count": int(st["viewCount"]) if st.get("viewCount") else None,
        "like_count": int(st["likeCount"]) if st.get("likeCount") else None,
        "comment_count": int(st["commentCount"]) if st.get("commentCount") else None,
        "category_id": sn.get("categoryId"),
        "tags": sn.get("tags", []),
        "topics": [t.rsplit("/", 1)[-1] for t in (it.get("topicDetails") or {}).get("topicCategories", [])],
        "description": sn.get("description", ""),
        "default_audio_language": sn.get("defaultAudioLanguage"),
        "caption": cd.get("caption"),
        "live_actual_start": live.get("actualStartTime"),
        "live_actual_end": live.get("actualEndTime"),
        "channel_id": sn.get("channelId"),
        "channel_title": sn.get("channelTitle"),
        "fetched_at": fetched_at,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle", required=True, help="채널 핸들(@ 없이)")
    ap.add_argument("--out", help="JSONL 출력 경로 (기본 private/meta/<handle>_videos.jsonl)")
    args = ap.parse_args()
    key = load_key()
    out = pathlib.Path(args.out) if args.out else ROOT / "private" / "meta" / f"{args.handle}_videos.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    ch = channel_by_handle(args.handle, key)
    print(f"[channel] {ch['title']} {ch['channel_id']} videoCount={ch['video_count']} subs={ch['subscriber_count']}", file=sys.stderr)
    ids = playlist_video_ids(ch["uploads"], key)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    kinds: dict[str, int] = {}
    total_sec = 0
    with out.open("w", encoding="utf-8") as f:
        for it in videos_detail(ids, key):
            row = flatten(it, fetched_at)
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
            total_sec += row["duration_sec"]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    summary = {
        "handle": args.handle, "channel": ch, "playlist_ids": len(ids), "written": n,
        "kinds": kinds, "total_hours": round(total_sec / 3600, 1), "quota_units": Quota.units,
        "fetched_at": fetched_at, "out": str(out.relative_to(ROOT)),
    }
    (out.with_suffix(".summary.json")).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
