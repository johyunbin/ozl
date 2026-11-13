# 쓰는 소스

이 쪽은 손으로 적지 않고 설정 파일과 검증 기록에서 뽑아 만듭니다(`scripts/build_sources.py`). 여기 없는 곳은 쓰지 않는 곳입니다.

## 매일 읽는 피드

피드 44개, 매체와 기관 24곳입니다. 등급은 [검증 방법](methodology.md)의 출처 등급입니다.

| 매체·기관 | 종류 | 등급 | 읽는 면 |
|---|---|---|---|
| ECB | 기관 원문 | T1 | 유럽 통화 |
| Federal Reserve | 기관 원문 | T1 | 미국 통화 |
| US Census | 기관 원문 | T1 | 미국 통계 |
| 기획재정부 | 기관 원문 | T1 | 한국 정책 |
| 한국은행 | 기관 원문 | T1 | 한국 통화 |
| Bloomberg | 언론·통신 | T3 | 증시, 경제, 테크 |
| CNBC | 언론·통신 | T3 | 종합, 경제 |
| FT | 언론·통신 | T3 | 종합, 국제 |
| Guardian | 언론·통신 | T3 | 경제, 국제 |
| NYT | 언론·통신 | T3 | 경제, 국제 |
| Nikkei Asia | 언론·통신 | T3 | 아시아 |
| SBS | 언론·통신 | T3 | 경제, 국제 |
| 경향신문 | 언론·통신 | T3 | 경제, 국제 |
| 동아일보 | 언론·통신 | T3 | 경제, 국제 |
| 매일경제 | 언론·통신 | T3 | 경제, 국제, 증시 |
| 머니투데이 | 언론·통신 | T3 | 종합 |
| 서울경제 | 언론·통신 | T3 | 경제 |
| 연합뉴스 | 언론·통신 | T3 | 경제, 국제, 산업, 증시 |
| 연합뉴스TV | 언론·통신 | T3 | 경제, 국제 |
| 조선일보 | 언론·통신 | T3 | 경제, 국제 |
| 한국경제 | 언론·통신 | T3 | 경제, 국제, 증시, 테크 |
| NBER | 연구 보고서 | T4 | 학술 |
| Google Trends KR | 검색 급상승어 | T5 | 급상승 |
| Google Trends US | 검색 급상승어 | T5 | 급상승 |

검색 급상승어와 커뮤니티 피드는 무엇이 화제인지 알아보는 단서로만 씁니다. 거기서 본 내용은 인용하지 않고 위 등급의 출처에서 다시 확인합니다.

### 지금 받지 않는 피드

주소가 응답하지 않거나, 이용 조건을 확인한 결과 받지 않기로 한 곳입니다. 조건은 출처 대장(`src/ozl/research/sources_ledger.yaml`)에 적습니다.

- BBC: 보관과 점수 이용이 금지로 확인돼 받지 않습니다
- BLS: 항목 1개짜리 요약 피드 — 발표 일정은 calendar.yaml 로 대신
- IMF: 403
- 정책브리핑: 404
- 금융위원회: 503
- 통계청: 항목 0개
- OECD: 응답 시간 초과
- WSJ: 이용 조건을 확인하지 못해 받지 않습니다
- Al Jazeera: 이용 조건을 확인하지 못해 받지 않습니다
- Reuters: 이용 조건이 수집을 막아 받지 않습니다
- AP: 이용 조건이 수집을 막아 받지 않습니다
- BEA: 이용 조건이 수집을 막아 받지 않습니다
- EIA: 이용 조건이 수집을 막아 받지 않습니다
- Eurostat: 이용 조건이 수집을 막아 받지 않습니다
- Hacker News: 이용 조건을 확인하지 못해 받지 않습니다

## 발표 일정을 확인하는 곳

물가, 고용, 금리 결정처럼 날짜가 정해진 발표는 기관의 일정 페이지를 직접 열어 확인한 날짜만 일정표에 적습니다.

- [BLS](https://www.bls.gov/schedule/news_release/cpi.htm)
- [국가데이터처](https://www.mods.go.kr/lcofNewsPln.es?mid=a50303000000)
- [한국교육과정평가원](https://www.suneung.re.kr)
- [BEA](https://www.bea.gov/news/schedule)
- [한국은행](https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?mtgSe=A&menuNo=200755)
- [Federal Reserve](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
- [ECB](https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html)
- [Bank of England](https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates)
- [Bank of Japan](https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm)

## 공개한 카드가 인용한 곳

공개한 검증 기록 34건의 출처입니다. 기록 파일에 적힌 이름 그대로 옮겼습니다.

| 기관 | 등급 | 건수 |
|---|---|---|
| U.S. Bureau of Labor Statistics | T1 | 7 |
| U.S. Energy Information Administration | T1 | 5 |
| CoreWeave, Inc. (Form 10-Q) | T1 | 3 |
| Eurostat | T1 | 3 |
| Board of Governors of the Federal Reserve System | T1 | 2 |
| Honda Motor Co., Ltd. (SEC Form 6-K) | T1 | 2 |
| U.S. Department of the Treasury, Office of Foreign Assets Control | T1 | 2 |
| Internal Revenue Service | T1 | 1 |
| International Centre for Settlement of Investment Disputes (World Bank Group) | T2 | 1 |
| International Energy Agency | T2 | 1 |
| The White House (Executive Order 14345) | T1 | 1 |
| U.S. General Accounting Office (GAO) · Honda | T1 | 1 |
| 국제통화기금(IMF) 글로벌 금융안정보고서(2026-10) | T2 | 1 |
| 댈러스 연방준비은행 Southwest Economy | T2 | 1 |
| 미 연방공개시장위원회(FOMC) | T1 | 1 |
| 세인트루이스 연방준비은행 FRED (원자료 BLS) | T2 | 1 |
| 캔자스시티 연방준비은행 경제 회보 | T2 | 1 |

예전에 이 자리에 있던 소스 조사 문서는 항목을 하나씩 확인하기 전의 초안이어서 내렸습니다.
