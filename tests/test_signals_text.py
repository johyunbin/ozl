"""화제 엔진: 주소 정규화, 제목 정규화, 낱말과 고유명사(설계 §2-1, §3). 제목은 전부 지어낸 것."""
import pytest

from ozl.signals import config, text
from ozl.signals.urls import canon_url, is_article_url

import test_signals_kit as K


@pytest.mark.parametrize("raw, want", [
    ("https://www.example.test/a/1?utm_source=x&utm_medium=y", "https://example.test/a/1"),
    ("http://m.example.test/a/1/", "https://example.test/a/1"),
    ("https://mobile.example.test/a/1#top", "https://example.test/a/1"),
    ("https://news.example.test/a?oc=5&mod=rss&traffic_source=rss&at_medium=x&at_campaign=y", "https://news.example.test/a"),
    ("https://news.example.test/v?news_id=N100&plink=RSS&cooper=RSS", "https://news.example.test/v?news_id=N100"),
    ("https://gov.example.test/view?nttId=7&fbclid=z&gclid=q&ref=home", "https://gov.example.test/view?nttId=7"),
    ("https://a.example.test/p?b=2&a=1", "https://a.example.test/p?a=1&b=2"),
    ("HTTPS://WWW.Example.TEST/", "https://example.test/"),
    ("ftp://example.test/a", None),
    ("", None),
    (None, None),
])
def test_canon_url(raw, want):
    assert canon_url(raw) == want


def test_article_url_excludes_trend_feed_and_root():
    assert not is_article_url(canon_url("https://trends.google.com/trending/rss?geo=KR"))
    assert not is_article_url(canon_url("https://example.test/"))
    assert is_article_url(canon_url("https://example.test/a/1"))


def test_norm_title_heads_tails_hanja():
    assert text.norm_title("[속보][단독] 美 가람전자, 공장 신설(종합2보)") == "미국가람전자공장신설"
    assert text.norm_title("中·日 정상 회동 (1보)") == "중국일본정상회동"
    assert text.strip_head("[포토] 北 발사") == "북한 발사"


def test_norm_summary_strips_wire_head():
    s = "(서울=연합뉴스) 김가상 기자 = 가람전자가 공장을 짓는다."
    assert text.norm_summary(s) == "가람전자가공장을짓는다"
    assert len(text.norm_summary("가" * 400)) == config.SUMMARY_HEAD


def test_dice():
    assert text.dice("가나다", "가나다") == 1.0
    assert text.dice("가나", "다라") == 0.0
    assert text.dice("", "가나") == 0.0
    assert abs(text.dice("가나다라", "가나다마") - 2 * 2 / 6) < 1e-9


def test_analyze_ko_names_terms_broad_alias():
    r = text.analyze("한빛전자, 가람시에 2조원 들여 배터리 공장 신설", "ko")
    assert r["entities"] == ["가람시", "한빛전자"]
    assert "배터리" in r["terms"] and "공장" in r["terms"]
    assert "연준" in text.analyze("美 연준 금리 동결", "ko")["entities"]     # 별칭 '미국 연준' → 연준
    r = text.analyze("美 정부, 켐텍화학 제재…서울 증시 출렁", "ko")
    assert "미국" not in r["entities"] and "미국" in r["terms"]        # 넓은 이름은 terms 로
    assert "서울" not in r["entities"] and "켐텍화학" in r["entities"]
    r = text.analyze("[속보] 투자 발표 확대", "ko")
    assert not {"속보", "투자", "발표", "확대"} & set(r["terms"])        # 흔한 낱말


def test_analyze_person_and_indirect():
    r = text.analyze("배아름 회장, 장남에 지분 증여", "ko")
    assert "배아름" in r["entities"] and r["person"]
    r = text.analyze("가람시 공무원 발언 SNS서 화제", "ko")
    assert r["indirect"]
    assert not text.analyze("가람시 공장 증설", "ko")["indirect"]


def test_analyze_unknown_name_at_title_start():
    # Kiwi 는 문장 첫머리의 모르는 이름을 NNG 로 내기도 한다. 사전에 없는 명사(oov)도 이름 후보로 본다.
    assert "켐텍화학" in text.analyze("켐텍화학 공장 화재…주민 대피", "ko")["entities"]
    assert "켐텍화학" in text.analyze("주민 대피시킨 켐텍화학 공장 화재", "ko")["entities"]


def test_analyze_en_sentence_case_vs_title_case():
    r = text.analyze("Hanbit Electronics Shares Fall After Recall", "en")
    assert r["entities"] == ["Hanbit Electronics"]
    r2 = text.analyze("Hanbit Electronics shares fall after recall", "en")
    assert r2["entities"] == ["Hanbit Electronics"]


def test_gold_fixture_names_are_entities():
    """정답 60쌍의 가상 이름이 analyze() 에서 entity 로 나온다(못 잡는 이름은 바꿔 두었다)."""
    misses = []
    for p in K.load_gold():
        for side in ("a", "b"):
            arts = [p[side]] + [s for s in p.get("support") or [] if s["for"] == side]
            for a in arts:
                ents = set(text.analyze(a["title"], "ko")["entities"])
                for n in p.get("names") or []:
                    if n in a["title"] and n not in ents:
                        misses.append((p["id"], n, a["title"]))
    assert misses == []


def test_dict_version_changes_with_role_flag(monkeypatch):
    # 기본값이 켜짐(True)으로 바뀌어(2026-11-14) 반대값으로 바꿔 본다. 값이 어느 쪽이든 판이 달라져야 한다.
    v1 = config.dict_version()
    monkeypatch.setattr(config, "ROLE_WORDS_NOT_TERMS", not config.ROLE_WORDS_NOT_TERMS)
    assert config.dict_version() != v1
