"""이슈 기록의 칸 이름과 허용 값, issue.yaml·근거 yaml 읽기 쓰기, 빈 뼈대, 독자에게 보이는 글 칸 순회.

형식의 정본은 설계 문서 3절이다. 칸을 더하면 여기 ISSUE_FIELDS 와 승인 지문의 분류(digest)를 함께 고친다.
"""
from __future__ import annotations

import copy
import pathlib
import re

import yaml

from . import paths

# ── 허용 값 ───────────────────────────────────────────────────────────
CATEGORIES = ("국제·지정학", "금융·증시", "국내 경제·정책", "사회·문화", "역사·과학·기술", "기타")   # cards.CATEGORIES 와 같다(시험이 고정)
PUBLISH_STATES = ("게시 가능", "보류", "공개 제외")
TARGET_KINDS = ("기관과 정책", "공인의 공적 활동", "공인의 사생활", "일반인")
SENSITIVE = ("정치", "선거", "형사", "연예", "건강")
SYUKA_DECK = ("가능", "불가", "미정")
ANGLES = ("판정", "규모", "선후", "이해관계", "절차", "남은 질문", "비교")
FACT_TYPES = ("사실", "해석")
FACT_KINDS = ("발표와 조치", "사실")
FLOW_KINDS = ("계기", "대응", "반박", "결정", "시행", "예정")   # 시행 = 발표와 다른 날 시행된 조치(구현에서 더함)
STANCE_KINDS = ("발표", "인정", "부인", "평가", "전망")
FIGURE_KINDS = ("직접 그린 도표", "공식 문서 캡처", "검수 대장 그림")
CORRECTION_KINDS = ("정정", "판정 변경", "새 사건")
TOPIC_STATES = ("새로 뜸", "커지는 중", "정점", "식는 중", "다시 오름", "휴면", "종료")
WORK_STATES = ("작성 중", "검토 대기", "게시 대기", "보류")
REVIEW_KINDS = ("문장 대조", "해석 점검", "수정 확인")
REVIEW_FAMILIES = ("anthropic", "openai", "google")
REVIEW_RESULTS = ("통과", "지적", "반려")
STANCES = ("지지", "반대")
BASES = ("가", "나", "다", "없음")
PASSAGE_ROLES = ("작성자의 판단", "당사자 주장을 옮긴 것", "사실 기재")
NUMBER_KINDS = ("공식", "주장", "계산")
NA = "해당 없음"

# 최상위 칸(설계 3-1). numbers 는 구현에서 더했다 — 문자열 칸(제목, 지금까지 3줄 등)의 숫자 종류를 칸 경로별로 적는다.
ISSUE_FIELDS = ("issue_id", "slug", "aliases", "revision", "split_from", "merged_into", "category", "keywords", "example",
                "reason", "publish", "sensitive", "election", "syuka_deck", "event_check", "titles", "rev_line", "what_new",
                "why_matters", "so_far", "so_far_refs", "numbers", "facts", "claims", "flow", "stances", "open_questions",
                "spillover", "figures", "reviews", "corrections", "production", "topic_state", "trend", "work_state", "history",
                "identifiers", "article")
# article(2026-11-14 더함) = 읽는 층의 글. issue.yaml 에 쓰지 않고 같은 폴더의 article.yaml 에 두며, load_issue 가 붙여 읽고
# save_issue 가 떼어 낸다. 승인 고정 사본(revisions/rN/issue.yaml)에는 함께 든다. 없으면 지문에서 빠진다(digest.OPTIONAL_TOP).
# identifiers(구현에서 더함) = 이름 속 숫자 표기(KTX-1, 제2형)의 목록. 덱 사양의 identifiers 와 같은 뜻(numbers.identifier_error).
# 비어 있거나 없으면 지문에서 빠진다(digest.issue_view) — 이 칸이 생기기 전의 이슈의 내용 해시가 바뀌지 않게.
REQUIRED = ("issue_id", "slug", "revision", "category", "keywords", "example", "publish", "sensitive", "syuka_deck",
            "event_check", "titles", "production", "work_state")
POST_REQUIRED = ("reason", "what_new", "why_matters", "so_far", "facts")   # 게시 가능일 때(또는 --public) 필수
ITEM_LISTS = {"facts": "f", "claims": "c", "flow": "w", "stances": "s", "figures": "g", "open_questions": "q"}
LEDGER_KINDS = tuple(ITEM_LISTS.values())   # 발급 대장이 세는 항목 종류(작은 주장 p 는 주장마다, 검토 r 은 검토 명령이 센다)

LIMITS = {"titles.chosen": 60, "rev_line": 80, "what_new": 80, "why_matters": 80, "so_far": 80, "facts.text": 120,
          "claims.gist": 100, "parts.gist": 100, "report.title": 200, "similar_cases.text": 120, "verdict_history.why": 120}
REASON_LEN = (10, 120)


# ── 읽기 쓰기 ─────────────────────────────────────────────────────────
def load_yaml(p) -> dict:
    d = yaml.safe_load(pathlib.Path(p).read_text(encoding="utf-8"))
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise ValueError(f"yaml 맨 위가 사전이 아니다: {p}")
    return d


def dump_yaml(d: dict) -> str:
    return yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=1000)


def save_yaml(p, d: dict) -> None:
    paths.write_atomic(pathlib.Path(p), dump_yaml(d))


ARTICLE_KEY = "article"
ARTICLE_FILE = "article.yaml"


def load_issue(issue_id: str) -> dict:
    """작업본 issue.yaml. 같은 폴더에 article.yaml 이 있으면 issue['article'] 로 붙인다(글이 지문과 검사에 들게)."""
    d = load_yaml(paths.issue_file(issue_id))
    if ARTICLE_KEY in d:
        raise ValueError(f"issue.yaml 에 article 칸을 두지 않는다 — 글은 {ARTICLE_FILE} 에 쓴다: {issue_id}")
    p = paths.issue_dir(issue_id) / ARTICLE_FILE
    if p.is_file():
        d[ARTICLE_KEY] = load_yaml(p)
    return d


def save_issue(issue: dict) -> None:
    """작업본 issue.yaml 을 쓴다. 붙여 읽은 글(article)은 쓰지 않는다(글은 article.yaml 에만 있다)."""
    save_yaml(paths.issue_file(issue["issue_id"]), {k: v for k, v in issue.items() if k != ARTICLE_KEY})


def load_evidences(issue_id: str, folder=None) -> dict[str, dict]:
    """그 이슈의 근거 기록 전부 {근거 번호: 기록}. 파일 이름과 evidence_id 가 다르면 이름 쪽 번호로 두고 check 가 잡는다."""
    d = pathlib.Path(folder) if folder else paths.evidence_dir(issue_id)
    out: dict[str, dict] = {}
    if d.is_dir():
        for p in sorted(d.glob("*.yaml")):
            out[p.stem] = load_yaml(p)
    return out


def save_evidence(ev: dict) -> None:
    save_yaml(paths.evidence_file(ev["issue_id"], ev["evidence_id"]), ev)


def all_issue_ids() -> list[str]:
    d = paths.issues_dir()
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir() and re.match(r"^i\d{8}-\d{2}$", p.name) and (p / "issue.yaml").is_file())


# ── 빈 뼈대 ───────────────────────────────────────────────────────────
def skeleton(issue_id: str, slug: str, example: bool = False, title: str = "", now: str = "") -> dict:
    """`new` 명령이 쓰는 빈 뼈대. 게시 필수 칸은 비워 두고 게시 가부는 '보류'(작성 중)로 둔다."""
    return {
        "issue_id": issue_id, "slug": slug, "aliases": [], "revision": 1, "split_from": None, "merged_into": None,
        "category": "기타", "keywords": [slug.split("-")[0]], "example": bool(example), "reason": "",
        "publish": {"state": "보류", "why": "작성 중"}, "sensitive": [], "election": None, "syuka_deck": "미정",
        "event_check": {"confirmed": False, "evidence": None, "at": None},
        "titles": {"candidates": [], "chosen": title, "target_kind": "기관과 정책", "basis_claims": []},
        "rev_line": "", "what_new": "", "why_matters": "", "so_far": [], "so_far_refs": [], "numbers": {},
        "facts": [], "claims": [], "flow": [], "stances": [], "open_questions": [],
        "spillover": {"issues": [], "similar_cases": []}, "figures": [], "reviews": [], "corrections": [],
        "production": {"researched_by": [], "drafted_by": "", "chosen_by": "사람"},
        "topic_state": None, "trend": None, "work_state": "작성 중", "history": [{"at": now, "event": "만듦"}] if now else [],
    }


# ── 독자에게 보이는 글 칸 ─────────────────────────────────────────────
TOP_TEXT = ("rev_line", "what_new", "why_matters", "reason")
ITEM_TEXT = {"facts": ("text",), "flow": ("what",), "stances": ("who", "summary"), "open_questions": ("text",),
             "figures": ("caption", "alt"), "corrections": ("before", "after", "why")}
CLAIM_TEXT = ("gist", "scope", "searched", "not_found", "would_decide")   # scope 는 본문에 '확인한 범위'로 실린다


def _s(v) -> str:
    return v if isinstance(v, str) else ""


def reader_items(issue: dict) -> list[tuple[str, str, list, dict | None]]:
    """(칸 경로, 글, numbers 목록, 그 글이 든 항목 | None). 항목 안의 글은 항목의 numbers 를, 이슈의 문자열 칸은
    최상위 numbers[칸 경로] 를 쓴다. 고른 제목은 같은 글의 후보 칸 numbers 를 쓴다. 빈 글은 돌려주지 않는다."""
    top = issue.get("numbers") if isinstance(issue.get("numbers"), dict) else {}
    out: list[tuple[str, str, list, dict | None]] = []

    def add(path, text, nums, item):
        if _s(text).strip():
            out.append((path, text, nums if isinstance(nums, list) else [], item))

    t = issue.get("titles") if isinstance(issue.get("titles"), dict) else {}
    cands = [c for c in (t.get("candidates") or []) if isinstance(c, dict)]
    for i, c in enumerate(cands):
        add(f"titles.candidates.{i}", c.get("text"), top.get(f"titles.candidates.{i}"), None)
    same = next((i for i, c in enumerate(cands) if c.get("text") == t.get("chosen")), None)
    add("titles.chosen", t.get("chosen"), top.get("titles.chosen", top.get(f"titles.candidates.{same}") if same is not None else None), None)
    for k in TOP_TEXT:
        add(k, issue.get(k), top.get(k), None)
    for i, s in enumerate(issue.get("so_far") or []):
        add(f"so_far.{i}", s, top.get(f"so_far.{i}"), None)
    for c in issue.get("claims") or []:
        if not isinstance(c, dict):
            continue
        base = f"claims.{c.get('id')}"
        for k in CLAIM_TEXT:
            add(f"{base}.{k}", c.get(k), c.get("numbers"), c)
        add(f"{base}.spread.where", (c.get("spread") or {}).get("where") if isinstance(c.get("spread"), dict) else "", c.get("numbers"), c)
        pp = c.get("party_position")
        if isinstance(pp, dict):
            add(f"{base}.party_position.text", pp.get("text"), c.get("numbers"), c)
        for p in c.get("parts") or []:
            if isinstance(p, dict):
                for k in ("gist", "scope", "would_decide"):
                    add(f"{base}.parts.{p.get('id')}.{k}", p.get(k), c.get("numbers"), c)
        add(f"{base}.basis_label", c.get("basis_label"), c.get("numbers"), c)
        for j, h in enumerate(c.get("verdict_history") or []):
            if isinstance(h, dict):
                add(f"{base}.verdict_history.{j}.why", h.get("why"), c.get("numbers"), c)
    sp = issue.get("spillover") if isinstance(issue.get("spillover"), dict) else {}
    for i, c in enumerate(sp.get("similar_cases") or []):
        if isinstance(c, dict):
            add(f"spillover.similar_cases.{i}.text", c.get("text"), top.get(f"spillover.similar_cases.{i}.text"), None)
    for lst, fields in ITEM_TEXT.items():
        for i, it in enumerate(issue.get(lst) or []):
            if not isinstance(it, dict):
                continue
            key = it.get("id", i)
            for k in fields:
                nums = it.get("numbers") if "numbers" in it else top.get(f"{lst}.{key}.{k}")
                add(f"{lst}.{key}.{k}", it.get(k), nums, it)
    return out


def top_number_paths(issue: dict) -> set[str]:
    """최상위 numbers 지도에 둘 수 있는 칸 경로 — reader_items 가 최상위 지도에서 숫자를 읽는 글 칸(이슈의 문자열 칸, numbers 칸이
    없는 항목의 글 칸)만. 주장은 항목 안 numbers 만 쓰므로 들지 않는다. 빈 글 칸도 들지 않는다(검사받지 않는 숫자가 실리지 않게)."""
    out: set[str] = set()
    for path, _t, _n, item in reader_items(issue):
        if item is None:
            out.add(path)
        elif not path.startswith("claims.") and "numbers" not in item:
            out.add(path)
    t = issue.get("titles") if isinstance(issue.get("titles"), dict) else {}
    if "titles.chosen" in out:
        cands = [c for c in (t.get("candidates") or []) if isinstance(c, dict)]
        out |= {f"titles.candidates.{i}" for i, c in enumerate(cands) if _s(c.get("text")).strip()}
    return out


# 숫자 항목과 계산 입력에 둘 수 있는 칸(공개 본문에 실리므로 모르는 칸은 거부한다)
NUMBER_KEYS = ("value", "kind", "evidence", "inputs", "formula", "unit", "rounding", "refutes")
INPUT_KEYS = ("value", "kind", "evidence", "of")

# 추이(trend · score.json) — 지문 밖 칸이라 승인 뒤에도 바뀐다. 모양이 맞는 값만 싣는다.
TREND_KEYS = ("score", "bars7", "asof", "formula_version")
_ASOF = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?([+-]\d{2}:?\d{2})?)?$")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def trend_error(tr) -> str:
    """추이 칸의 모양 오류(None 은 맞다). {score: 0~100 정수, bars7: 0~100 수 7개, asof: 날짜·시각, formula_version: 1 이상 정수}."""
    if tr is None:
        return ""
    if not isinstance(tr, dict) or set(tr) - set(TREND_KEYS):
        return "trend 는 {score, bars7, asof, formula_version} 칸만 둔다"
    s, b = tr.get("score"), tr.get("bars7")
    if not (isinstance(s, int) and not isinstance(s, bool) and 0 <= s <= 100):
        return "trend 는 score 가 0~100 정수다"
    if not (isinstance(b, list) and len(b) == 7 and all(_num(x) and 0 <= x <= 100 for x in b)):
        return "trend 는 bars7 이 0~100 수 7개다"
    if tr.get("asof") is not None and not (isinstance(tr["asof"], str) and _ASOF.match(tr["asof"].strip())):
        return "trend 는 asof 가 날짜·시각(YYYY-MM-DD HH:MM)이다"
    fv = tr.get("formula_version")
    if fv is not None and not (isinstance(fv, int) and not isinstance(fv, bool) and fv >= 1):
        return "trend 는 formula_version 이 1 이상 정수다"
    return ""


def clean_trend(tr) -> dict | None:
    """공개 출력에 싣는 추이 — 모양이 맞으면 정해진 칸만 새로 만든 사전, 아니면(또는 점수가 없으면) None."""
    if not isinstance(tr, dict) or tr.get("score") is None or trend_error(tr):
        return None
    return {"score": tr["score"], "bars7": [x for x in tr["bars7"]], "asof": tr.get("asof"), "formula_version": tr.get("formula_version")}


def clean_topic_state(v):
    return v if v in TOPIC_STATES else None


def item_evidence_ids(item: dict | None) -> list[str]:
    """항목이 인용한 근거 번호. 사실·흐름은 목록, 입장·그림은 한 개, 주장은 근거 연결·작은 주장·당사자 입장의 근거."""
    if not isinstance(item, dict):
        return []
    out: list[str] = []
    ev = item.get("evidence")
    if isinstance(ev, str):
        out.append(ev)
    elif isinstance(ev, list):
        for x in ev:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict) and isinstance(x.get("id"), str):
                out.append(x["id"])
    for p in item.get("parts") or []:
        if isinstance(p, dict):
            out += [x["id"] for x in p.get("evidence") or [] if isinstance(x, dict) and isinstance(x.get("id"), str)]
    pp = item.get("party_position")
    if isinstance(pp, dict) and isinstance(pp.get("evidence"), str):
        out.append(pp["evidence"])
    return list(dict.fromkeys(out))


def cited_evidence_ids(issue: dict) -> list[str]:
    """이슈 전체가 인용한 근거 번호(사건 확인 근거, 항목들, 최상위 numbers 의 공식 값 근거)."""
    out: list[str] = []
    ec = issue.get("event_check")
    if isinstance(ec, dict) and isinstance(ec.get("evidence"), str):
        out.append(ec["evidence"])
    for lst in ("facts", "claims", "flow", "stances", "figures"):
        for it in issue.get(lst) or []:
            out += item_evidence_ids(it)
    top = issue.get("numbers") if isinstance(issue.get("numbers"), dict) else {}
    for nums in top.values():
        out += number_evidence_ids(nums)
    return list(dict.fromkeys(out))


def number_evidence_ids(nums) -> list[str]:
    """숫자 항목들이 기대는 근거 번호(공식 값의 evidence 와 계산 입력의 evidence)."""
    out: list[str] = []
    for n in nums if isinstance(nums, list) else []:
        if not isinstance(n, dict):
            continue
        if isinstance(n.get("evidence"), str):
            out.append(n["evidence"])
        for x in (n.get("inputs") or {}).values() if isinstance(n.get("inputs"), dict) else []:
            if isinstance(x, dict) and isinstance(x.get("evidence"), str):
                out.append(x["evidence"])
    return out


def clone(d):
    return copy.deepcopy(d)
