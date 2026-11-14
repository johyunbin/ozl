"""python -m ozl.render check <사양.yaml> [--draft] [--claims-dir <경로>]…
python -m ozl.render build <사양.yaml> [--draft] [--claims-dir <경로>]… [--no-export]
python -m ozl.render bundle <사양.yaml> [--out <md>]          # 검토 묶음(ozl.render.bundle)
python -m ozl.render progress <card_id> [--start|--resume|--mark 단계|--done --final 폴더|--abandon]   # 진행 기록(ozl.render.progress)

--draft        아직 '확인'(사람 대조)도 「원문 일치」(프로그램 대조 + 독립 재대조)도 아닌 기록·대기 폴더 기록도 인용 허용.
               해당 쪽에 [검증 대기] 딱지, 산출물 이름에 _draft. 완성본은 엄격 모드(--draft 없이)로만 만든다.
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
    if argv and argv[0] in ("bundle", "progress"):   # 하위 명령은 각 모듈이 인자를 읽는다(_opts 는 사양 파일 명령 전용)
        from importlib import import_module
        return import_module(f"ozl.render.{argv[0]}").main(argv[1:])
    if any(a in ("-h", "--help") for a in argv):   # 사양 파일을 읽기 전에 끝낸다
        print(__doc__)
        return 0
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
        if not draft:   # build 와 같게 — 엄격 모드는 밈을 빼고 검사하고, 뺀 것을 알린다
            from ozl.render import pictures as PIC
            sp, dropped = PIC.drop_memes(sp)
            for d in dropped:
                print("[밈 제외]", d)
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
        if k != "dropped":
            print(f"{k}: {v}")
    for d in info.get("dropped") or []:
        print("[밈 제외]", d)
    cid = str(sp.get("card_id", ""))
    if C.CARD_ID.match(cid):
        from ozl.render import progress as P   # 막지 않고 알리기만 한다(빌드는 한 편에 여러 번 부른다)
        st = P.load(cid)
        if st.get("status") == P.DONE and not draft:
            print(f"[진행 기록] 이 카드는 이미 완성본이 있다: {st.get('final', '')} — 다시 만드는 중이면 progress --start --force")
    if draft:
        print(f"[검증 대기] 기록을 인용한 슬라이드: {info.get('pending_slides', 0)}장")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
