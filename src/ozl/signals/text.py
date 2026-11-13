"""낱말(§3). 제목 정규화, 글자 두 개 묶음 Dice, 한국어(Kiwi)·영문 낱말과 고유명사, 간접 포착, 사람 이름 표시.

자료 파일(src/ozl/signals/data/)을 바꾸면 config.dict_version() 이 바뀌고 저장된 분석을 다시 한다.
명령: python -m ozl.signals.text build-broad | build-en-common
"""
from __future__ import annotations

import functools
import re
import sys

import yaml

from ozl.signals import config

HANJA = {"美": "미국", "中": "중국", "日": "일본", "韓": "한국", "北": "북한", "英": "영국", "獨": "독일", "佛": "프랑스",
         "與": "여당", "野": "야당", "靑": "청와대", "銀": "은행", "社": "사"}
_HEAD = re.compile(r"^\s*(?:\[[^\]]{0,10}\]\s*)+")
_TAIL = re.compile(r"\s*\((?:종합\d*보?|\d+보|속보)\)\s*$")
_SUM_HEAD = re.compile(r"^\s*(?:\[[^\]]{1,15}\]\s*)?(?:\([^)=]{1,15}=[^)]{1,15}\)\s*)?(?:[가-힣]{2,4}\s*(?:기자|특파원)\s*=\s*)?")
_SEP = re.compile(r"[\s…·,\"“”‘’'()\[\]:!?~|/]+|\.{2,}")
OOV_PARTICLES = sorted("에서 으로 에게 까지 부터 에 을 를 은 는".split(), key=len, reverse=True)   # 이름 끝과 헷갈리지 않는 것만
PARTICLES = sorted("은 는 이 가 을 를 의 에 에서 으로 로 와 과 도 만 까지 부터 에게".split(), key=len, reverse=True)
HONORIFICS = ("씨", "회장", "부회장", "대표", "사장", "장관", "의원", "지사", "시장", "총장", "위원장", "감독", "선수",
              "배우", "가수", "교수", "대통령", "총리", "CEO")
PERSON_RE = re.compile(r"[가-힣]{2,4}\s?(씨|의원|대표|회장|부회장|사장|장관|지사|총장|위원장|교수|대통령)")
EN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'&.\-]*")
_EDGE = re.compile(r"^[^\w가-힣]+|[^\w가-힣]+$")
_PUNCT_TAGS = {"SF", "SP", "SS", "SSO", "SSC", "SE", "SO", "SW"}


# ── 정규화와 유사도
def strip_head(t: str) -> str:
    """§3-1의 1~2단계: 꺾쇠 머리와 (종합)·(1보) 꼬리를 떼고 한자 약칭을 푼다. 띄어쓰기는 둔다."""
    s = _HEAD.sub("", t or "")
    s = _TAIL.sub("", s)
    for h, k in HANJA.items():
        s = s.replace(h, k)
    return s.strip()


def _squash(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def norm_title(t: str) -> str:
    """비교용 제목: 머리·꼬리를 떼고 한자 약칭을 푼 뒤 소문자로, 글자·숫자만 남긴다."""
    return _squash(strip_head(t))


def norm_summary(s: str) -> str:
    """요약의 (지역=매체) 아무개 기자 = 머리를 떼고 제목과 같게(꺾쇠 머리, (종합)·(1보) 꼬리, 한자 약칭) 정규화한 앞 150자."""
    body = _SUM_HEAD.sub("", s or "", count=1)
    return _squash(strip_head(body))[:config.SUMMARY_HEAD]


def bigrams(s: str) -> frozenset[str]:
    if len(s) < 2:
        return frozenset([s]) if s else frozenset()
    return frozenset(s[i:i + 2] for i in range(len(s) - 1))


def dice(a, b) -> float:
    """글자 두 개 묶음 Dice. 문자열이나 bigrams() 집합을 받는다."""
    A = a if isinstance(a, frozenset) else bigrams(a)
    B = b if isinstance(b, frozenset) else bigrams(b)
    if not A or not B:
        return 0.0
    return 2 * len(A & B) / (len(A) + len(B))


# ── 자료 파일
def _lines(name: str) -> list[str]:
    p = config.DATA / name
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            out.append(ln)
    return out


@functools.lru_cache(maxsize=None)
def resources() -> dict:
    from ozl.research import coverage, collect, videos
    amap = videos.load_keywords()
    ind = yaml.safe_load((config.DATA / "indirect.yaml").read_text(encoding="utf-8")) or {}
    broad_doc = {}
    bp = config.DATA / "broad_entities.yaml"
    if bp.exists():
        broad_doc = yaml.safe_load(bp.read_text(encoding="utf-8")) or {}
    ind_ko = [str(w) for w in ind.get("ko") or []]
    ind_en = [str(w).lower() for w in ind.get("en") or []]
    stop = set(_lines("stop_terms.txt")) | set(ind_ko) | {w for w in coverage.STOP if re.fullmatch(r"[가-힣]+", w)}
    stop |= {w.replace(" ", "") for w in ind_ko}
    if config.ROLE_WORDS_NOT_TERMS:
        stop |= set(config.ROLE_WORDS)
    return {
        "amap": amap,
        "canon": set(amap.values()),
        "broad": {str(x) for x in broad_doc.get("broad") or []},
        "persons": {str(x) for x in broad_doc.get("persons") or []},
        "stop": stop,
        "not_ent": set(_lines("not_entities.txt")),
        "seo_nouns": tuple(_lines("seo_nouns.txt")),
        "en_common": set(_lines("en_common.txt")),
        "en_stop": set(collect.EN_STOP),
        "ind_ko": ind_ko,
        "ind_en": ind_en,
    }


@functools.lru_cache(maxsize=1)
def kiwi():
    from kiwipiepy import Kiwi
    return Kiwi()


def _kkey(s: str) -> str:
    return re.sub(r"\s+", "", s or "").casefold()


def _strip_particle(w: str, parts=None) -> str:
    for p in parts or PARTICLES:
        if w.endswith(p) and len(w) - len(p) >= 2:
            return w[:-len(p)]
    return w


# ── 한국어
def _is_name(t) -> bool:
    """Kiwi 고유명사(NNP), 또는 Kiwi 사전에 없는 명사(oov). 모르는 이름은 문장 첫머리에서 NNG 로 나오는 일이 많다."""
    return t.tag == "NNP" or (t.tag.startswith("NN") and bool(getattr(t, "oov", False)))


def _seo_cut(core: str, toks, tok_eoj, i: int, end: int) -> bool:
    """어절 i 의 끝 '서'를 조사로 보고 뗄지. 둘 가운데 하나이고, 어절이 '서'로 끝나는 일반 낱말(seo_nouns.txt)로 끝나지 않을 때만:
    (가) Kiwi 가 '서'를 따로 떼고 바로 앞 형태소가 이름이다(한마음병원+서).
    (나) Kiwi 가 모르는 낱말(oov)이 '서'까지 삼켰고 어절이 네 글자 이상이다(덴린병원서). '미르문서'처럼 일반 낱말로 끝나면 떼지 않는다."""
    if any(core.endswith(w) for w in resources()["seo_nouns"]):
        return False
    mine = [t for t, ei in zip(toks, tok_eoj) if ei == i and t.start < end]
    if not mine or mine[-1].start + mine[-1].len != end:
        return False
    last = mine[-1]
    if last.form == "서":
        return len(mine) >= 2 and _is_name(mine[-2])
    return bool(getattr(last, "oov", False)) and last.form.endswith("서") and len(core) >= 4


def _analyze_ko(title: str) -> dict:
    R = resources()
    amap = R["amap"]
    text = strip_head(title)
    spans = [(m.start(), m.end(), m.group()) for m in re.finditer(r"(?:(?!" + _SEP.pattern + r").)+", text)]
    toks = kiwi().tokenize(text)
    ents: set[str] = set()
    person = False
    covered: set[int] = set()

    def canon(s: str) -> str | None:
        return amap.get(_kkey(s))

    def eoj_of(pos: int) -> int | None:
        for i, (s, e, _) in enumerate(spans):
            if s <= pos < e:
                return i
        return None

    tok_eoj = [eoj_of(t.start) for t in toks]
    # 별칭 먼저: 이웃 두 어절 붙임, 그다음 한 어절(조사 뗀 꼴 포함). 한 글자 별칭은 한국어 문장에서 오탐이 많아 쓰지 않는다.
    for i in range(len(spans) - 1):
        for key in (spans[i][2] + spans[i + 1][2], spans[i][2] + _strip_particle(spans[i + 1][2])):
            c = canon(key)
            if c:
                ents.add(c)
                covered |= {i, i + 1}
                break
    cores: dict[int, str] = {}
    for i, (s, e, w) in enumerate(spans):
        mine = [t for t, ei in zip(toks, tok_eoj) if ei == i]
        keep_end = e
        for t in reversed(mine):
            if t.tag.startswith("J") or t.tag in _PUNCT_TAGS:
                keep_end = min(keep_end, t.start)
            else:
                break
        core = text[s:keep_end] if keep_end > s else w
        if any(getattr(t, "oov", False) and t.start + t.len >= keep_end for t, ei in zip(toks, tok_eoj) if ei == i):
            core = _strip_particle(core, OOV_PARTICLES)   # 모르는 낱말이 조사까지 삼킨 경우(솔텍시에)
        if core.endswith("서") and _seo_cut(core, toks, tok_eoj, i, s + len(core)):
            core = core[:-1]   # 헤드라인의 '에서' 줄임(한마음병원서). '서'로 끝나는 일반 낱말(문서, 경찰서)이면 두지 않는다
        cores[i] = core
        if i in covered:
            continue
        for key in (w, _strip_particle(w), core):
            if len(_kkey(key)) >= 2 and canon(key):
                ents.add(canon(key))
                covered.add(i)
                break
    # 어절 보강: core 안에 NNP 가 있거나 다음 어절이 호칭으로 시작하면 core 전체가 이름이다.
    for i, (s, e, w) in enumerate(spans):
        if i in covered:
            continue
        core = cores[i]
        if len(core) < 2:
            continue
        has_nnp = any(_is_name(t) and ei == i and t.start < s + len(core) for t, ei in zip(toks, tok_eoj))
        nxt = spans[i + 1][2] if i + 1 < len(spans) else ""
        hon = any(nxt.startswith(h) for h in HONORIFICS)
        if has_nnp or hon:
            ents.add(canon(core) or core)
            covered.add(i)
            person = person or hon
    # Kiwi 고유명사(NNP 두 글자 이상, SL 두 글자 이상) 가운데 덮이지 않은 것
    terms: set[str] = set()
    for t, ei in zip(toks, tok_eoj):
        form = t.form.replace(" ", "")
        inside = ei in covered
        if (_is_name(t) or t.tag == "SL") and len(form) >= 2 and not inside:
            ents.add(canon(form) or form)
            continue
        if inside:
            continue
        if t.tag in ("NNG", "NNP") and len(form) >= 2:
            terms.add(form)
        elif t.tag == "SL" and len(form) >= 3:
            terms.add(form)
    return _finish(ents, terms, person, title, R)


def _finish(ents: set[str], terms: set[str], person: bool, title: str, R: dict) -> dict:
    out_e = set()
    seen = set()                          # 넓은 이름으로 옮긴 것까지(사람 이름 표시에 쓴다 — 넓은 이름에 사람도 있다)
    ind = {w.lower().replace(" ", "") for w in R["ind_ko"] + R["ind_en"]}
    for e in ents:
        e = _EDGE.sub("", e)              # 앞뒤 문장부호('.누리전자')
        if not e:
            continue
        if e.lower().replace(" ", "") in ind:
            continue                      # 간접 포착 낱말(SNS 등)은 묶기에 끼지 않게 고유명사로도 두지 않는다(§3-2)
        seen.add(e)
        if e in R["broad"] or e in R["not_ent"]:
            terms.add(e)
        elif len(e) >= 2 or e in R["canon"]:
            out_e.add(e)
    terms = {t for t in terms if t not in out_e and t not in R["stop"] and t.lower() not in R["en_stop"]}
    person = person or bool(seen & R["persons"]) or bool(PERSON_RE.search(strip_head(title)))
    low = (title or "").lower()
    indirect = any(w.lower() in low for w in R["ind_ko"]) or any(w in low for w in R["ind_en"])
    return {"entities": sorted(out_e), "terms": sorted(terms), "person": person, "indirect": indirect}


# ── 영문
def _analyze_en(title: str) -> dict:
    R = resources()
    common, stop = R["en_common"], R["en_stop"]
    words = [re.sub(r"['’]s$", "", w).rstrip(".'-") for w in EN_WORD.findall(strip_head(title).replace("’", "'"))]
    words = [w for w in words if w]
    ents: set[str] = set()
    in_ent: set[int] = set()
    run: list[int] = []

    def flush():
        if run:
            name = " ".join(words[j] for j in run)
            ents.add(R["amap"].get(_kkey(name), name))
            in_ent.update(run)
        run.clear()

    for j, w in enumerate(words):
        lw = w.lower()
        if w[0].isupper() and lw not in common and lw not in stop and len(w) >= 2:
            run.append(j)
        else:
            flush()
    flush()
    terms = {w.lower() for j, w in enumerate(words)
             if j not in in_ent and len(w) >= 3 and w.lower() not in stop and w.lower() not in common}
    return _finish(ents, terms, False, title, R)


def analyze(title: str, lang: str) -> dict:
    """{'entities': [...], 'terms': [...], 'person': bool, 'indirect': bool}. 넓은 이름은 entities 에서 빠져 terms 에 든다."""
    return _analyze_en(title) if lang == "en" else _analyze_ko(title)


# ── 자료 파일 만들기(한 번 만들고 그 뒤는 손으로 고친다)
BROAD_EXTRA = ["서울", "부산", "인천", "대구", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남",
               "경북", "경남", "제주", "뉴욕", "워싱턴", "베이징", "도쿄",
               "CEO", "CFO", "CTO", "AI", "IT", "ETF", "IPO", "M&A", "ESG"]


def _keyword_sections() -> dict[str, list[str]]:
    from ozl.research import videos
    sec, out = "", {}
    for ln in videos.KEYWORDS.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        m = re.fullmatch(r"#\s*([^\s#─:]{2,12})", s)
        if m:
            sec = m.group(1)
            continue
        m = re.match(r"([^#:\s][^:#]*?)\s*:\s*\[", s)
        if m:
            out.setdefault(sec, []).append(m.group(1).strip())
    return out


def build_broad() -> str:
    secs = _keyword_sections()
    broad = [c for s, cs in secs.items() if s.startswith("나라") or s == "지표·제도" for c in cs]
    persons = [c for s, cs in secs.items() if s == "인물" for c in cs]
    broad = list(dict.fromkeys(broad + BROAD_EXTRA))
    body = ("# 넓은 이름(1판) — entities 에서 빼고 terms 로 옮긴다. `python -m ozl.signals.text build-broad` 로 처음 만들었다.\n"
            "# broad: 별칭 사전 '나라·지역(도시)'·'지표·제도' 절 대표 표기 + 광역 지명 + 흔한 약어(HBM 은 넣지 않는다)\n"
            "# persons: 별칭 사전 '인물' 절 대표 표기(사람 이름 표시용)\n")
    body += yaml.safe_dump({"broad": broad, "persons": persons}, allow_unicode=True, sort_keys=False)
    (config.DATA / "broad_entities.yaml").write_text(body, encoding="utf-8")
    return f"넓은 이름 {len(broad)}개, 인물 {len(persons)}개를 썼다"


EN_COMMON_FEEDS = ("gnews_reuters", "gnews_ap", "bbc_", "guardian_", "ft_", "cnbc_")


def build_en_common(pulse_db=None) -> str:
    import sqlite3
    from collections import Counter
    db = pulse_db or config.paths()["pulse_db"]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cnt: Counter = Counter()
    for (feed, title) in con.execute("SELECT feed, title FROM items WHERE lang='en'"):
        if not feed or not feed.startswith(EN_COMMON_FEEDS):
            continue
        t = re.sub(r"\s+-\s+[^-]{2,40}$", "", title or "")   # 구글 뉴스의 ' - 매체' 꼬리
        ws = EN_WORD.findall(t)
        for w in ws[1:]:
            if w[0].islower():
                cnt[re.sub(r"'s$", "", w).rstrip(".'-")] += 1
    con.close()
    words = sorted(w for w, n in cnt.items() if n >= 2 and w)
    head = "# 영문 흔한 낱말 — 문장식 제목 피드에서 문장 첫 낱말이 아닌 자리에 소문자로 두 번 이상 나온 낱말. build-en-common 으로 한 번 만들고 고정.\n"
    (config.DATA / "en_common.txt").write_text(head + "\n".join(words) + "\n", encoding="utf-8")
    return f"영문 흔한 낱말 {len(words)}개를 썼다"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build-broad":
        print(build_broad())
    elif cmd == "build-en-common":
        print(build_en_common())
    else:
        print("쓰는 법: python -m ozl.signals.text build-broad | build-en-common", file=sys.stderr)
        sys.exit(2)
