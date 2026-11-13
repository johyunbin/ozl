"""옛 자료 건수 집계와 연결 검사 — 카드 → 기록 → 원문 사본 → 덱 → 공개 주소(설계 14절).

실제 private/desk 와 공개 저장소의 claims/, daily/ 를 읽기만 한다(자료 루트 OZL_DESK_ROOT 와 무관하게 옛 카드 자리를 본다).
대응표(legacy_map.json)는 write_map() 으로만 쓰고, 실제 자료 루트에서만 쓴다.
"""
from __future__ import annotations

import json
import re

from ozl.research import cards

from . import paths

URL_SLOT = re.compile(r"/daily/(\d{4})-(\d{2})-(\d{2})_(am|pm|wk)/#([a-z]{2}-\d{2})")


def available() -> bool:
    return cards.CARDS.is_dir() and cards.CLAIMS.is_dir()


def _ids_in(obj, key_re=re.compile(r"^(claim_ids|claims)$")) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if key_re.match(str(k)) and isinstance(v, list):
                out |= {x for x in v if isinstance(x, str) and cards.CLAIM_ID.match(x)}
            out |= _ids_in(v, key_re)
    elif isinstance(obj, list):
        for v in obj:
            out |= _ids_in(v, key_re)
    return out


def counts() -> dict:
    allc = cards.all_cards()
    claim_files = sorted(cards.CLAIMS.rglob("*.yaml"))
    parked = sorted(p.stem for p in claim_files if p.parent.name == "_unused")
    removed_dir = cards.DESK / "claims_removed"
    removed = sorted(p.stem for p in removed_dir.rglob("*.yaml")) if removed_dir.is_dir() else []
    read = sum(len(cards.claims_for(c["card_id"])) for c in allc)
    pub_claims = sorted(cards.PUB_CLAIMS.rglob("*.yaml")) if cards.PUB_CLAIMS.is_dir() else []
    published = [c["card_id"] for c in allc if cards.publishable(c, cards.claims_for(c["card_id"]))]
    return {"cards": len(allc), "claims_read": read, "claims_files": len(claim_files), "parked": len(parked),
            "removed": len(removed), "public_claims": len(pub_claims), "published_cards": len(published),
            "_parked": parked, "_removed": removed, "_published": published}


def check() -> dict:
    """{skipped, counts, missing: [문구], no_capture_device, deck_na, errors: [문구]}. missing 이 0건이면 연결이 다 있다."""
    if not available():
        return {"skipped": True, "counts": {}, "missing": [], "no_capture_device": 0, "deck_na": 0, "errors": []}
    cnt = counts()
    missing, errors = [], []
    no_dev = deck_na = 0
    caps_dir = cards.DESK / "captures"
    index_p = cards.ROOT / "daily" / "index.json"
    index = json.loads(index_p.read_text(encoding="utf-8")) if index_p.is_file() else {"cards": []}
    in_index = {c.get("card_id"): c for c in index.get("cards") or [] if isinstance(c, dict)}
    finals = cards.ROOT / "private" / "decks" / "final"
    for card in cards.all_cards():
        cid = card["card_id"]
        claims = cards.claims_for(cid)
        have = {c.get("claim_id") for c in claims}
        for d in card.get("data") or []:
            if isinstance(d, dict) and d.get("claim_id") not in have:
                missing.append(f"{cid}: 카드가 가리키는 기록이 없다({d.get('claim_id')})")
        for c in claims:
            if not isinstance(c.get("verification"), dict):
                continue
            cs = cards.copy_source(c)
            if cs["ok"]:
                continue
            if not caps_dir.is_dir():
                no_dev += 1
            else:
                missing.append(f"{c.get('claim_id')}: 원문 사본 — {cs['reason']}")
        published = cid in cnt["_published"]
        if published:
            for c in claims:
                pub = cards.claim_path(c["claim_id"], public=True)
                if not pub.is_file():
                    missing.append(f"{c['claim_id']}: 공개 기록이 없다")
                elif pub.read_bytes() != cards.claim_path(c["claim_id"]).read_bytes():
                    missing.append(f"{c['claim_id']}: 공개 기록이 정본과 다르다")
            row = in_index.get(cid)
            m = URL_SLOT.search(str((row or {}).get("url") or ""))
            if not m:
                missing.append(f"{cid}: 발행 카드 색인(daily/index.json)에 주소가 없다")
            else:
                y, mo, dd, slot, anchor = m.groups()
                md = cards.ROOT / "daily" / y / mo / f"{y}-{mo}-{dd}_{slot}.md"
                if not md.is_file() or f'id="{anchor}"' not in md.read_text(encoding="utf-8"):
                    missing.append(f"{cid}: 공개 주소의 회차 파일에 카드 자리표({anchor})가 없다")
        elif cid in in_index:
            errors.append(f"{cid}: 발행하지 않은 카드가 색인에 있다 — 색인에 있으면 안 된다")
        decks = sorted(finals.glob(f"{cid}_*")) if finals.is_dir() else []
        if not decks:
            deck_na += 1
        for dk in decks:
            for spec in sorted(dk.glob("spec_*.yaml")):
                for x in sorted(_ids_in(cards.load_yaml(spec)) - have):
                    missing.append(f"{cid}: 덱 사양({spec.name})이 없는 기록을 인용한다({x})")
    return {"skipped": False, "counts": {k: v for k, v in cnt.items() if not k.startswith("_")}, "missing": missing,
            "no_capture_device": no_dev, "deck_na": deck_na, "errors": errors}


def write_map(now=None) -> dict:
    """legacy_map.json — 실제 자료 루트에서만. 옛 카드는 이슈로 옮기지 않는다(issue_id: null)."""
    if not paths.is_real_root():
        raise ValueError("대응표는 실제 자료 루트에서만 쓴다")
    cnt = counts()
    index_p = cards.ROOT / "daily" / "index.json"
    index = json.loads(index_p.read_text(encoding="utf-8")) if index_p.is_file() else {"cards": []}
    urls = {c.get("card_id"): c.get("url") for c in index.get("cards") or [] if isinstance(c, dict)}
    finals = cards.ROOT / "private" / "decks" / "final"
    rows = []
    for card in cards.all_cards():
        cid = card["card_id"]
        decks = sorted(finals.glob(f"{cid}_*")) if finals.is_dir() else []
        rows.append({"card_id": cid, "issue_id": None,
                     "claims": [{"claim_id": c["claim_id"], "evidence_id": None} for c in cards.claims_for(cid)],
                     "deck": paths.rel_or_abs(decks[-1]) if decks else None, "public_url": urls.get(cid),
                     "published": cid in cnt["_published"]})
    d = {"schema": 1, "made_at": now or cards.now_kst(), "counts": {k: v for k, v in cnt.items() if not k.startswith("_")},
         "parked": cnt["_parked"], "removed": cnt["_removed"], "cards": rows}
    paths.write_atomic(paths.issues_dir() / "legacy_map.json", json.dumps(d, ensure_ascii=False, indent=1) + "\n")
    return d
