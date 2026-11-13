#!/usr/bin/env python3
"""공개 문서의 문체 검사 — 사람이 읽는 글에서 이모지, 꾸미는 말, 가운뎃점 나열, 느낌표 구호, 맺음 인사, 내부 표기를 잡는다.

쓰는 법
    python scripts/style_check.py                 정해 둔 공개 문서 전부(DEFAULT_GLOBS)
    python scripts/style_check.py README.md docs/how-it-works.md
    python scripts/style_check.py --strict-internal docs/issue-brief.md   내부 표기도 오류로 친다
    python scripts/style_check.py --text "올릴 글"  글 한 덩이를 검사한다(Notion 에 올리는 칸에 쓴다)

검사에서 빼는 것: 코드 블록(``` 사이), 한 줄 코드(`…`), 주소, HTML 주석.
규칙을 설명하느라 금지어를 예로 드는 줄은 줄 끝에 `<!-- style: 예시 -->` 를 붙여 뺀다(뺀 줄 수를 결과에 찍는다).
내부 표기(T1, verified, i20990101-01 같은 것)는 뜻을 풀어 적는 문서가 있어 기본으로는 알림만 하고, --strict-internal 일 때 오류로 친다.

낱말 목록의 정본은 `src/ozl/issues/style.py` 다(이슈 기록의 글과 같은 기준). 여기에는 문서에만 쓰는 목록(맺음 인사, 부풀리는 말)만 더한다.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from ozl.issues import style as S  # noqa: E402

DEFAULT_GLOBS = ("README.md", "docs/*.md", "apps/web/README.md", "apps/web/DESIGN.md")
# 글을 맺는 인사와 안내 말투. 한 일을 적는 문서에는 필요 없다.
TAIL = ("살펴보겠습니다", "알아보겠습니다", "정리해 보았습니다", "정리해 봤습니다", "도움이 되길", "도움이 되었기를", "도움이 되셨",
        "궁금한 점이 있으", "언제든지 문의", "감사합니다", "결론적으로", "요약하자면", "한마디로 말해")
# 뜻 없이 크기만 키우는 말.
INFLATED = ("시너지", "극대화", "패러다임", "게임 체인저", "게임체인저", "차세대", "올인원", "원스톱", "주목할 만한", "눈여겨볼")
SLOGAN = re.compile(r"[가-힣A-Za-z0-9)\]]\s*!+(?=\s|$|[\"'”’)])")
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"https?://\S+|\]\([^)]*\)")
COMMENT = re.compile(r"<!--.*?-->")
SKIP_MARK = re.compile(r"<!--\s*style:\s*예시\s*-->")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")


def clean(line: str) -> str:
    """검사할 글만 남긴다 — 한 줄 코드, 주소, 주석을 지운다."""
    return COMMENT.sub(" ", URL.sub(" ", INLINE_CODE.sub(" ", line)))


def line_errors(text: str, strict_internal: bool = False) -> tuple[list[str], list[str]]:
    """(오류, 알림). text 는 이미 clean 을 거친 한 줄."""
    err: list[str] = []
    info: list[str] = []
    if S.EMOJI.search(text):
        err.append("이모지를 쓰지 않는다")
    for w in S.DECORATIVE:
        if w in text:
            err.append(f"꾸미는 말 '{w}'을 쓰지 않는다")
    for w in INFLATED:
        if w in text:
            err.append(f"부풀리는 말 '{w}'을 쓰지 않는다")
    for w in TAIL:
        if w in text:
            err.append(f"맺음 인사나 안내 말투 '{w}'를 쓰지 않는다")
    if S.middot_run(text):
        err.append("가운뎃점으로 명사를 넷 이상 잇지 않는다 — 문장으로 풀어 쓴다")
    if SLOGAN.search(text):
        err.append("느낌표로 끝나는 구호를 쓰지 않는다")
    if S.AI_PHRASE.search(text):
        err.append("'AI 가 분석' 같은 문구를 쓰지 않는다")
    for rx in S.INTERNAL:
        m = rx.search(text)
        if m:
            (err if strict_internal else info).append(f"내부 표기 '{m.group(0)}'")
            break
    return err, info


def check_text(text: str, strict_internal: bool = False) -> tuple[list[tuple[int, str]], list[tuple[int, str]], int]:
    """(오류 [(줄 번호, 문구)], 알림, 예시 표시로 뺀 줄 수)."""
    errs: list[tuple[int, str]] = []
    infos: list[tuple[int, str]] = []
    skipped = 0
    fenced = False
    for no, raw in enumerate(text.splitlines(), 1):
        if FENCE.match(raw):
            fenced = not fenced
            continue
        if fenced or TABLE_RULE.match(raw):
            continue
        if SKIP_MARK.search(raw):
            skipped += 1
            continue
        e, i = line_errors(clean(raw), strict_internal)
        errs += [(no, m) for m in e]
        infos += [(no, m) for m in i]
    return errs, infos, skipped


def default_files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for g in DEFAULT_GLOBS:
        out += sorted(ROOT.glob(g))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="공개 문서의 문체 검사")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--strict-internal", action="store_true", help="내부 표기도 오류로 친다")
    ap.add_argument("--text", help="파일 대신 이 글을 검사한다")
    ap.add_argument("--quiet-info", action="store_true", help="알림을 찍지 않는다")
    a = ap.parse_args(argv)
    bad = 0
    if a.text is not None:
        targets: list[tuple[str, str]] = [("(글)", a.text)]
    else:
        files = [pathlib.Path(f) for f in a.files] or default_files()
        targets = [(str(p.relative_to(ROOT)) if p.is_absolute() and ROOT in p.parents else str(p),
                    p.read_text(encoding="utf-8", errors="ignore")) for p in files if p.is_file()]
    for name, text in targets:
        errs, infos, skipped = check_text(text, a.strict_internal)
        for no, m in errs:
            print(f"[문체] {name}:{no}: {m}")
        if not a.quiet_info:
            for no, m in infos:
                print(f"[알림] {name}:{no}: {m}")
        if skipped:
            print(f"[알림] {name}: 예시 표시로 뺀 줄 {skipped}개")
        bad += len(errs)
    print(f"문체 검사: 문서 {len(targets)}개, 오류 {bad}건")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
