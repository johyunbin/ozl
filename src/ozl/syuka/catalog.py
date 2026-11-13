"""슈카월드 영상 목록 = 채널 업로드 목록(유튜브 API 메타) ∪ Trading 쪽 전사 목록(index.csv).

메타 파일에는 통계 칸이 있지만 여기서는 KEEP 에 적은 칸만 꺼낸다(약관 — 통계는 읽지도 저장하지도 않는다).
"""
from __future__ import annotations

import csv
import json
import pathlib
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
META = ROOT / "private" / "meta"
TRANSCRIPTS = ROOT / "private" / "transcripts"
EXPORT_IDX = TRANSCRIPTS / "trading_export" / "index.csv"
KST = timezone(timedelta(hours=9))

KEEP = ("video_id", "title", "published_at", "duration_sec", "kind")  # 업로드 목록에서 쓰는 칸 전부
INDEX_CHANNEL = "syuka"

# 종류 구분 규칙
# - 쇼츠·짧은 클립: API kind 가 short 이거나 길이 180초 이하(유튜브 쇼츠 상한 3분. 1~3분 본편도 예고·짤 성격이라 함께 묶는다)
# - 생방송 전체: 길이 90분 이상. 기존 라이브 매핑(analyze/catalog.livemap)과 Trading 의 is_live_full(최소 92분, 비라이브 최대 84분)이 같은 선을 쓴다.
#   2018~2019 라디오·풀버전 업로드도 여기에 든다. API kind 가 live 이고 60분 이상인 옛 풀버전(61·68분)도 생방송 전체로 본다.
# - 그 밖: 길이 0(예정·삭제), API kind 가 live 인데 60분 미만(휴방 공지·부분본)
# - 본편: 나머지
KINDS = ("본편", "생방송 전체", "쇼츠·짧은 클립", "그 밖")
SHORT_MAX = 180
LIVE_MIN = 5400
LIVE_KIND_MIN = 3600


def classify(duration_sec: int, api_kind: str | None) -> str:
    d = int(duration_sec or 0)
    if d <= 0:
        return "그 밖"
    if api_kind == "short" or d <= SHORT_MAX:
        return "쇼츠·짧은 클립"
    if d >= LIVE_MIN or (api_kind == "live" and d >= LIVE_KIND_MIN):
        return "생방송 전체"
    if api_kind == "live":
        return "그 밖"
    return "본편"


def to_kst(published_at: str) -> str:
    return datetime.fromisoformat(published_at.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d %H:%M")


def upload_files(meta: pathlib.Path = META) -> list[pathlib.Path]:
    """채널 업로드 목록 파일들. 오래된 것부터(뒤 파일이 앞 값을 덮는다)."""
    ps = list(meta.glob("syukaworld_videos*.jsonl")) + list(meta.glob("recent_syukaworld_*.jsonl"))
    return sorted(ps, key=lambda p: (p.stat().st_mtime, p.name))


def load_uploads(files: list[pathlib.Path]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in files:
        for line in p.open(encoding="utf-8"):
            if not line.strip():
                continue
            raw = json.loads(line)
            out[raw["video_id"]] = {k: raw.get(k) for k in KEEP}
    return out


def load_index(path: pathlib.Path = EXPORT_IDX) -> dict[str, dict]:
    cols = ("video_id", "title", "upload_at", "duration_sec", "transcript_source", "chars", "has_transcript")
    if not path.exists():
        return {}
    return {r["video_id"]: {k: r.get(k, "") for k in cols}
            for r in csv.DictReader(path.open(encoding="utf-8")) if r.get("channel") == INDEX_CHANNEL}


def find_transcript(video_id: str, root: pathlib.Path = TRANSCRIPTS) -> pathlib.Path | None:
    for p in (root / "trading_export" / INDEX_CHANNEL / f"{video_id}.json",
              root / "daglo" / f"{video_id}.json", root / "whisper" / f"{video_id}.json"):
        if p.exists():
            return p
    return None


def build(uploads: dict[str, dict], index: dict[str, dict], transcripts: pathlib.Path = TRANSCRIPTS,
          repo_root: pathlib.Path = ROOT) -> list[dict]:
    """두 목록을 합친 영상 행. 업로드 목록에 있으면 그 제목·시각·길이를 쓴다."""
    rows = []
    for vid in sorted(set(uploads) | set(index)):
        u, t = uploads.get(vid), index.get(vid)
        if u:
            title, at, dur, api_kind = u["title"], to_kst(u["published_at"]), int(u["duration_sec"] or 0), u["kind"]
        else:
            title, at, dur, api_kind = t["title"], t["upload_at"][:16], int(t["duration_sec"] or 0), None
        path = find_transcript(vid, transcripts)
        rel = str(path.relative_to(repo_root)) if path and path.is_relative_to(repo_root) else (str(path) if path else "")
        rows.append({
            "video_id": vid, "title": title, "upload_at": at, "duration_sec": dur,
            "kind": classify(dur, api_kind),
            "has_transcript": int(path is not None),
            "transcript_source": (t or {}).get("transcript_source", "") if path else "",
            "transcript_path": rel,
            "chars": int((t or {}).get("chars") or 0) if path else 0,
            "in_uploads": int(u is not None), "in_transcripts": int(t is not None),
        })
    return rows


def load_all() -> list[dict]:
    return build(load_uploads(upload_files()), load_index())


def read_transcript(path: str | pathlib.Path, repo_root: pathlib.Path | None = None) -> str:
    """전사 본문(text 칸). 없으면 segments 의 text 를 잇는다."""
    p = pathlib.Path(path)
    p = p if p.is_absolute() else (repo_root or ROOT) / p
    d = json.loads(p.read_text(encoding="utf-8"))
    return d.get("text") or "\n".join(s.get("text", "") for s in d.get("segments") or [])
