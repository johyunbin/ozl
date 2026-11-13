"""공개 문서의 문체 검사 — 지어낸 문장으로만 시험한다."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("style_check", ROOT / "scripts" / "style_check.py")
SC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SC)


def errs(text, **kw):
    return [m for _, m in SC.check_text(text, **kw)[0]]


def test_plain_sentences_pass():
    text = "한빛시는 지어낸 도시다.\n\n- 기록은 파일에 둔다.\n- 승인은 운영 화면에서 한다.\n"
    assert errs(text) == []


def test_catches_each_rule():
    assert any("이모지" in m for m in errs("기록을 올렸다 \U0001F680"))
    assert any("꾸미는 말" in m for m in errs("혁신적 검증 체계를 만들었다."))
    assert any("부풀리는 말" in m for m in errs("두 모델의 시너지를 낸다."))
    assert any("맺음 인사" in m for m in errs("이 문서가 도움이 되길 바란다."))
    assert any("가운뎃점" in m for m in errs("수집·묶기·점수·검토를 한다"))
    assert any("구호" in m for m in errs("오늘의 화제를 한눈에!"))
    assert any("AI" in m for m in errs("AI가 분석한 오늘의 이슈"))


def test_three_items_with_middot_and_question_mark_pass():
    assert errs("수집·묶기·점수를 한다.") == []
    assert errs("규정이 바뀌었는가?") == []


def test_code_and_urls_are_skipped():
    text = "```\n혁신적! \U0001F680\n```\n명령은 `python -m ozl.issues check --strict!` 다.\n주소: https://example.com/a·b·c·d·e!\n"
    assert errs(text) == []


def test_example_mark_skips_line_and_counts():
    text = "쓰지 않는 말: 혁신적, 압도적 <!-- style: 예시 -->\n"
    e, _, skipped = SC.check_text(text)
    assert e == [] and skipped == 1


def test_internal_notation_is_info_unless_strict():
    text = "근거 등급은 T1 과 T2 만 받는다."
    e, info, _ = SC.check_text(text)
    assert e == [] and len(info) == 1
    assert any("내부 표기" in m for m in errs(text, strict_internal=True))


def test_cli_text_mode_exit_code(capsys):
    assert SC.main(["--text", "기록을 한 건 올렸다."]) == 0
    assert SC.main(["--text", "압도적 결과!"]) == 1
    out = capsys.readouterr().out
    assert "오류 2건" in out
