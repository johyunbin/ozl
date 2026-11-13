"""덱 검토 묶음 — 사양과 인용 기록을 검토용 글 한 편으로 묶는다.

    python -m ozl.render bundle <사양.yaml> [--out <md>]

검토자(문장 대조·다른 모델 계열의 해석 점검)가 검사기와 **같은 글**을 보도록, 화면 글·말·각주는 spec 의
visible_text·spoken_text·chart_screen_text·footnote_text 로 뽑는다. 머리에는 사양 sha256 과 엄격 검사 결과를 적어
검토 판정이 어느 판에 대한 것인지 남긴다(진행 기록 progress 가 이 값을 쓴다).

묶음에는 기록의 observed(원문 표기)와 재대조 칸이 들어간다 — 절차서 §5 의 독립 재대조 에이전트에게는 주지 않는다.
기본 출력은 private/desk/builds/<card_id>/reviews/bundle_<타임코드>.md 이고, private/ 밖에는 쓰지 않는다(실수로 커밋되지 않게).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

from ozl.render import spec as S
from ozl.research import cards as C

KST = timezone(timedelta(hours=9))


def all_cited(sp: dict) -> list[str]:
    """사양이 인용한 기록 전부 — claim_ids·conversions(S.cited_ids)에 차트의 claims 와 원문 캡처 기록을 더한다."""
    seen: dict[str, None] = {c: None for c in S.cited_ids(sp)}
    for sl in sp.get("slides") or []:
        if not isinstance(sl, dict):
            continue
        for _, v in S.slot_views(sl):   # image_pair 는 두 자리 각각
            ch = v.get("chart")
            if isinstance(ch, dict):
                for c in ch.get("claims") or []:
                    seen.setdefault(str(c), None)
            if v.get("capture"):
                seen.setdefault(str(v["capture"]).strip(), None)
    return list(seen)


def _short(cid: str) -> str:
    return str(cid).rsplit("-", 1)[-1]


def _chart_line(ch: dict) -> str:
    pts = "; ".join(f"{s.get('name', '')}: " + ", ".join(f"{pt[0]}={S.point_notation(pt)}" for pt in (s.get("points") or [])
                                                          if isinstance(pt, (list, tuple)) and len(pt) >= 2)
                    for s in ch.get("series") or [] if isinstance(s, dict))   # 점은 [x, 값] 또는 [x, 값, 표시 문자열]
    return (f"[차트 {ch.get('kind', '')}] {ch.get('title', '')} · 단위 {ch.get('unit', '')} · 기간 {ch.get('period', '')} · {pts}"
            f" · 출처 {ch.get('source', '')} · 기록 {', '.join(_short(c) for c in ch.get('claims') or [])}")


def slide_block(i: int, sl: dict, claims: dict, card: dict | None, labels: dict) -> list[str]:
    L = [f"### {i}쪽 · {sl.get('stage', '')} · {sl.get('kind', '')}", f"제목: {sl.get('title', '')}"]
    vt = S.visible_text(sl)
    screen = vt[1:] if vt and vt[0] == S._s(sl.get("title")) else vt
    for j, v in S.slot_views(sl):
        where = f"({S.SLOT_NAME[j]}) " if j >= 0 else ""
        ch = v.get("chart")
        if isinstance(ch, dict):
            screen.append(where + _chart_line(ch))
        if v.get("capture"):
            focus = v.get("capture_focus")
            focus = focus if isinstance(focus, list) else ([focus] if focus else [])
            screen.append(f"{where}[원문 캡처] 기록 {_short(v['capture'])}" + (" · 형광: " + " | ".join(map(str, focus)) if focus else ""))
        if v.get("picture"):
            screen.append(f"{where}[그림 파일] {v['picture']}(검수 대장 pictures)")
    q = S.chart_screen_text(sl)
    if q:
        screen.append("차트에 찍히는 수량: " + " · ".join(q))
    L.append("화면: " + ("\n  ".join(screen) if screen else "—"))
    for k, name in (("spoken", "말"), ("transition", "넘김")):
        L.append(f"{name}: {sl.get(k, '') or '—'}")
    ids = sl.get("claim_ids") or []
    L.append("인용: " + (", ".join(_short(c) for c in ids) if ids else "없음"))
    if sl.get("refs"):
        L.append("refs: " + " / ".join(map(str, sl["refs"])))
    foot = S.footnote_text(sl, claims, card, labels)
    if foot:
        L.append(f"각주: {foot}")
    if sl.get("conversions"):
        L.append("환산: " + " / ".join(f"{cv.get('shown')} ← {cv.get('source')}({_short(cv.get('claim_id', ''))})" for cv in sl["conversions"]))
    if sl.get("notes"):
        L.append(f"작성자 메모: {sl['notes']}")
    return L + [""]


def claim_line(cid: str, c: dict, labels: dict) -> str:
    r = ((c.get("verification") or {}).get("recheck") or {}) if isinstance(c.get("verification"), dict) else {}
    rc = r.get("checks") or {}
    src = c.get("source") or {}
    bits = [f"- {_short(cid)} · {labels.get(cid) or src.get('publisher', '')} · {src.get('tier', '')}",
            f"observed: 「{c.get('observed', '')}」",
            f"등급 {C.grade_label(c)}",
            f"기준 {rc.get('as_of') or (c.get('checks') or {}).get('base_period', '')}"]
    for k, name in (("status", "상태"), ("unit", "단위"), ("population", "대상"), ("speaker", "말한 쪽")):
        if rc.get(k):
            bits.append(f"{name} {rc[k]}")
    if r.get("note"):
        bits.append(f"재대조 메모: {r['note']}")
    if r.get("row_col"):
        bits.append(f"행·열: {r['row_col']}")
    if src.get("url"):
        bits.append(f"주소: {src['url']}")
    return " · ".join(bits)


def render(sp: dict, claims: dict, card: dict | None, spec_sha: str, check_line: str, spec_name: str = "") -> str:
    labels = sp.get("source_labels") or {}
    slides = [sl for sl in sp.get("slides") or [] if isinstance(sl, dict)]
    cited = all_cited(sp)
    L = [f"# 검토 묶음 — {sp.get('card_id', '')}", "",
         f"- 사양: {spec_name} · sha256 {spec_sha[:16]}",
         f"- 엄격 검사: {check_line}",
         f"- 본편 {len(slides)}장 · 인용 기록 {len([c for c in cited if c in claims])}건",
         f"- 만든 때: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}",
         "- 이 묶음은 독립 재대조 에이전트에게 주지 않는다(원문 표기와 재대조 칸이 들어 있다).", "",
         "## 덱 본문(쪽마다: 단계 · 종류 · 제목 / 화면 글 / 말 / 넘김 / 인용 / 각주)", ""]
    for i, sl in enumerate(slides, 1):
        L += slide_block(i, sl, claims, card, labels)
    L += ["## 인용한 검증 기록(번호 · 출처 · 원문 표기 · 등급 · 기준 · 재대조 맥락)", ""]
    for cid in sorted((c for c in cited if c in claims), key=lambda c: int(_short(c)[1:]) if _short(c)[1:].isdigit() else 0):
        L.append(claim_line(cid, claims[cid], labels))
    missing = [c for c in cited if c not in claims]
    if missing:
        L += ["", "읽지 못한 기록: " + ", ".join(missing)]
    return "\n".join(L) + "\n"


def default_out(card_id: str, now: datetime | None = None) -> pathlib.Path:
    ts = (now or datetime.now(KST)).strftime("%Y%m%d_%H%M%S")
    return C.DESK / "builds" / str(card_id) / "reviews" / f"bundle_{ts}.md"


def _inside_private(p: pathlib.Path) -> bool:
    private = C.DESK.parent.resolve()
    real = p.resolve()
    return real == private or private in real.parents


def main(argv: list[str]) -> int:
    out = None
    pos: list[str] = []
    it = iter(argv)
    for a in it:
        if a == "--out":
            out = next(it, None)
            if out is None:
                raise SystemExit("--out 뒤에 경로가 있어야 한다")
        elif a.startswith("--"):
            raise SystemExit(f"모르는 옵션 {a}")
        else:
            pos.append(a)
    if len(pos) != 1:
        print(__doc__)
        return 2
    path = pathlib.Path(pos[0])
    if not path.is_file():
        print(f"[bundle] 사양 파일이 없다: {path}", file=sys.stderr)
        return 1
    raw = path.read_bytes()   # 한 번만 읽는다 — 내용과 sha256 이 같은 판을 가리키게(읽는 사이 파일이 바뀌어도)
    import yaml
    sp = yaml.safe_load(raw.decode("utf-8")) or {}
    if not isinstance(sp, dict) or not C.CARD_ID.match(str(sp.get("card_id", ""))):
        print("[bundle] 사양에 카드 ID 가 없다", file=sys.stderr)
        return 1
    cid = str(sp["card_id"])
    card = C.load_card(cid) if C.card_path(cid).exists() else None
    claims, staged = S.load_claims(all_cited(sp))
    from ozl.render import build as B   # pptx 를 쓰는 모듈 — 엄격 검사의 화면 검사에만 필요하다
    rep = S.check(sp, claims, S.load_template(), card, B.layout_problems, staged=staged, appendix_fn=B.appendix_problems)
    check_line = f"{'통과' if rep.ok else '실패'} · 실패 {len(rep.errors)} · 경고 {len(rep.warnings)}"
    sha = hashlib.sha256(raw).hexdigest()
    target = pathlib.Path(out) if out else default_out(cid)
    if not _inside_private(target):
        print(f"[bundle] private/ 밖에는 쓰지 않는다: {target}", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(sp, claims, card, sha, check_line, path.name), encoding="utf-8")
    print(json.dumps({"out": str(target), "spec_sha256": sha, "check": check_line}, ensure_ascii=False))
    return 0 if rep.ok else 1
