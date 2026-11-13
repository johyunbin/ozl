"""문체 검사 — 이모지, 내부 표기, 제목 금지어, 꾸미는 말, 낚시 제목, 가운뎃점 나열, AI 문구, 범죄 의혹 낱말, 연속 20자(경고).

적용 칸은 model.reader_items 가 돌려주는 독자에게 보이는 글 칸이다(AI 고지는 고정 문장이라 빠진다).
연속 20자의 정규화는 scripts/publish_gate.py 의 norm() 과 같은 정규식이다(시험이 두 결과가 같은지 고정한다).
"""
from __future__ import annotations

import re

from . import model

TITLE_BANNED = ("충격", "경악", "발칵", "난리", "대박", "소름", "역대급", "총정리", "완벽 정리", "한눈에", "전격", "초토화", "일파만파",
                "긴급", "속보", "단독", "알고 보니", "이럴 수가", "근황", "무슨 일", "논란 확산", "결국")
DECORATIVE = ("놀라운", "엄청난", "압도적", "혁신적", "획기적", "완벽한", "최고의", "독보적", "충격적", "놀랍게도", "무려", "드디어", "마침내")
CRIME_WORDS = ("횡령", "배임", "사기", "뇌물", "탈세", "성범죄", "성추행", "성폭행", "마약", "폭행", "갑질", "비리", "비위", "불법", "혐의",
               "의혹", "수사", "압수수색", "기소", "구속", "고발", "고소", "은폐", "숨겼", "숨긴", "조작", "부정행위", "부정 행위", "표절",
               "위증", "유용", "착복", "음주운전", "음주 운전", "도박", "학대", "스토킹", "범죄", "범행", "위법", "부당이득", "담합")
POLL_WORDS = ("여론조사", "지지율", "앞선", "앞서", "우세", "열세", "격차", "오차범위", "판세")
CAUSE_WORDS = ("때문에", "탓에", "로 인해", "여파로")
COPY_LEN = 20

EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍⬀-⯿]")
_A = r"(?<![A-Za-z0-9_])"
_Z = r"(?![A-Za-z0-9_])"
INTERNAL = [re.compile(_A + r"T[1-5]" + _Z), re.compile(_A + r"(RED|YELLOW|GREEN)" + _Z),
            re.compile(_A + r"(verified|pending|credible_estimate|single_source)" + _Z), re.compile("GRADE_"),
            re.compile(_A + r"[a-z]+_[a-z_]+" + _Z), re.compile(r"i\d{8}-\d{2}(-e\d+)?"), re.compile(r"TODO|FIXME")]
AI_PHRASE = re.compile(r"AI ?가 ?(분석|정리|판단|선정|요약)|인공지능이 ?(분석|정리|판단)|AI 분석")
BAIT_END = re.compile(r"(\?|？|\?!|…|\.\.\.)\s*$")
MIDDOT = re.compile(r"[·ㆍ・]")
CLAUSE = re.compile(r"[,.;:!?\n，。]")
QUOTE = re.compile(r"'([^']+)'|\"([^\"]+)\"|“([^”]+)”|‘([^’]+)’|「([^」]+)」|『([^』]+)』")

MSG_CRIME = "범죄·비위 의혹은 수사기관이나 법원의 확정 문서 없이 제목과 첫 화면에 쓰지 않는다"
MSG_POLL = "판세를 말하는 문장은 가림 대상으로 표시한다"
TITLE_PATHS = re.compile(r"^titles\.(chosen|candidates\.\d+)$")
FIRST_SCREEN = re.compile(r"^(titles\.(chosen|candidates\.\d+)|what_new|so_far\.0|figures\.[^.]+\.(caption|alt))$")


def norm(s: str) -> str:
    """publish_gate.norm 과 같은 정규화 — 낱말 글자와 한글만 남기고 소문자로."""
    return re.sub(r"[^\w가-힣]+", "", s or "").lower()


def middot_run(text: str) -> bool:
    """가운뎃점으로 이은 항목이 4개 이상(구분자 3개 이상)인 연속 구간이 있는가. 쉼표·마침표가 구간을 끊는다."""
    return any(len(MIDDOT.findall(seg)) >= 3 for seg in CLAUSE.split(text))


def text_errors(path: str, text: str) -> list[str]:
    """한 칸의 문체 오류 문구 목록."""
    e: list[str] = []
    if EMOJI.search(text):
        e.append("이모지를 쓰지 않는다")
    for rx in INTERNAL:
        m = rx.search(text)
        if m:
            e.append(f"내부 표기 '{m.group(0)}'를 독자에게 보이는 글에 쓰지 않는다")
            break
    for w in DECORATIVE:
        if w in text:
            e.append(f"꾸미는 말 '{w}'을 쓰지 않는다")
    if middot_run(text):
        e.append("가운뎃점으로 명사를 넷 이상 잇지 않는다 — 문장으로 풀어 쓴다")
    if AI_PHRASE.search(text):
        e.append("'AI 가 분석' 같은 문구를 쓰지 않는다 — 모델을 쓴 사실은 AI 고지가 알린다")
    if TITLE_PATHS.match(path):
        for w in TITLE_BANNED:
            if w in text:
                e.append(f"제목 금지어 '{w}'를 쓰지 않는다")
        if BAIT_END.search(text):
            e.append("제목을 물음표나 말줄임으로 끝내지 않는다")
    return e


def crime_words(text: str) -> list[str]:
    return [w for w in CRIME_WORDS if w in text]


def style_errors(issue: dict, crime_exempt: set[str] = frozenset()) -> list[tuple[str, str]]:
    """[(칸 경로, 문구)]. crime_exempt 는 확정 근거가 받치는 주장이 쓴 범죄 낱말(check 가 rules 로 정해 넘긴다)."""
    errs: list[tuple[str, str]] = []
    for path, text, _nums, _item in model.reader_items(issue):
        errs += [(path, m) for m in text_errors(path, text)]
        if FIRST_SCREEN.match(path) and [w for w in crime_words(text) if w not in crime_exempt]:
            errs.append((path, MSG_CRIME))
    return errs


def poll_words(text: str) -> list[str]:
    return [w for w in POLL_WORDS if w in (text or "")]


def cause_warnings(issue: dict) -> list[tuple[str, str]]:
    """입장(평가·전망) 요약에 인과 낱말이 있으면 경고 — 인과를 옮겨 싣지 않는다."""
    out = []
    for s in issue.get("stances") or []:
        if isinstance(s, dict) and s.get("kind") in ("평가", "전망") and any(w in str(s.get("summary") or "") for w in CAUSE_WORDS):
            out.append((f"stances.{s.get('id')}.summary", "인과를 옮겨 싣지 않는다 — 검토가 본다"))
    return out


# ── 연속 20자 ─────────────────────────────────────────────────────────
def _segments(text: str, skip: list[str]) -> list[str]:
    """건너뛸 글(공식 명칭, 공식 근거에 그대로 있는 따옴표 인용)을 잘라 낸 나머지 조각들. 조각끼리 잇지 않는다."""
    segs = [text]
    for s in sorted({x for x in skip if x and x.strip()}, key=len, reverse=True):
        segs = [p for seg in segs for p in seg.split(s)]
    return segs


def copy20_hits(text: str, refs: list[str], proper_names=(), quote_ok=()) -> list[str]:
    """text 의 정규화한 20자 창 가운데 refs(보도 제목·읽은 본문 등)의 정규화한 글에 그대로 있는 것.
    proper_names 의 글은 건너뛰고, 따옴표 안 글이 quote_ok(인용한 공식 근거의 observed) 가운데 하나에 있으면 그 인용도 건너뛴다."""
    skip = list(proper_names)
    okn = [norm(q) for q in quote_ok]
    for m in QUOTE.finditer(text):
        q = next(g for g in m.groups() if g)
        if norm(q) and any(norm(q) in o for o in okn):
            skip.append(m.group(0))
    hay = [norm(r) for r in refs if r]
    hits: list[str] = []
    for seg in _segments(text, skip):
        n = norm(seg)
        for i in range(0, len(n) - COPY_LEN + 1):
            w = n[i:i + COPY_LEN]
            if any(w in h for h in hay):
                hits.append(w)
                break
    return hits


def copy20_warnings(issue: dict, evidences: dict, articles=()) -> list[tuple[str, str]]:
    """보도 근거의 기사 제목과 만들 때 읽은 기사 본문(articles — 저장하지 않는다)에 연속 20자가 같은 글 칸을 경고한다.
    예외: 공식 명칭(keywords + 근거 source.title)과, 인용한 공식 근거 observed 안에 있는 따옴표 인용."""
    refs = [str((e.get("report") or {}).get("title") or "") for e in evidences.values() if e.get("kind") == "보도"] + list(articles)
    if not any(r.strip() for r in refs):
        return []
    names = [str(k) for k in issue.get("keywords") or []] + [str((e.get("source") or {}).get("title") or "") for e in evidences.values()]
    out = []
    for path, text, _nums, item in model.reader_items(issue):
        cited = model.item_evidence_ids(item) if item is not None else list(evidences)
        obs = [str(evidences[i].get("observed") or "") for i in cited if i in evidences and evidences[i].get("kind") in ("공식 원문", "기관 자료")]
        if copy20_hits(text, refs, names, obs):
            out.append((path, "기사 글과 연속 20자가 같다 — 우리 말로 다시 쓴다"))
    return out
