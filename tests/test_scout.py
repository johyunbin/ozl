"""소재 발굴 쪽 규칙(민감 기준 표시기)의 회귀 테스트. 예시 문장은 전부 지어낸 것이다(실제 기사 제목 아님)."""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ozl.research import sensitive  # noqa: E402

LEVELS = [
    # 해외 정치는 GREEN — 표지가 낱말 바로 앞에 없어도 같은 글에 있고 국내 표지가 없으면 푼다
    ("가상국 증시 급등, 민주당의 상원 장악 전망에 기술주 강세", "GREEN"),
    ("프랑스 중도 연합 지지율 1위…대선 판세 요동", "GREEN"),
    ("美하원, 재무장관 탄핵소추안 표결 연기", "GREEN"),
    # '민주당'은 나라 이름만으로는 풀지 않는다
    ("민주당, 미국 관세 협상 결과 두고 정부 비판", "RED"),
    ("국민의힘·민주당, 미국 반도체 보조금 대응 놓고 여야 공방", "RED"),
    # 지명·이름의 일부는 정치 낱말이 아니다
    ("가상군 용산리 마을회관 준공", "GREEN"),
    ("전경선 시의원, 버스 노선 개편 간담회 참석", "GREEN"),
    ("당내 경선 일정 확정…후보 등록 시작", "RED"),
    # '피해자' 단독은 RED 가 아니다. 강력 범죄 낱말과 함께일 때만
    ("보이스피싱 피해자 생계비 지원 기금 조성", "GREEN"),
    ("가상시 흉기 난동…피해자 2명 병원 이송", "RED"),
    ("영국 수도서 흉기 난동…경찰 수사", "YELLOW"),
    # 사법: 인물이 있으면 RED, 통계·제도면 YELLOW, 해외면 YELLOW
    ("전 대표 구속영장 청구… 1심 선고는 다음 달", "RED"),
    ("부정청약 354건 적발…징역형 선고 비율 늘어", "YELLOW"),
    ("트럼프 측근 1심 유죄…항소 방침", "YELLOW"),
    # 더한 갈래
    ("가상 배우 불륜 의혹에 소속사 해명", "RED"),
    ("Fictional studio head denies rumored affair with a staff member", "RED"),
    ("이혼율 10년 만에 최저…혼인 건수는 반등", "GREEN"),
    ("가상 재벌 빈소에 조문 행렬", "RED"),
    ("혈압약 복용 뒤 어지럼 보고 늘어", "GREEN"),
    ("중수청 출범 앞두고 검찰개혁 공방 격화", "RED"),
    ("자살 예방 상담전화, 채무 상담과 연계", "YELLOW"),
    ("스마트 초인종 써 보니…사생활 침해 우려는 숙제", "GREEN"),
    # 정부 발언의 정책 내용, 선거 제도·관리, 젠더 갈등은 YELLOW
    ("李대통령 \"노숙인 지원금 정보 잘못 알려져\"", "YELLOW"),
    ("이란 대통령 \"전쟁도 평화도 아닌 상황 끝내야\"", "GREEN"),
    ("사전투표율 역대 최고…선관위 투표용지 관리 강화", "YELLOW"),
    ("젠더 갈등, 청년 남녀 투표 성향 차이로 본 통계", "YELLOW"),
    ("게시판에 '김치녀' 표현 확산…플랫폼 제재", "RED"),
]

# 2026-11-13 반박 검토(다른 에이전트·Codex)에서 나온 반례. 기대값은 확정 기준이고, 문장은 전부 지어낸 것이다.
REVIEW = [
    # 해외 낱말이 뒤에 붙었다고 국내 형사 사건이 풀리지 않는다(해외 표지는 그 낱말보다 앞에 있어야 한다)
    ("가상 전 대표 1심 선고…미국 언론 주목", "RED"),
    ("가수 김모씨 성폭행 혐의 송치…일본 팬 충격", "RED"),
    ("강남 아파트 흉기 난동…미국 국적 용의자", "RED"),
    ("서울 김가상 씨 구속영장 청구…미국 투자금 횡령 혐의", "RED"),
    ("김영국 씨 구속영장 청구", "RED"),                      # 이름 속 '영국'
    ("서울 김가상 씨 사기 혐의로 경찰 수사", "RED"),
    ("서울 배우 가상민 구속영장 청구", "RED"),
    ("가수 김씨 마약 투약 혐의 검찰 송치", "RED"),
    ("광주 아파트 방화 40대 남성 구속 송치", "RED"),
    ("미국 법원, 가상 전 의원에 징역 4개월 선고", "YELLOW"),
    # 민사 소송, 범죄 통계는 RED 가 아니다
    ("가상전자 대표, 특허 손해배상 소송 1심 승소", "YELLOW"),
    ("국내 살인 범죄 통계, 발생률 10년째 감소", "YELLOW"),
    ("부동산감독 강화…부정청약 적발 뒤 징역형 비율 늘어", "YELLOW"),
    # 국내 표지가 있으면 해외 낱말이 있어도 국내 정치다
    ("대선 출마 선언한 경기지사, 일본 수출규제 비판", "RED"),
    ("민주당 대표, 미국 상원의원 만나 관세 논의", "RED"),
    ("미국 방문한 민주당(한국), 관세 협상 결과 두고 정부 비판", "RED"),
    ("국내 정치의 향방을 가를 대선 지지율 조사…미국 금리는 변수", "RED"),
    ("어린이집 하원 시간 변경…민주당 공약 논란", "RED"),      # '하원'은 의회 용례일 때만 해외 표지다
    ("김하원 시의원 출마 선언", "RED"),
    ("흥미 끄는 여당 전당대회", "RED"),
    ("원칙이란 여당 대표의 말", "RED"),
    ("與野 예산 협상 결렬", "RED"),
    ("국힘·민주 공방 격화", "RED"),
    ("국내 총선 여론조사, 후보 지지율 박빙…개표는 내일", "RED"),   # 선거 관리 낱말이 판세 보도를 낮추지 않는다
    ("국내 선관위, 투표용지 관리 강화…미국 사례 참고", "YELLOW"),
    # 해외의 '여당·국회·당대표'는 국내 표지가 아니다
    ("프랑스 집권 여당, 대선 후보 지지율 상승", "GREEN"),
    ("상원 장악에 성공한 미국 민주당 당대표 지지율 상승에 증시 급등", "GREEN"),
    ("일본 국회 해산…다음 달 총선", "GREEN"),
    ("호주 연방 선거 앞두고 지지율 조사", "GREEN"),
    ("인도 증시, 전국 총선 결과 앞두고 강세", "GREEN"),
    ("싱가포르 총선 여당 압승", "GREEN"),
    # 정부·대통령실 발표는 YELLOW, 입법 절차도 YELLOW
    ("대통령실, 수출 기업 지원 확대 방안 발표", "YELLOW"),
    ("청와대, 반도체 연구개발 지원 계획 발표", "YELLOW"),
    ("이재명 대통령, 미국 관세 협상 결과 보고받아", "YELLOW"),
    ("코인 과세 3년 유예 여야 잠정 합의", "YELLOW"),
    # 사망자·유족
    ("가상시 공장 화재로 노동자 2명 사망…유족 오열", "RED"),
    ("가상 참사 희생자 추모식", "RED"),
    ("유족, 마지막 편지 공개", "YELLOW"),
    ("유족연금 지급률 조정안 발표", "GREEN"),
    ("故가상인 9년 전 사진 공개", "RED"),
    ("고(故) 김씨 발인", "RED"),
    # 낱말 속 글자와 비유 표현
    ("한남동 상가 임대료 하락", "GREEN"),
    ("한남3구역 재개발 시공사 선정", "GREEN"),
    ("국내 최대선사, 신규 항로 개설", "GREEN"),
    ("살인물가에 소비심리 위축", "GREEN"),
    ("협력사와 결별한 기업, 자체 생산 확대", "GREEN"),
    ("전기차 내연기관 대체 속도 둔화", "GREEN"),
    ("국내 이혼 소송 통계 발표", "GREEN"),
    ("반도체 수요 폭발…수출 증가", "GREEN"),
    ("주가 폭락에 개미 극단적 선택 늘어", "YELLOW"),
    # 수사기관 이름만 나오면 YELLOW, 개편 다툼이면 RED
    ("증선위, 미공개정보 이용 사건 중수청에 통보", "YELLOW"),
    ("중대범죄수사청 사건 선별 기준 두고 경찰 불만", "RED"),
    ("2차 세계대전 학살 기록 공개한 독일 문서고", "GREEN"),
    ("미대선 앞두고 달러 강세", "GREEN"),
    ("조기대선 가능성에 정치 테마주 급등", "RED"),
    ("한미 정상회담 뒤 지지율 반등", "RED"),
    ("일본서 한국인 관광객 폭행 피해", "RED"),
    ("가상화학 대표이사 횡령 혐의 구속기소", "RED"),
    ("담합 혐의 4개사 과징금", "YELLOW"),
    ("가상 그룹 내연기관 부문 매각", "GREEN"),
    # 2차 검토(Codex)의 반례
    ("서울 김가상 씨 사기 사건 기소…내일 재판 시작", "RED"),
    ("김상원 의원 구속영장 청구", "RED"),                    # 이름 속 '상원'
    ("김하원 의원, 대선 출마 선언", "RED"),
    ("국내 민주당, 미국 공화당과 면담", "RED"),
    ("미국 투자금 횡령한 김가상 씨, 한국 경찰에 사기 혐의로 입건", "RED"),
    ("국내 대선 개표 90%…김가상 후보 당선 확실", "RED"),
    ("김가상 씨 저작권법 위반 형사재판 1심 선고", "RED"),
    ("김가상 씨 횡령 사건 항소심…피해자 손해배상 청구", "RED"),
    ("서울 공장 화재 사망자 김가상 씨의 마지막 편지 공개", "RED"),
    ("서울 참사 유족 보상 요구하며 오열", "RED"),
    ("국내 차기총선 결과에 정치 테마주 요동", "RED"),
    ("중수청, 보이스피싱 피해자 지원센터 신설", "YELLOW"),
    ("산재 사망 통계 발표…건설업이 절반", "YELLOW"),
    ("Actor Kim Ga-sang charged with fraud in Seoul", "RED"),
    # 영문
    ("Korea ruling party wins by-election", "RED"),
    ("South Korea elections too close to call", "RED"),
    ("Actor Kim Ga-sang arrested in Seoul for fraud", "RED"),
    ("South Korean stocks rise after US election results", "GREEN"),
    ("US senator John Example indicted on bribery charges", "YELLOW"),
    ("Central bank calls debt dispute a purely financial affair", "GREEN"),
    ("Bus crash kills three in Seoul; bereaved families demand answers", "RED"),
]


@pytest.mark.parametrize("text,level", REVIEW)
def test_sensitive_levels_from_adversarial_review(text, level):
    assert sensitive.classify(text)["level"] == level, sensitive.classify(text)


def test_context_from_other_titles_never_releases_a_criminal_case():
    """묶음의 다른 제목에 해외 낱말이 있어도 형사 사건은 풀리지 않는다. 정치 낱말은 국내 표지가 없을 때만 풀린다."""
    assert sensitive.classify("서울 지하철 성추행 피의자 검거", "미국 지하철 범죄 통계")["level"] == "RED"
    assert sensitive.classify("지방선거 서울시장 여론조사 박빙", "미국 중간선거 결과")["level"] == "RED"
    assert sensitive.classify("민주당 압승…서울시장 탈환", "미국 중간선거 상원 개표")["level"] == "RED"


def test_summary_only_hit_is_yellow_not_red():
    """RED 는 제목에 근거가 있을 때만. 요약에만 민감 낱말이 있으면 YELLOW 로 표시하고 사유에 적는다."""
    r = sensitive.classify_item("가상 기업 다음 주 상장", "한편 다른 가상 배우의 불륜 의혹 보도도 이어졌다")
    assert r["level"] == "YELLOW" and "요약에만" in r["reasons"][0]
    assert sensitive.classify_item("가상 배우 불륜 의혹", "소속사가 해명했다")["level"] == "RED"
    assert sensitive.classify_item("가상 지수 강보합 마감", "")["level"] == "GREEN"
    # 요약의 해외 표지는 제목의 정치 낱말을 푸는 근거가 된다
    assert sensitive.classify_item("민주당 압승 전망에 가상 지수 4% 급등", "중간선거 개표 초반 상원 판세")["level"] == "GREEN"


@pytest.mark.parametrize("text,level", LEVELS)
def test_sensitive_levels_after_2026_11_13_rules(text, level):
    assert sensitive.classify(text)["level"] == level, sensitive.classify(text)


def test_cluster_context_resolves_foreign_party():
    """해외 표지가 같은 묶음의 다른 제목에만 있어도 '민주당'을 해외로 푼다. 국내 표지가 묶음에 있으면 풀지 않는다."""
    item = "민주당 압승 전망에 가상 지수 4% 급등"
    assert sensitive.classify(item)["level"] == "RED"
    assert sensitive.classify(item, "중간선거 개표 초반 상원 판세")["level"] == "GREEN"
    assert sensitive.classify(item, "중간선거 개표 초반 상원 판세 · 국회 여야 반응")["level"] == "RED"
