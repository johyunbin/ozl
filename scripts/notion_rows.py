#!/usr/bin/env python3
"""Notion 에 올릴 행을 이슈 기록에서 뽑는다 — 요약 칸만.

쓰는 법: .venv/bin/python scripts/notion_rows.py [이슈 번호 …]   (번호가 없으면 전부. 결과는 JSON 한 덩이)

Notion 에 쓰는 일은 이 스크립트가 하지 않는다. 세션이 Notion 커넥터로 한다: DB 「이슈」에서 `이슈 번호`가 같은 줄을 찾아 있으면 고치고
없으면 만든다. 「제작물」은 `제작물 번호`로 찾는다. 두 번 돌려도 줄이 늘지 않는다. `메모` 칸은 사용자의 것이라 쓰지 않는다.
DB 의 식별자는 `private/notion_issues.json` 에 있다.

올리지 않는 것: 본문(확인된 사실, 주장의 문장, 흐름, 입장), 근거 사본, 공개하지 않는 주장의 내용, 개인 정보.
이슈 전체가 공개 제외면 제목도 올리지 않는다.
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from ozl.issues import model, revisions  # noqa: E402

VERDICT_ORDER = ("확인", "일부 맞음", "사실과 다름", "확인 못 함")
HIDDEN_TITLE = "(공개 제외 이슈)"


def issue_date(issue_id: str) -> str:
    d = issue_id[1:9]
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def verdict_line(issue: dict) -> str:
    """공개 대상 주장의 판정 집계 한 줄."""
    c = collections.Counter(cl.get("verdict") for cl in issue.get("claims") or []
                            if isinstance(cl, dict) and cl.get("publish") == "게시 가능")
    parts = [f"{v} {c[v]}" for v in VERDICT_ORDER if c.get(v)]
    return ", ".join(parts) if parts else "판정할 주장 없음"


def review_line(issue: dict, content_hash: str) -> str:
    """지금 내용에 붙은 검토만: 종류, 모델, 결과."""
    out = []
    for r in issue.get("reviews") or []:
        if isinstance(r, dict) and (r.get("after_hash") or r.get("content_hash")) == content_hash:
            out.append(f"{r.get('kind')} {r.get('by_model')} {r.get('result')}")
    return " / ".join(out) if out else "지금 내용에 붙은 검토 없음"


def state_of(row: dict) -> str:
    if row.get("latest_public"):
        return "게시"
    return row.get("work_state") if row.get("work_state") in ("작성 중", "검토 대기", "게시 대기", "보류") else "작성 중"


def issue_row(row: dict) -> dict:
    issue = model.load_issue(row["id"])
    pub = (issue.get("publish") or {}).get("state")
    title = (issue.get("titles") or {}).get("chosen") or ""
    return {
        "이슈 번호": row["id"],
        "제목": HIDDEN_TITLE if pub == "공개 제외" else title,
        "날짜": issue_date(row["id"]),
        "분야": issue.get("category"),
        "상태": state_of(row),
        "게시 가부": pub,
        "민감 표시": list(issue.get("sensitive") or []),
        "슈카 덱": issue.get("syuka_deck"),
        "판 번호": row.get("rev"),
        "판정 집계": verdict_line(issue) if pub != "공개 제외" else "",
        "검토": f"{row.get('review')}: {review_line(issue, row.get('content_hash'))}",
        "사이트 주소": None,   # 게시한 뒤에 채운다(공개 주소가 정해져야 한다)
    }


def product_rows(row: dict, cards_root: pathlib.Path) -> list[dict]:
    """이슈 한 건의 제작물 줄. 있는 것만 낸다."""
    issue = model.load_issue(row["id"])
    slug, rev = issue.get("slug"), row.get("rev")
    stage = {"게시": "게시", "게시 대기": "게시 대기", "검토 대기": "검토 대기"}.get(state_of(row), "만드는 중")
    out = [{"제작물 번호": f"{row['id']}:web", "이름": f"{row['id']} 웹 이슈 화면", "이슈 번호": row["id"], "형식": "웹 이슈 화면",
            "단계": stage, "판 번호": rev, "파일 위치": f"private/desk/issues/{row['id']}/"}]
    d = cards_root / str(slug) / f"r{rev}"
    n = len(list(d.glob("*.png"))) if d.is_dir() else 0
    if n:
        out.append({"제작물 번호": f"{row['id']}:cards", "이름": f"{row['id']} 카드 그림 {n}장", "이슈 번호": row["id"], "형식": "카드 그림",
                    "단계": stage, "판 번호": rev, "파일 위치": str(d.relative_to(ROOT)) if ROOT in d.parents else str(d)})
    return out


def build(ids=None, cards_root: pathlib.Path | None = None) -> dict:
    rows = revisions.status_rows(ids or None)
    cards_root = cards_root or ROOT / "private" / "out" / "cards"
    return {"issues": [issue_row(r) for r in rows], "products": [p for r in rows for p in product_rows(r, cards_root)]}


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1:]), ensure_ascii=False, indent=1))
