"""출처와 약관 대장(sources_ledger.yaml)을 읽는다 — 수집 코드가 요청을 보내기 전에, 점수 계산이 저장분을 쓰기 전에 묻는 곳.

    allowed("yna_economy", "collect")   # 대장의 collect 칸이 '허용'일 때만 True
    verdict("trends_kr", "score_use")   # '허용' | '금지' | '불명'

판정은 허용, 금지, 불명 셋이다. 셋 가운데 하나가 아닌 값, 비어 있는 칸, 대장에 없는 출처는 불명으로 본다.
불명은 금지처럼 다룬다(allowed 가 False). 대장 파일이 없거나 읽지 못하면 모든 출처가 불명이다 —
요청이 나가지 않는 쪽이 안전하다.

운영 판단(policy): 대장의 줄은 원문에서 확인한 것만 적는다. 원문에 허락도 금지도 없어 '불명'으로 남았지만
운영자가 쓰기로 정한 쓰임은 대장 파일 맨 위의 policy 묶음에 따로 적는다(예: 공식 RSS 의 제목과 링크로 건수를 세기).
verdict() 는 줄의 값이 '불명'이고 policy 의 조건이 맞을 때만 '허용'을 돌려준다. '금지'는 어떤 policy 로도 풀리지 않는다.
어느 쪽에서 나온 허용인지는 verdict_source() 가 알려 준다(보고서에 '운영 판단'이라고 밝히는 데 쓴다).

사용자 결정(user_override): 대장이 허용하지 않는 쓰임을 사용자가 범위와 기한을 정해 직접 풀 수 있다. 비공개 파일
(private/ops/ledger_overrides.yaml)에 적고, 손으로 돌리는 도구가 부르는 require() 만 이 파일을 본다. allowed() 와 verdict() 는
보지 않으므로 자동 수집과 점수 계산은 대장의 판정만 따른다. 풀린 채로 요청할 때마다 그 사실을 표준 오류에 적는다.

시험은 PATH 를 지어낸 대장 파일로 바꿔 끼운다(monkeypatch.setattr(ledger, "PATH", ...)) 또는 path 인자를 넘긴다.
"""
from __future__ import annotations

import datetime
import pathlib
import sys
import threading

import yaml

PATH = pathlib.Path(__file__).resolve().parent / "sources_ledger.yaml"
FEEDS_PATH = pathlib.Path(__file__).resolve().parent / "feeds.yaml"   # policy 의 scope: feeds 가 가리키는 피드 목록
OVERRIDES_PATH = pathlib.Path(__file__).resolve().parents[3] / "private" / "ops" / "ledger_overrides.yaml"   # 사용자 결정(비공개)
VERDICTS = ("허용", "금지", "불명")
UNKNOWN = "불명"
POLICY_USES = ("score_use", "store", "backup")   # 운영 판단이 열 수 있는 쓰임(점수, 비공개 보관, 비공개 백업). 수집, 공개, 수익은 원문 근거로만 연다

_lock = threading.Lock()
_cache: dict[str, tuple[tuple[int, int], dict[str, dict]]] = {}   # 경로 → ((mtime_ns, 크기), 출처표)
_side: dict[str, tuple[tuple[int, int], object]] = {}             # 경로#종류 → ((mtime_ns, 크기), policy 묶음 | 피드 id)


def _read(path: pathlib.Path) -> dict[str, dict]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 없음·권한·깨진 YAML 모두 '대장 없음'
        return {}
    src = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(src, dict):
        return {}
    return {str(k): v for k, v in src.items() if isinstance(v, dict)}


def load(path: pathlib.Path | str | None = None) -> dict[str, dict]:
    """출처 id → 대장 줄. 파일이 없거나 깨졌으면 빈 dict. 파일이 바뀌면 다시 읽는다(수정 시각·크기 기준)."""
    p = pathlib.Path(path) if path is not None else PATH
    try:
        st = p.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return {}
    with _lock:
        hit = _cache.get(str(p))
        if hit and hit[0] == key:
            return hit[1]
    got = _read(p)
    with _lock:
        _cache[str(p)] = (key, got)
    return got


def _cached_side(p: pathlib.Path, kind: str, read):
    try:
        st = p.stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    k = f"{p}#{kind}"
    with _lock:
        hit = _side.get(k)
        if hit and hit[0] == key:
            return hit[1]
    got = read(p)
    with _lock:
        _side[k] = (key, got)
    return got


def policies(path: pathlib.Path | str | None = None) -> dict[str, dict]:
    """대장 파일 맨 위의 policy 묶음 — 규칙 이름 → {enabled, scope, when, uses, note}. 없거나 깨졌으면 빈 dict."""
    def read(p: pathlib.Path) -> dict[str, dict]:
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        pol = data.get("policy") if isinstance(data, dict) else None
        return {str(k): v for k, v in pol.items() if isinstance(v, dict)} if isinstance(pol, dict) else {}
    return _cached_side(pathlib.Path(path) if path is not None else PATH, "policy", read) or {}


def feed_ids() -> frozenset[str]:
    """feeds.yaml 의 feeds 에 있는 피드 id — policy 의 scope: feeds 가 이 목록 안의 출처에만 닿는다."""
    def read(p: pathlib.Path) -> frozenset[str]:
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return frozenset()
        feeds = data.get("feeds") if isinstance(data, dict) else None
        return frozenset(str(f["id"]) for f in feeds or [] if isinstance(f, dict) and f.get("id"))
    return _cached_side(FEEDS_PATH, "feeds", read) or frozenset()


def _raw(entry: dict | None, use: str) -> str:
    v = entry.get(use) if entry else None
    v = v.strip() if isinstance(v, str) else None
    return v if v in VERDICTS else UNKNOWN


def _policy_for(source_id: str, entry: dict, use: str, path: pathlib.Path | str | None) -> str | None:
    """이 출처의 이 쓰임을 허용으로 보게 하는 운영 판단의 이름. 없으면 None.
    규칙은 enabled 가 참이고, scope 가 'feeds'(feeds.yaml 의 피드)이며, when 의 칸이 모두 맞고, uses 에 그 쓰임이 있어야 한다."""
    for name, rule in policies(path).items():
        if rule.get("enabled") is not True or rule.get("scope") != "feeds":
            continue
        uses, when = rule.get("uses"), rule.get("when")
        if use not in POLICY_USES or not isinstance(uses, list) or use not in uses or not isinstance(when, dict) or not when:
            continue
        if source_id not in feed_ids():
            continue
        if all(_raw(entry, str(k)) == v for k, v in when.items()):
            return name
    return None


def verdict_source(source_id: str | None, use: str, path: pathlib.Path | str | None = None) -> tuple[str, str]:
    """(판정, 어디서 나왔나). 어디서: '대장' 또는 '운영 판단: <규칙 이름>'."""
    entry = load(path).get(str(source_id)) if source_id is not None else None
    if not entry:
        return UNKNOWN, "대장"
    v = _raw(entry, use)
    if v == UNKNOWN:
        name = _policy_for(str(source_id), entry, use, path)
        if name:
            return "허용", f"운영 판단: {name}"
    return v, "대장"


def verdict(source_id: str | None, use: str, path: pathlib.Path | str | None = None) -> str:
    """'허용' | '금지' | '불명'. 대장에 없는 출처, 세 낱말이 아닌 값은 '불명'.
    줄의 값이 '불명'이어도 대장 파일의 policy(운영 판단)가 그 쓰임을 열어 두었으면 '허용'이다. '금지'는 풀리지 않는다."""
    return verdict_source(source_id, use, path)[0]


def allowed(source_id: str | None, use: str, path: pathlib.Path | str | None = None) -> bool:
    return verdict(source_id, use, path) == "허용"


class Blocked(RuntimeError):
    """대장이 허용하지 않은 출처로 요청하려 했다."""


def _today() -> str:
    return datetime.date.today().isoformat()


def user_override(source_id: str, use: str = "collect", overrides_path: pathlib.Path | str | None = None,
                  today: str | None = None) -> dict | None:
    """사용자가 범위와 기한을 정해 직접 푼 결정. 조건을 모두 채운 줄만 돌려준다: uses 에 그 쓰임이 있고,
    decided_by 가 '사용자'이고, decided_at 과 scope 가 적혀 있고, until(YYYY-MM-DD)이 오늘 이후다.
    파일이 없거나 깨졌거나 칸이 하나라도 비면 None(풀리지 않는다)."""
    p = pathlib.Path(overrides_path) if overrides_path is not None else OVERRIDES_PATH
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 없음, 권한, 깨진 YAML 모두 '결정 없음'
        return None
    rules = data.get("overrides") if isinstance(data, dict) else None
    rule = rules.get(str(source_id)) if isinstance(rules, dict) else None
    if not isinstance(rule, dict):
        return None
    uses = rule.get("uses")
    if not isinstance(uses, list) or use not in uses:
        return None
    if rule.get("decided_by") != "사용자" or not rule.get("decided_at") or not rule.get("scope"):
        return None
    until = str(rule.get("until") or "")
    day = today or _today()
    if len(until) != 10 or day > until:
        return None
    return rule


def require(source_id: str, use: str = "collect", path: pathlib.Path | str | None = None,
            overrides_path: pathlib.Path | str | None = None) -> None:
    """손으로 돌리는 도구가 요청 직전에 부른다. 허용이 아니면 Blocked 를 던진다(요청을 보내지 않는다).
    대장이 허용하지 않아도 사용자 결정(user_override)이 있으면 그 사실을 표준 오류에 적고 지나간다."""
    if allowed(source_id, use, path):
        return
    rule = user_override(source_id, use, overrides_path)
    if rule:
        print(f"[ledger] {source_id}: 대장은 {verdict(source_id, use, path)}. 사용자 결정으로 진행한다 — "
              f"{rule['scope']} (정한 때 {rule['decided_at']}, 기한 {rule['until']})", file=sys.stderr)
        return
    raise Blocked(f"{source_id}: {off_reason(source_id, use, path)} — 출처 대장(sources_ledger.yaml)이 허용하지 않아 요청하지 않는다")


def scorable(off: set[str] | frozenset[str] = frozenset(), path: pathlib.Path | str | None = None):
    """항목 → 점수와 화면에 써도 되나. 꺼 둔 소스(off)가 아니고, 대장의 score_use 가 '허용'인 출처(항목의 feed)여야 한다.
    매시 화면(pulse.snapshot), 아침 발굴(research.collect), 이슈 브리핑 후보(briefs.candidates)가 같이 쓴다."""
    ok: dict[str, bool] = {}

    def usable(i: dict) -> bool:
        f = i.get("feed")
        if f in off:
            return False
        if f not in ok:
            ok[f] = allowed(f, "score_use", path)
        return ok[f]
    return usable


def off_reason(source_id: str | None, use: str = "collect", path: pathlib.Path | str | None = None) -> str:
    """막힌 출처의 상태 문구 — '꺼짐(대장: 금지)' 또는 '꺼짐(대장: 불명)'."""
    return f"꺼짐(대장: {verdict(source_id, use, path)})"
