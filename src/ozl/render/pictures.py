"""그림 검수 대장 — 덱에 넣는 그림 파일마다 남기는 검수 기록과 그 판정.

대장은 사양의 맨 위 `pictures:` 목록이다(사양 옆 파일이 아니다). 까닭:
  - 완성본 폴더에 사양 사본이 들어가고, 진행 기록(progress)과 검토 묶음(bundle)이 사양 sha256 하나로 판을 가린다.
    대장을 사양 안에 두면 그림 검수 기록이 같은 지문에 묶여, 검토한 판과 다른 대장으로 빌드하는 일이 생기지 않는다.
  - 검사(check)는 사양 사전 하나만 받는다. 옆 파일이면 사양 경로를 따로 알아야 하고, 옮기거나 복사할 때 짝이 끊긴다.

쪽에서는 `picture: <그림 번호>` 로 부른다(image_text · number · photo_caption 의 그림 자리, image_pair 의 각 자리).

칸(FIELDS — 하나라도 비면 그 그림은 엄격 모드에서 실패, 초안 모드에서는 [그림 대기]):
  id 그림 번호(p1, p2 …) · path 파일 경로(저장소 기준 상대 또는 절대) · kind 그림 종류(KIND_RULES 의 이름)
  source_url 출처 주소 · origin 원출처 · rights_holder 권리자 · license 라이선스
  commercial_ok 상업적 이용이 되는가(참/거짓) · modify_ok 변경이 되는가(참/거짓) · attribution 출처 표시 문구
  reverse_search 역검색 {did: 한 일, result: 결과} · synthetic_check 합성 여부 확인 · content_check 인물·로고·지도 점검
  checked_at 확인 시각(ISO) · as_is 원형 그대로 썼는가(참/거짓) · map 지도인가(참/거짓 — 모든 종류에서 답한다)
  sha256 검수한 파일의 해시(검사·빌드 때 다시 해시해 다르면 그 그림을 쓰지 않는다)
칸끼리: 라이선스에 NC 가 있으면 commercial_ok 가 거짓, ND 가 있으면 modify_ok 가 거짓이어야 한다. 점검 글·파일 이름·원출처·주소가
  지도를 가리키면 종류와 상관없이 map_check 를 요구한다. 그림 밑 표기의 수는 라이선스 판 번호·유형과 출처 주소·확인 시각의 연도만 받는다.
  파일 짧은 변은 MIN_SHORT_PX 이상.
조건 칸: edits(as_is 가 거짓이면 자르기·덧칠 내용) · map_check {east_sea: 참, dokdo: 참}(지도) ·
         permission(기업 뉴스룸 — 이용 조건에서 사용 허락을 확인한 기록) · meme_origin(밈의 유래)

판정(설계 5-7절 그림 종류 표를 그대로 옮겼다 — KIND_RULES):
  쓴다 / 원형 그대로만 / 허락 기록이 있을 때만 원형으로 / 연습용 판(초안 모드)에서만 / 쓰지 않는다.
  상업적 이용이 안 되는 그림은 종류와 상관없이 쓰지 않는다(수익 계획). 변경이 안 되는 그림을 고쳐 썼으면 실패다.
  밈은 엄격 모드에서 실패가 아니라 빠진다(drop_memes — 빌드 출력과 러닝시트에 뺀 것을 적는다).

못 하는 것: 칸이 채워졌는지, 칸끼리 맞는지만 본다. 역검색을 실제로 했는지, 라이선스 주장이 사실인지는 사람이 본다.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import pathlib
import re
import unicodedata
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[3]

PIC_ID = re.compile(r"^p\d{1,3}$")

# 판정 이름
USE = "쓴다"
AS_IS = "원형 그대로만"
PERMIT = "허락 기록이 있을 때만 원형으로"
DRAFT_ONLY = "연습용 판에서만"
NEVER = "쓰지 않는다"

AI_MARK = "AI 생성 이미지, 실제 장면 아님"
TRADEMARK_NOTE = "상표는 각 소유자의 것"
# 로고를 쓰려면 따로 허락을 요구하는 회사 — 이 권리자의 로고는 쓰지 않는다(설계 표의 예).
# 권리자 칸을 NFKC 정규화·casefold 한 뒤 낱말 경계로 견준다(logo_blocked): 'Apple Inc' · 'Apple Korea' · 전각 'Ａpple' 도 걸린다.
# 한글 항목은 낱말 앞머리로도 견준다('애플코리아').
LOGO_BLOCKED = ("Apple", "Apple Inc.", "애플")
MIN_SHORT_PX = 300   # 그림 파일 짧은 변의 최소 픽셀 — 이보다 작으면 슬라이드에서 뭉개진다


@dataclass(frozen=True)
class Rule:
    verdict: str
    note: str = ""
    as_is: bool = False        # 원형 그대로만(as_is 가 참이어야 한다)
    credit: bool = False       # 저작자와 라이선스 표기가 그림 밑에 찍혀야 한다(attribution 이 권리자를 담아야)
    permission: bool = False   # 이용 조건에서 사용 허락을 확인한 기록(permission 칸)
    map: bool = False          # 지도 — 동해·독도 표기 확인(map_check)
    mark: str = ""             # 그림 밑에 따로 찍는 표시
    warn: str = ""             # 쓸 수 있지만 알리는 말
    license_has: tuple = ()    # 라이선스 칸에 들어 있어야 할 표기(하나라도)
    license_not: tuple = ()    # 라이선스 칸에 있으면 안 되는 표기


KIND_RULES: dict[str, Rule] = {
    "직접 그린 도표": Rule(USE),
    "직접 그린 지도": Rule(USE, map=True),
    "공공누리 1유형": Rule(USE, "저작자와 라이선스 표기", credit=True, license_has=("1유형",)),
    "CC BY": Rule(USE, "저작자와 라이선스 표기", credit=True, license_has=("CC BY",), license_not=("SA", "NC", "ND")),
    "CC BY-SA": Rule(AS_IS, "고쳐 쓰면 결과물에도 같은 라이선스를 붙여야 해서 원형 그대로만", as_is=True, credit=True, license_has=("BY-SA",),
                     license_not=("NC", "ND")),
    "공공누리 3유형": Rule(AS_IS, "변경 금지", as_is=True, credit=True, license_has=("3유형",)),
    "기업 뉴스룸": Rule(PERMIT, "그 뉴스룸의 이용 조건에서 사용 허락을 확인한 것만, 변형 없이", as_is=True, permission=True),
    "무료 스톡 인물 사진": Rule(USE, warn="무료 스톡의 인물 사진이다 — 부정적인 소재의 쪽에는 쓰지 않는다(쪽의 소재는 사람이 본다)"),
    "로고": Rule(AS_IS, "그 회사를 가리키는 자리에만 원형으로 작게", as_is=True, mark=TRADEMARK_NOTE),
    "AI 개념도": Rule(USE, "사람이 없는 개념도만", mark=AI_MARK),
    "밈": Rule(DRAFT_ONLY, "원출처와 라이선스가 확인된 것만, 연습용 판에서만"),
    "통신사·언론사 사진": Rule(NEVER, "우리 방침"),
    "방송 화면 캡처": Rule(NEVER, "우리 방침"),
    "공공누리 2유형": Rule(NEVER, "상업적 이용 금지 — 수익 계획이 있다"),
    "공공누리 4유형": Rule(NEVER, "상업적 이용과 변경 금지 — 수익 계획이 있다"),
    "실존 인물 AI 그림": Rule(NEVER),
    "사실처럼 보이는 AI 장면": Rule(NEVER),
}
MEME = "밈"
MAP_KINDS = ("직접 그린 지도",)

FIELDS = {
    "id": "그림 번호", "path": "파일 경로", "kind": "그림 종류", "source_url": "출처 주소", "origin": "원출처", "rights_holder": "권리자",
    "license": "라이선스", "commercial_ok": "상업적 이용", "modify_ok": "변경", "attribution": "출처 표시 문구", "reverse_search": "역검색",
    "synthetic_check": "합성 여부 확인", "content_check": "인물·로고·지도 점검", "checked_at": "확인 시각", "as_is": "원형 그대로",
    "map": "지도인가", "sha256": "파일 해시",
}
BOOL_FIELDS = ("commercial_ok", "modify_ok", "as_is", "map")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

# 라이선스 조건 — 약자와 풀어 쓴 낱말(공백·하이픈을 뺀 대문자로 견준다)
LICENSE_WORDS = {
    "NC": ("NONCOMMERCIAL", "비영리", "영리금지"),
    "ND": ("NODERIVATIVES", "NODERIVS", "NODERIVATIVE", "변경금지"),
    "SA": ("SHAREALIKE", "동일조건"),
}
# 지도로 보이는 낱말 — '지도 아님' · '지도 없음' 처럼 부정이 바로 뒤에 붙으면 세지 않는다
MAP_HINT = re.compile(r"(지도|동해|독도)(?!\s*(?:아님|아니|없))|\bmaps?\b", re.IGNORECASE)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def _words(s: str) -> list[str]:
    return re.findall(r"\w+", _norm(s))


def _hangul(w: str) -> bool:
    return any("가" <= ch <= "힣" for ch in w)


def logo_blocked(holder: str) -> str:
    """권리자 이름이 LOGO_BLOCKED 의 한 항목과 낱말 경계로 맞으면 그 항목, 아니면 빈 문자열.
    항목의 낱말들이 권리자 이름 안에 이어서 나오면 맞다(마지막 낱말이 한글이면 앞머리만 맞아도 된다)."""
    hw = _words(holder)
    for x in LOGO_BLOCKED:
        xw = _words(x)
        n = len(xw)
        if not n:
            continue
        for i in range(len(hw) - n + 1):
            head, last = hw[i:i + n - 1], hw[i + n - 1]
            if head == xw[:-1] and (last == xw[-1] or (_hangul(xw[-1]) and last.startswith(xw[-1]))):
                return x
    return ""


def license_conditions(lic: str) -> set[str]:
    """라이선스 글에 붙은 조건(NC · ND · SA) — 약자 낱말 또는 풀어 쓴 낱말."""
    up = _norm(lic).upper()
    toks = set(re.findall(r"[A-Z]+", up))
    flat = re.sub(r"[\s\-_·.]", "", up)
    return {k for k, words in LICENSE_WORDS.items() if k in toks or any(w.upper() in flat for w in words)}


def looks_like_map(e: dict) -> bool:
    """점검 글·파일 이름·원출처·출처 주소가 지도를 가리키는가('지도 아님' 같은 부정은 세지 않는다)."""
    texts = [_s(e.get("content_check")), _s(e.get("origin")), pathlib.Path(_s(e.get("path"))).stem, _s(e.get("source_url"))]
    return any(MAP_HINT.search(re.sub(r"[_\-]", " ", t)) for t in texts if t)


_LICENSE_NUM_OK = re.compile(r"\d+\.\d+|제?\s*\d\s*유형")


def credit_number_errors(e: dict) -> list[str]:
    """그림 밑 표기(출처 표시 문구·라이선스)에 실을 수 있는 수: 라이선스 판 번호(4.0)·공공누리 유형, 출처 표시 문구의 연도 가운데
    출처 주소에 있거나 확인 시각의 연도인 것. 그 밖의 수는 숫자 대조를 받지 않는 글에 수량을 싣는 길이라 실패다."""
    out = []
    lic = _s(e.get("license"))
    rest = _LICENSE_NUM_OK.sub(" ", unicodedata.normalize("NFKC", lic))
    if re.search(r"\d", rest):
        out.append(f"라이선스 '{lic}' 에 판 번호(4.0)·공공누리 유형 말고 다른 수가 있다")
    att = unicodedata.normalize("NFKC", _s(e.get("attribution")))
    ok_years = set(re.findall(r"(?<!\d)\d{4}(?!\d)", _s(e.get("source_url"))))
    ca = _s(e.get("checked_at"))[:4]
    if ca.isdigit():
        ok_years.add(ca)
    for tok in re.findall(r"\d[\d,.]*", att):
        if tok not in ok_years:
            out.append(f"출처 표시 문구 '{_s(e.get('attribution'))}' 의 수 '{tok}' — 출처 주소나 확인 시각의 연도만 적을 수 있다(그림 밑 표기는 숫자 대조를 받지 않는다)")
    return out
OWN_KINDS = ("직접 그린 도표", "직접 그린 지도")   # 출처 주소 칸에 주소 대신 자료 경로·설명을 적어도 된다


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def ledger(spec: dict) -> tuple[dict[str, dict], list[str]]:
    """사양의 pictures 목록 → ({그림 번호: 기록}, 모양 오류). 번호가 겹치거나 형식이 틀리면 오류."""
    raw = spec.get("pictures")
    if raw is None:
        return {}, []
    if not isinstance(raw, list):
        return {}, ["pictures 는 그림 검수 기록의 목록이어야 한다"]
    out: dict[str, dict] = {}
    errs = []
    for k, e in enumerate(raw):
        if not isinstance(e, dict):
            errs.append(f"pictures[{k}]: 사전(mapping)이어야 한다")
            continue
        pid = _s(e.get("id"))
        if not PIC_ID.match(pid):
            errs.append(f"pictures[{k}]: 그림 번호 '{pid}' 는 p1 · p2 … 꼴이어야 한다")
            continue
        if pid in out:
            errs.append(f"pictures[{k}]: 그림 번호 {pid} 가 겹친다")
            continue
        out[pid] = e
    return out, errs


def resolve_path(e: dict) -> pathlib.Path:
    p = pathlib.Path(_s(e.get("path")))
    return p if p.is_absolute() else ROOT / p


def is_meme(e: dict | None) -> bool:
    return bool(e) and _s(e.get("kind")) == MEME


def rule_of(e: dict) -> Rule | None:
    return KIND_RULES.get(_s(e.get("kind")))


def _checked_at_ok(v) -> bool:
    if isinstance(v, (dt.date, dt.datetime)):
        return True
    try:
        dt.datetime.fromisoformat(_s(v))
        return True
    except ValueError:
        return False


def judge(e: dict, draft: bool = False) -> tuple[str, list[str], list[str]]:
    """(판정, 이 그림을 쓰지 못하는 까닭, 경고). 까닭이 비어 있으면 이 모드에서 쓸 수 있다.
    판정은 종류 표의 이름(KIND_RULES)이고, 상업적 이용이 안 되면 종류와 상관없이 NEVER."""
    why: list[str] = []
    warns: list[str] = []
    kind = _s(e.get("kind"))
    rule = KIND_RULES.get(kind)
    for k, name in FIELDS.items():
        v = e.get(k)
        if k in BOOL_FIELDS:
            if not isinstance(v, bool):
                why.append(f"{name}({k}) 칸이 참/거짓으로 적혀 있지 않다")
        elif k == "reverse_search":
            if not (isinstance(v, dict) and _s(v.get("did")) and _s(v.get("result"))):
                why.append("역검색(reverse_search) 칸에 한 일(did)과 결과(result)가 둘 다 있어야 한다")
        elif not _s(v):
            why.append(f"{name}({k}) 칸이 비었다")
    if rule is None:
        return NEVER, why + [f"그림 종류 '{kind}' 는 종류 표에 없다({' · '.join(KIND_RULES)}) — 표에 없는 종류는 쓰지 않는다"], warns
    verdict = rule.verdict
    if e.get("commercial_ok") is False:
        verdict = NEVER
        why.append("상업적 이용이 안 되는 그림이다 — 수익 계획이 있어 쓰지 않는다")
    if rule.verdict == NEVER:
        why.append(f"'{kind}' 는 쓰지 않는다" + (f"({rule.note})" if rule.note else ""))
    if e.get("checked_at") not in (None, "") and not _checked_at_ok(e.get("checked_at")):
        why.append(f"확인 시각 '{_s(e.get('checked_at'))}' 를 시각으로 읽지 못했다(ISO 꼴: 2099-01-02T10:00:00+09:00)")
    url = _s(e.get("source_url"))
    if url and kind not in OWN_KINDS and not url.startswith(("https://", "http://")):
        why.append(f"출처 주소 '{url}' 가 주소가 아니다")
    if e.get("as_is") is False:
        if not _s(e.get("edits")):
            why.append("원형 그대로가 아니면(as_is: false) 자르기·덧칠 내용(edits)을 적어야 한다")
        if e.get("modify_ok") is False:
            why.append("변경이 안 되는 그림(modify_ok: false)을 고쳐 썼다(as_is: false)")
        if rule.as_is:
            why.append(f"'{kind}' 는 원형 그대로만 쓴다 — as_is: false 면 쓰지 않는다")
    lic = _s(e.get("license"))
    if lic and rule.license_has and not any(x.upper() in _norm(lic).upper() for x in rule.license_has):
        why.append(f"라이선스 '{lic}' 가 종류 '{kind}' 와 맞지 않는다({' 또는 '.join(rule.license_has)} 표기가 없다)")
    conds = license_conditions(lic)
    bad = [x for x in rule.license_not if x in conds]
    if bad:
        why.append(f"라이선스 '{lic}' 에 {bad} 조건이 붙어 있다 — 종류 '{kind}' 로 쓰지 않는다")
    # 칸끼리: 라이선스 조건과 참/거짓 칸이 어긋나면 어느 쪽이 맞는지 모른다 — 쓰지 않는다
    if "NC" in conds and e.get("commercial_ok") is True:
        why.append(f"라이선스 '{lic}' 에 비영리(NC) 조건이 있는데 상업적 이용(commercial_ok) 칸이 참이다 — 칸끼리 어긋난다")
    if "ND" in conds and e.get("modify_ok") is True:
        why.append(f"라이선스 '{lic}' 에 변경 금지(ND) 조건이 있는데 변경(modify_ok) 칸이 참이다 — 칸끼리 어긋난다")
    why += credit_number_errors(e)
    sha = _s(e.get("sha256")).lower()
    if sha and not SHA_RE.match(sha):
        why.append(f"파일 해시(sha256) '{_s(e.get('sha256'))}' 가 sha256 꼴(16진 64자)이 아니다")
    if rule.credit:
        holder = _s(e.get("rights_holder"))
        att = _s(e.get("attribution"))
        if att and holder and holder not in att:
            why.append(f"출처 표시 문구에 저작자(권리자 '{holder}')가 없다 — '{kind}' 는 저작자와 라이선스를 표기해야 한다")
    if rule.permission and not _s(e.get("permission")):
        why.append("기업 뉴스룸 그림은 그 뉴스룸의 이용 조건에서 사용 허락을 확인한 기록(permission)이 있어야 한다 — 찾지 못했으면 쓰지 않는다")
    if kind == "로고":
        hit = logo_blocked(_s(e.get("rights_holder")))
        if hit:
            verdict = NEVER
            why.append(f"권리자 '{_s(e.get('rights_holder'))}' 는 로고 사용에 따로 허락을 요구하는 회사다(LOGO_BLOCKED '{hit}') — 쓰지 않는다")
    if e.get("map") is False and (rule.map or looks_like_map(e)):
        why.append("지도인가(map) 칸이 거짓인데 " + ("종류가 지도다" if rule.map else "점검 글·파일 이름·원출처·주소가 지도를 가리킨다")
                   + " — 지도면 map: true 와 동해·독도 확인(map_check)을 적는다")
    if rule.map or e.get("map") is True or looks_like_map(e):
        mc = e.get("map_check")
        if not (isinstance(mc, dict) and mc.get("east_sea") is True and mc.get("dokdo") is True):
            why.append("지도는 동해와 독도 표기를 확인한 기록(map_check: {east_sea: true, dokdo: true})이 있어야 한다")
    if kind == MEME:
        if not _s(e.get("meme_origin")):
            why.append("밈은 유래(meme_origin)를 적어야 한다")
        if not draft:
            why.append("밈은 연습용 판(초안 모드)에서만 쓴다 — 엄격 모드는 빼고 만든다(drop_memes)")
    if rule.warn:
        warns.append(rule.warn)
    return verdict, why, warns


def credit_lines(e: dict) -> list[str]:
    """그림 밑에 찍는 표기(위에서 아래로): 따로 찍는 표시(AI 표시·상표 고지) · '출처 표시 문구 · 라이선스'.
    숫자 대조에서 빼는 구조 글이다(원문 캡처의 호스트 줄과 같다)."""
    rule = rule_of(e)
    out = []
    if rule and rule.mark == AI_MARK:
        out.append(AI_MARK)
    line = " · ".join(x for x in (_s(e.get("attribution")), _s(e.get("license"))) if x)
    if rule and rule.mark == TRADEMARK_NOTE:
        line = " · ".join(x for x in (line, TRADEMARK_NOTE) if x)
    if line:
        out.append(line)
    return out


def file_error(e: dict) -> str:
    """그림 파일을 열 수 있는가. 빈 문자열이면 연다."""
    p = resolve_path(e)
    if not p.is_file():
        return f"그림 파일이 없다: {p}"
    try:
        from PIL import Image
        with Image.open(p) as g:
            size = g.size
            g.verify()
    except Exception as x:  # noqa: BLE001 — 그림으로 읽지 못하면 사유 한 줄
        return f"그림 파일을 그림으로 읽지 못했다({type(x).__name__}): {p}"
    if min(size) < MIN_SHORT_PX:
        return f"그림 파일이 너무 작다({size[0]}x{size[1]} — 짧은 변 {MIN_SHORT_PX}px 이상): {p}"
    want = _s(e.get("sha256")).lower()
    if want:
        got = file_sha256(p)
        if got != want:
            return f"그림 파일의 sha256 이 대장과 다르다(검수 뒤 파일이 바뀌었다 — 대장 {want[:12]}… · 지금 {got[:12]}…): {p}"
    return ""


def file_sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 밈 빼기(엄격 모드) ──────────────────────────────────────────────────────
DROPPED = "_dropped"   # image_pair 의 자리에서 밈을 뺐다는 표시(빌드가 그 자리를 비운다)


def drop_memes(spec: dict) -> tuple[dict, list[str]]:
    """엄격 모드(완성본·공개용)에서 밈 그림을 뺀 사양과, 뺀 것을 적은 글 목록. 원래 사양은 고치지 않는다.
    - photo_caption 쪽의 그림이 밈이면 쪽을 뺀다.
    - image_text · number 의 그림 자리가 밈이면 picture 칸을 지운다(그림 자리가 빈다).
    - image_pair 의 한 자리가 밈이면 그 자리를 비운다(DROPPED 표시 — 설명도 함께 뺀다). 두 자리가 다 밈이면 쪽을 뺀다.
    쪽 번호는 원래 사양 기준으로 적는다."""
    pics, _ = ledger(spec)
    sp = copy.deepcopy(spec)
    notes: list[str] = []
    keep = []
    for i, sl in enumerate(sp.get("slides") or [], 1):
        if not isinstance(sl, dict):
            keep.append(sl)
            continue
        kind = sl.get("kind")
        pid = _s(sl.get("picture"))
        if pid and is_meme(pics.get(pid)):
            if kind == "photo_caption":
                notes.append(f"{i}쪽(photo_caption): 밈 {pid} 을 뺐다 — 쪽을 뺐다")
                continue
            sl.pop("picture", None)
            notes.append(f"{i}쪽({kind}): 밈 {pid} 을 뺐다 — 그림 자리를 비웠다")
        if kind == "image_pair" and isinstance(sl.get("pair"), list):
            memes = [j for j, slot in enumerate(sl["pair"]) if isinstance(slot, dict) and is_meme(pics.get(_s(slot.get("picture"))))]
            if memes and len(memes) == len(sl["pair"]):
                # 두 자리가 다 밈이면 빈 두 칸짜리 장이 남는다 — photo_caption 처럼 쪽을 뺀다
                ids = " · ".join(_s(sl["pair"][j].get("picture")) for j in memes)
                notes.append(f"{i}쪽(image_pair): 두 자리가 다 밈({ids})이다 — 쪽을 뺐다")
                continue
            for j in memes:
                notes.append(f"{i}쪽(image_pair) {'왼' if j == 0 else '오른'}쪽 자리: 밈 {_s(sl['pair'][j].get('picture'))} 을 뺐다 — 그 자리를 비웠다")
                sl["pair"][j] = {DROPPED: "밈"}
        keep.append(sl)
    sp["slides"] = keep
    return sp, notes


def dropped_summary(notes: list[str]) -> str:
    """러닝시트·빌드 출력 한 줄: '밈 2장을 뺐다(엄격 모드) — …'."""
    if not notes:
        return ""
    return f"밈 {len(notes)}장을 뺐다(엄격 모드 — 완성본·공개용 판에는 밈을 넣지 않는다): " + " / ".join(notes)
