"""이슈 기록 문체 검사기 시험 — 예시 문장은 전부 지어낸 것이다."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ozl.issues import style  # noqa: E402
from test_issues_check import I2, claim, desk, errors, has, load  # noqa: E402,F401  (desk 는 pytest fixture)

T = "titles.chosen"


@pytest.mark.parametrize("path,text,want", [
    (T, "한빛시 버스 요금 충격 인상", "제목 금지어 '충격'"),
    (T, "요금 인상, 결국 시의회로", "제목 금지어 '결국'"),
    ("what_new", "시가 놀라운 인상안을 냈다.", "꾸미는 말 '놀라운'"),
    ("what_new", "무려 400원이 오른다.", "꾸미는 말 '무려'"),
    (T, "버스 요금은 얼마나 오를까?", "물음표나 말줄임"),
    (T, "버스 요금 인상의 속사정…", "물음표나 말줄임"),
    ("so_far.0", "요금·적자·연료비·인건비가 함께 올랐다.", "가운뎃점으로 명사를 넷 이상"),
    ("so_far.0", "AI가 분석한 요금 인상의 배경이다.", "'AI 가 분석' 같은 문구"),
    ("so_far.0", "인공지능이 정리한 결과다.", "'AI 가 분석' 같은 문구"),
    ("so_far.0", "요금이 오른다 \U0001F68C", "이모지"),
    ("so_far.0", "출처 등급 T1 자료다.", "내부 표기 'T1'"),
    ("so_far.0", "판정은 verified 다.", "내부 표기 'verified'"),
    ("so_far.0", "자세한 것은 i20990101-01 기록에 있다.", "내부 표기 'i20990101-01'"),
    ("so_far.0", "badge_note 칸을 본다.", "내부 표기 'badge_note'"),
])
def test_banned_and_decorative(path, text, want):
    assert any(want in m for m in style.text_errors(path, text)), style.text_errors(path, text)


@pytest.mark.parametrize("path,text", [
    (T, "버스 400원 인상, 다음 결정은 2월 시의회"),
    ("so_far.0", "요금·적자·연료비가 함께 올랐다."),                 # 3항목 나열은 통과
    ("so_far.0", "요금·적자, 연료비·인건비가 함께 올랐다."),         # 쉼표가 끊으면 나열이 아니다
    ("what_new", "시가 1월 2일 요금 인상안을 발표했다."),
    ("so_far.0", "회의는 결국 다음 달로 미뤄졌다."),                 # 제목이 아닌 칸의 금지어는 묻지 않는다
])
def test_plain_sentences_pass(path, text):
    assert style.text_errors(path, text) == []


def test_title_style_through_check(desk):
    issue, evs = load(I2)
    t = "보조 배터리 1만 2천 개 회수, 충격의 화재 원인 판결은 아직 확정 전"
    issue["titles"]["candidates"][0]["text"] = issue["titles"]["chosen"] = t
    assert has(errors(issue, evs), "titles.chosen", "제목 금지어 '충격'")


def test_copy_20_warning(desk):
    ref = "누리전자, 배터리 결함 알고도 알리지 않았다는 증언"
    assert style.copy20_hits("가나일보는 누리전자 배터리 결함 알고도 알리지 않았다는 증언을 실었다.", [ref])
    assert not style.copy20_hits("누리전자가 결함을 알고도 한 달 넘게 숨겼다.", [ref])
    long_name = "누리전자 배터리 결함 알고도 알리지 않았다는 증언"           # 공식 명칭이면 그 글은 건너뛴다
    assert not style.copy20_hits("가나일보는 누리전자 배터리 결함 알고도 알리지 않았다는 증언을 실었다.", [ref], proper_names=[long_name])
    quoted = "공고는 '누리전자 배터리 결함 알고도 알리지 않았다는 증언'을 언급했다."
    assert style.copy20_hits(quoted, [ref])
    assert not style.copy20_hits(quoted, [ref], quote_ok=["누리전자 배터리 결함 알고도 알리지 않았다는 증언을 받았다."])
    issue, evs = load(I2)
    evs["i20990101-02-e4"]["report"]["title"] = "누리전자, 배터리 결함 알고도 한 달 넘게 알리지 않았다는 내부 증언 나와"
    claim(issue, "c4")["searched"] = "누리전자 공시와 배터리 결함 알고도 한 달 넘게 알리지 않았다는 내부 증언 기사"
    from ozl.issues import check
    r = check.check_issue(issue, evs, public=True)
    assert r["errors"] == [] and any("claims.c4.searched" in w and "연속 20자" in w for w in r["warnings"])
    arts = ["전문가들은 같은 배터리를 쓰는 집이 많고 회수 방법을 알아야 한다고 짚었다."]      # 만들 때 읽은 기사 본문(저장하지 않는다)
    assert any(" why_matters: " in w for w in check.check_issue(*load(I2), articles=arts)["warnings"])
    assert check.check_issue(*load(I2))["warnings"] == []


def test_norm_matches_publish_gate():
    spec = importlib.util.spec_from_file_location("publish_gate_for_test", ROOT / "scripts" / "publish_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    for s in ["버스 400원 인상, 시가 든 근거!", "Hanbit-City 2099 · 요금", "  공백\t탭\n줄  ", "", "ＡＢＣ 전각 글자_밑줄"]:
        assert style.norm(s) == gate.norm(s)
