"""python -m ozl.issues … — 이슈 기록 명령(설계 12절). 자료 루트는 OZL_DESK_ROOT(없으면 private/desk).

    check [번호 …] [--all] [--public] [--articles 파일] [--json]   0 통과, 1 오류, 2 사용 오류
    new --date YYYY-MM-DD --slug s [--example] [--title …]           번호를 받아 빈 뼈대를 쓴다
    ids --date D --n N | --evidence 이슈 --n N | --item 이슈 --kind c --n N
    hash 번호 | day:날짜 | restored:날짜                               지금 내용 해시와 판 번호
    capture 번호 근거번호 / machine-verify 번호 근거번호               원문 받기(네트워크) / 기계 대조
    review add 번호 --kind --by-model --family --result --notes-path 검토원문 [--findings 파일] [--before-hash H --addresses r1,r2]
                [--content-hash H]                                    검토가 본 내용(snapshot 으로 남긴 사본)에 묶는다
    snapshot 번호                                                     지금 내용의 사본을 남기고 해시를 찍는다(검토 묶음을 보낼 때)
    approve 대상 --rev N --hash H --by 이름 [--request-id R]          0 승인, 1 미충족, 2 사용 오류·시험 규칙, 3 충돌
    export --preview|--public --out 폴더 [--now 시각]                 0, 1 출력 검사 실패, 2 연락처·출력 자리, 4 일부 판 빠짐
    withdraw 대상 [--rev N] --by 이름 --reason 까닭
    status [번호 …] [--json]
    links [--json] [--write-map]                                      0 누락 0건, 1 누락 있음
    article-check 번호 [--json]                                       글(article.yaml) 검사. 0 오류 없음, 1 오류, 2 사용 오류·글 없음
    article-new slug --category 분야 --title 제목 [--date YYYY-MM-DD]   번호를 받아 폴더, 최소 issue.yaml, 빈 글 뼈대를 쓴다
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

from ozl.research import cards

from . import article as ART
from . import digest, export, ids, links, model, numbers, paths, revisions, units
from . import evidence as EV


def _err(msg: str, code: int = 2) -> int:
    print(msg, file=sys.stderr)
    return code


def _check(a) -> int:
    if a.all and a.ids:
        return _err("번호와 --all 을 같이 주지 않는다")
    targets = model.all_issue_ids() if a.all else a.ids
    if not targets:
        return _err("검사할 이슈 번호를 주거나 --all 을 쓴다")
    bad = [t for t in targets if not ids.issue_id_ok(t)]
    if bad:
        return _err(f"이슈 번호 꼴이 아니다: {', '.join(bad)}")
    articles: list[str] = []
    if a.articles:
        p = pathlib.Path(a.articles)
        if not p.is_file():
            return _err(f"기사 본문 파일이 없다: {p}")
        articles = [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    res = revisions.check_ids(targets, public=a.public, articles=articles)
    n_err = sum(len(r["errors"]) for r in res.values())
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for iid, r in res.items():
            for line in r["errors"] + r["warnings"]:
                print(line)
            note = _exempt_note(iid)
            if note:
                print(f"알림 {iid}: {note}")             # 알림은 오류·경고 건수에 넣지 않는다
            print(f"{iid}: 오류 {len(r['errors'])}건, 경고 {len(r['warnings'])}건")
    return 1 if n_err else 0


def _exempt_note(iid: str) -> str:
    """식별자로 면제한 표기 알림('수량으로 보지 않은 표기: KTX-1(3곳)'). 읽지 못하면 빈 글."""
    try:
        return numbers.exempt_note(model.load_issue(iid))
    except (OSError, ValueError):
        return ""


def _taken_slugs() -> set:
    taken: set = set()
    for i in model.all_issue_ids():
        x = model.load_issue(i)
        taken |= {x.get("slug")} | {s for s in (x.get("aliases") or []) if isinstance(x.get("aliases"), list)}
    return taken | {e.get("slug") for e in revisions.load_manifest()["entries"] if e.get("unit") == "issue"}


def _new(a) -> int:
    if ids.slug_error(a.slug):
        return _err(ids.slug_error(a.slug))
    with paths.lock():                              # 쓰는 이름 확인부터 번호 받기·뼈대 저장까지 한 잠금 안에서(같은 이름 두 건 방지)
        if a.slug in _taken_slugs():
            return _err(f"이미 쓰는 주소 이름이다: {a.slug}")
        try:
            iid = ids.next_issue_ids_locked(a.date)[0]
        except ValueError as e:
            return _err(str(e))
        model.save_issue(model.skeleton(iid, a.slug, example=a.example, title=a.title or "", now=cards.now_kst()))
    print(iid)
    return 0


def _article_new(a) -> int:
    """글만 있는 이슈 — 발급 대장에서 번호를 받아 폴더, 최소 issue.yaml(new 와 같은 뼈대), 빈 article.yaml 을 쓴다."""
    if ids.slug_error(a.slug):
        return _err(ids.slug_error(a.slug))
    if not a.category.strip() or not a.title.strip():
        return _err("--category 와 --title 을 적는다")
    now = cards.now_kst()
    date = a.date or now[:10]
    with paths.lock():
        if a.slug in _taken_slugs():
            return _err(f"이미 쓰는 주소 이름이다: {a.slug}")
        try:
            iid = ids.next_issue_ids_locked(date)[0]
        except ValueError as e:
            return _err(str(e))
        if ART.article_file(iid).exists():
            return _err(f"글이 이미 있다: {ART.article_file(iid)}")
        model.save_issue(model.skeleton(iid, a.slug, title=a.title.strip()[:model.LIMITS["titles.chosen"]], now=now))
        model.save_yaml(ART.article_file(iid), ART.skeleton(iid, a.slug, a.category.strip(), a.title.strip(), now))
    print(iid)
    return 0


def _article_check(a) -> int:
    if not ids.issue_id_ok(a.issue):
        return _err(f"이슈 번호 꼴이 아니다: {a.issue}")
    if not paths.issue_dir(a.issue).is_dir():
        return _err(f"이슈 폴더가 없다: {a.issue}")
    try:
        r = ART.check_issue_article(a.issue)
    except (OSError, ValueError) as e:
        return _err(f"{a.issue} article.yaml: 읽지 못했다 — {e}")
    if r["missing"]:
        return _err(f"글이 없다: {ART.article_file(a.issue)}")
    if a.json:
        print(json.dumps({k: r[k] for k in ("errors", "warnings")}, ensure_ascii=False, indent=1))
    else:
        for line in r["errors"] + r["warnings"]:
            print(line)
        print(f"오류 {len(r['errors'])}, 경고 {len(r['warnings'])}")
    return 1 if r["errors"] else 0


def _ids(a) -> int:
    try:
        if a.date:
            out = ids.next_issue_ids(a.date, a.n)
        elif a.evidence:
            out = ids.next_evidence_ids(a.evidence, a.n)
        elif a.item and a.kind:
            out = ids.next_item_ids(a.item, a.kind, a.n)
        else:
            return _err("--date, --evidence, --item --kind 가운데 하나를 준다")
    except ValueError as e:
        return _err(str(e))
    print("\n".join(out))
    return 0


def _target(t: str) -> tuple[str, str]:
    if ":" in t:
        unit, uid = t.split(":", 1)
        if unit not in units.UNITS:
            raise ValueError(f"대상 꼴이 틀렸다: {t}")
        return unit, uid
    if not ids.issue_id_ok(t):
        raise ValueError(f"이슈 번호 꼴이 아니다: {t}")
    return "issue", t


def _hash(a) -> int:
    try:
        unit, uid = _target(a.target)
        if unit == "issue":
            issue = model.load_issue(uid)
            h, rev = digest.content_hash(issue, model.load_evidences(uid)), issue.get("revision")
        else:
            d = units.load_unit(unit, uid)
            h, rev = units.unit_hash(unit, d), d.get("revision")
    except (ValueError, OSError) as e:
        return _err(str(e))
    print(f"{a.target} {rev}판 내용 해시 {h}")
    return 0


def _capture(a) -> int:
    r = EV.capture_evidence(a.issue, a.evidence)
    print(f"{a.evidence}: {'받음' if r['ok'] else '못 받음 — ' + r['reason']}")
    return 0 if r["ok"] else 1


def _machine(a) -> int:
    r = EV.machine_verify_evidence(a.issue, a.evidence)
    print(f"{a.evidence}: 기계 대조 통과" if r["ok"] else "\n".join(r["reasons"]))
    return 0 if r["ok"] else 1


def _review(a) -> int:
    findings = []
    if a.findings:
        p = pathlib.Path(a.findings)
        if not p.is_file():
            return _err(f"지적 파일이 없다: {p}")
        findings = yaml.safe_load(p.read_text(encoding="utf-8")) or []
        if not isinstance(findings, list):
            return _err("지적 파일은 [{field, note}] 목록이다")
    if not paths_ok(a.issue):
        return _err(f"작업본이 없다: {a.issue}")
    try:
        row = revisions.add_review(a.issue, a.kind, a.by_model, a.family, a.result, findings, a.before_hash,
                                   [x for x in (a.addresses or "").split(",") if x], a.notes_path or "",
                                   content_hash=a.content_hash or None)
    except ValueError as e:
        return _err(str(e), 1)
    print(f"{a.issue} {row['id']} {row['kind']} {row['result']} (내용 해시 {row['content_hash']})")
    return 0


def _snapshot(a) -> int:
    if not paths_ok(a.issue):
        return _err(f"작업본이 없다: {a.issue}")
    h = revisions.save_snapshot(a.issue)
    print(f"{a.issue} 내용 해시 {h} (사본 snapshots/{h}.yaml)")
    return 0


def paths_ok(iid: str) -> bool:
    return ids.issue_id_ok(iid) and iid in model.all_issue_ids()


def _approve(a) -> int:
    try:
        unit, uid = _target(a.target)
    except ValueError as e:
        return _err(str(e))
    if unit == "issue":
        r = revisions.approve(uid, a.rev, a.hash, a.by, request_id=a.request_id)
    else:
        r = units.approve_unit(unit, uid, a.rev, a.hash, a.by, request_id=a.request_id)
    print(r["msg"], file=sys.stdout if r["code"] == 0 else sys.stderr)
    return r["code"]


def _export(a) -> int:
    r = export.export("public" if a.public else "preview", a.out, now=a.now)
    for m in r["msgs"]:
        print(m, file=sys.stderr)
    if r["code"] in (0, 4):
        c = r["counts"]
        print(f"{'공개용' if a.public else '미리보기용'} 내보내기: 이슈 {c.get('issues', 0)}건, 판 {c.get('revisions', 0)}개, "
              f"화제 목록 {c.get('days', 0)}일, 복원판 {c.get('restored', 0)}일 → {a.out}")
    return r["code"]


def _withdraw(a) -> int:
    r = revisions.withdraw(a.target, a.rev, a.by, a.reason)
    print(r["msg"], file=sys.stdout if r["code"] == 0 else sys.stderr)
    return r["code"]


def _status(a) -> int:
    rows = revisions.status_rows(a.ids or None)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print("이슈 기록이 없다")
    for r in rows:
        lp = f"공개 {r['latest_public']}판" if r["latest_public"] else "공개 판 없음"
        print(f"{r['id']} {r['rev']}판 · {r['work_state']} · {r['approval']} · {lp} · {r['review']} · "
              f"숨긴 주장 {r['hidden_claims']}건 · 내용 해시 {r['content_hash']}")
        try:
            issue = model.load_issue(r["id"])
            miss = revisions.missing_reviews(issue, model.load_evidences(r["id"]))
        except (OSError, ValueError):
            issue, miss = {}, []
        if miss:
            print(f"  검토 완료까지 빠진 것: {'; '.join(miss)}")
        note = numbers.exempt_note(issue) if issue else ""
        if note:
            print(f"  {note}")
    return 0


def _links(a) -> int:
    r = links.check()
    if a.write_map and not r["skipped"]:
        links.write_map()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif r["skipped"]:
        print("옛 자료가 이 기기에 없어 건너뜀")
    else:
        c = r["counts"]
        print(f"옛 카드 {c['cards']}장, 카드가 읽는 기록 {c['claims_read']}건(파일 {c['claims_files']}, 대기로 옮김 {c['parked']}), "
              f"지운 기록 {c['removed']}건, 공개 기록 {c['public_claims']}건, 발행 카드 {c['published_cards']}장")
        print(f"덱 없는 카드 {r['deck_na']}장(해당 없음), 사본 없는 기기로 센 기록 {r['no_capture_device']}건")
        for m in r["missing"] + r["errors"]:
            print(m)
        print(f"빠진 연결 {len(r['missing'])}건, 오류 {len(r['errors'])}건")
    return 1 if r["missing"] or r["errors"] else 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m ozl.issues", description="이슈 기록 명령")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="이슈 기록 검사")
    c.add_argument("ids", nargs="*")
    c.add_argument("--all", action="store_true")
    c.add_argument("--public", action="store_true", help="게시 필수 칸까지 본다")
    c.add_argument("--articles", help="만들 때 읽은 기사 본문 파일(한 줄에 한 건, 저장하지 않는다)")
    c.add_argument("--json", action="store_true")
    c = sub.add_parser("new", help="번호를 받아 빈 뼈대를 쓴다")
    c.add_argument("--date", required=True)
    c.add_argument("--slug", required=True)
    c.add_argument("--example", action="store_true")
    c.add_argument("--title")
    c = sub.add_parser("ids", help="번호만 받는다")
    c.add_argument("--date")
    c.add_argument("--evidence")
    c.add_argument("--item")
    c.add_argument("--kind")
    c.add_argument("--n", type=int, default=1)
    c = sub.add_parser("hash", help="지금 내용 해시와 판 번호")
    c.add_argument("target")
    for name in ("capture", "machine-verify"):
        c = sub.add_parser(name)
        c.add_argument("issue")
        c.add_argument("evidence")
    c = sub.add_parser("review", help="검토 한 줄 더하기")
    c.add_argument("action", choices=["add"])
    c.add_argument("issue")
    c.add_argument("--kind", required=True)
    c.add_argument("--by-model", required=True)
    c.add_argument("--family", required=True)
    c.add_argument("--result", required=True)
    c.add_argument("--findings")
    c.add_argument("--before-hash")
    c.add_argument("--addresses")
    c.add_argument("--notes-path")
    c.add_argument("--content-hash", help="검토가 본 내용의 해시(snapshot 으로 남긴 사본이 있어야 한다)")
    c = sub.add_parser("snapshot", help="지금 내용의 사본을 남기고 해시를 찍는다")
    c.add_argument("issue")
    c = sub.add_parser("approve", help="승인 요청")
    c.add_argument("target")
    c.add_argument("--rev", type=int, required=True)
    c.add_argument("--hash", required=True)
    c.add_argument("--by", required=True)
    c.add_argument("--request-id")
    c = sub.add_parser("export", help="미리보기용·공개용 내보내기")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--preview", action="store_true")
    g.add_argument("--public", action="store_true")
    c.add_argument("--out", required=True)
    c.add_argument("--now")
    c = sub.add_parser("withdraw", help="내림")
    c.add_argument("target")
    c.add_argument("--rev", type=int)
    c.add_argument("--by", required=True)
    c.add_argument("--reason", required=True)
    c = sub.add_parser("status")
    c.add_argument("ids", nargs="*")
    c.add_argument("--json", action="store_true")
    c = sub.add_parser("links")
    c.add_argument("--json", action="store_true")
    c.add_argument("--write-map", action="store_true")
    c = sub.add_parser("article-check", help="글(article.yaml) 검사")
    c.add_argument("issue")
    c.add_argument("--json", action="store_true")
    c = sub.add_parser("article-new", help="번호를 받아 글만 있는 이슈의 뼈대를 쓴다")
    c.add_argument("slug")
    c.add_argument("--category", required=True)
    c.add_argument("--title", required=True)
    c.add_argument("--date", help="번호의 날짜(없으면 오늘, KST)")
    return ap


HANDLERS = {"check": _check, "new": _new, "ids": _ids, "hash": _hash, "capture": _capture, "machine-verify": _machine,
            "review": _review, "snapshot": _snapshot, "approve": _approve, "export": _export, "withdraw": _withdraw, "status": _status, "links": _links,
            "article-check": _article_check, "article-new": _article_new}


def main(argv=None) -> int:
    try:
        a = _parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        return HANDLERS[a.cmd](a)
    except (ValueError, OSError) as e:
        return _err(f"{a.cmd}: {e}", 2)


if __name__ == "__main__":
    sys.exit(main())
