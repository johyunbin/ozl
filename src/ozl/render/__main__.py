"""python -m ozl.render check <사양.yaml> [--draft] [--claims-dir <경로>]…
python -m ozl.render build <사양.yaml> [--draft] [--claims-dir <경로>]… [--no-export]

--draft        사람 대조 전(human_verified 거짓)·대기 폴더 기록도 인용 허용. 해당 쪽에 [검증 대기] 딱지, 산출물 이름에 _draft.
--claims-dir   카드 기록 폴더(private/desk/claims) 말고 기록을 더 찾을 폴더(예: private/desk/staging/<card_id>/). 초안 모드에서만 쓸 수 있다.
"""
from __future__ import annotations

import pathlib
import sys

from ozl.render import build as B
from ozl.render import spec as S
from ozl.research import cards as C


def _opts(argv: list[str]) -> tuple[list[str], bool, bool, list[str]]:
    pos, draft, export, dirs = [], False, True, []
    it = iter(argv)
    for a in it:
        if a == "--draft":
            draft = True
        elif a == "--no-export":
            export = False
        elif a == "--claims-dir":
            d = next(it, None)
            if d is None:
                raise SystemExit("--claims-dir 뒤에 경로가 있어야 한다")
            if not pathlib.Path(d).is_dir():
                raise SystemExit(f"--claims-dir {d} 는 폴더가 아니다")
            dirs.append(d)
        elif a.startswith("--"):
            raise SystemExit(f"모르는 옵션 {a}")
        else:
            pos.append(a)
    return pos, draft, export, dirs


def main(argv: list[str]) -> int:
    pos, draft, export, dirs = _opts(argv)
    if len(pos) < 2 or pos[0] not in ("check", "build"):
        print(__doc__)
        return 2
    path = pathlib.Path(pos[1])
    if not path.is_file():
        print(f"[{pos[0]}] 사양 파일이 없다: {path}", file=sys.stderr)
        return 1
    try:
        sp = S.load_spec(path)
    except Exception as e:  # noqa: BLE001 — YAML 문법 오류 등은 한 줄로
        print(f"[{pos[0]}] 사양을 읽지 못했다({type(e).__name__}): {str(e).splitlines()[0] if str(e) else ''}", file=sys.stderr)
        return 1
    if not isinstance(sp, dict):
        print(f"[{pos[0]}] 사양 최상위가 사전(mapping)이 아니다: {path}", file=sys.stderr)
        return 1
    if pos[0] == "check":
        cid = sp.get("card_id")
        card = None
        if cid and C.CARD_ID.match(str(cid)):
            if not C.card_path(str(cid)).exists():
                print(f"[check] 카드 {cid} 를 찾지 못했다")
                return 1
            card = C.load_card(str(cid))
        claims, staged = S.load_claims(S.cited_ids(sp), dirs)
        rep = S.check(sp, claims, S.load_template(), card, B.layout_problems, draft=draft, staged=staged, appendix_fn=B.appendix_problems)
        for w in rep.warnings:
            print("[경고]", w)
        for e in rep.errors:
            print("[실패]", e)
        print("[면제한 식별자]", ", ".join(rep.exempt_idents) if rep.exempt_idents else "없음")
        n = len(sp.get("slides") or [])
        extra = f" · [검증 대기] {len(rep.pending)}장({', '.join(map(str, rep.pending))})" if draft else ""
        print(f"[check] {'통과' if rep.ok else '실패'}{' (초안 모드)' if draft else ''} · 본편 {n}장 · 실패 {len(rep.errors)} · 경고 {len(rep.warnings)}{extra}")
        return 0 if rep.ok else 1
    try:
        info = B.build(path, export=export, draft=draft, claims_dirs=dirs)
    except SystemExit as e:
        print(f"[build] {e}", file=sys.stderr)
        return 1
    for k, v in info.items():
        print(f"{k}: {v}")
    if draft:
        print(f"[검증 대기] 기록을 인용한 슬라이드: {info.get('pending_slides', 0)}장")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
