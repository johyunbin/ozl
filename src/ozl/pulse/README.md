# OZL Pulse

매시 5분에 피드를 읽고, 최근 6시간 기사를 사건별로 묶어 신호 네 가지로 순위를 매기는 비공개 도구다. 결과는 `private/pulse/out/now.json` 에 쓰고, 웹 화면이 이 파일을 읽는다(iOS 앱은 아직 만들지 않았다). 검증 전 신호여서 공개 문서와 사이트에 옮기지 않는다.

## 웹 화면

- 서버: `python -m ozl.pulse serve` — 표준 라이브러리, 읽기 전용, `127.0.0.1:8765` 에만 연다. launchd `com.hyunbin.ozl-pulse-web` 이 상시 띄운다.
- 밖에서 보기: `tailscale serve --bg --http=8765 http://127.0.0.1:8765` 로 tailnet 안에만 연다. 주소는 `http://pulse-host.example-tailnet.ts.net:8765/`(같은 tailnet 에 로그인한 기기에서만 열린다). tailnet 에 HTTPS 인증서를 켜지 않아 HTTP 다. 끄기: `tailscale serve --http=8765 off`.
- API: `/api/now`(now.json) · `/api/topic/<id>`(지난 24시간 순위·매체 수) · `/api/health`(마지막 성공 실행과 90분 넘게 멈췄는지).
- 화면: 순위 · 기관 발표 · 급상승어 탭, 국내/해외 필터, 민감 소재 숨김. 5분마다, 그리고 탭으로 돌아올 때 다시 읽는다.

## 실행

```bash
.venv/bin/python -m ozl.pulse run          # 수집하고 now.json 을 새로 쓴다
.venv/bin/python -m ozl.pulse run --no-fetch   # 저장된 기사로만 다시 계산
.venv/bin/python -m ozl.pulse show -n 15   # 상위 주제를 표로
.venv/bin/python -m ozl.pulse prune        # 90일 지난 기록 정리
```

예약 실행은 launchd `com.hyunbin.ozl-pulse` 가 `scripts/pulse_run.sh` 를 매시 5분에 부른다. 로그는 `private/pulse/logs/`. 모델은 부르지 않는다.

## 무엇을 읽나

- 기사·기관 원문·급상승어·HN: `src/ozl/research/feeds.yaml` 의 피드 전부(OZL 일일 데스크와 같은 목록)
- 유튜브 인기 동영상(KR): YouTube Data API. 키는 환경 변수 `OZL_YOUTUBE_API_KEY`·`YOUTUBE_API_KEY` 또는 저장소 루트 `.env`(gitignore)에서 읽는다. 키가 없으면 이 신호는 "꺼짐"으로 표시한다.
- 발표 일정: `src/ozl/research/calendar.yaml`

## 신호와 점수

| 신호 | 켜지는 조건 |
|---|---|
| 보도 | 서로 다른 매체 수, 그리고 지난 1시간에 기사를 낸 매체 수를 그 전 5시간 평균과 견준 속도. 매체 한 곳으로는 켜지지 않는다 |
| 검색 | 구글 트렌드 KR/US 급상승어가 주제 낱말에 들어 있고, 급상승어에 딸린 기사 제목도 주제와 겹칠 때. 대략 검색량이 클수록 높다 |
| 커뮤니티 | 묶음에 HN 글이 있거나 유튜브 인기 동영상 제목과 낱말 2개 이상 겹칠 때 |
| 기관 | 묶음에 기관 원문이 있고 언론도 받았을 때. 언론이 받지 않은 보도자료는 순위에 넣지 않고 "기관 발표" 목록에 따로 싣는다. 오늘 발표 일정과 지표 이름이 겹칠 때도 약하게 켜진다 |

점수는 네 신호의 가중합(보도 0.35, 검색 0.30, 기관 0.25, 커뮤니티 0.10)에, 켜진 신호가 두 개 이상이면 하나당 1.5를 더한 값이다. 매체 한 곳뿐인 묶음은 1.5를 넘지 못한다. 점수는 순위를 정하는 데만 쓰고 사실 여부와는 상관이 없다.

같은 사건은 시간이 지나도 같은 번호(`topic_id`)로 잇는다. 이번 시각 묶음의 기사 하나하나를 지난 24시간 주제의 첫 기사 낱말과 견주어, 겹침이 큰 쌍부터 짝짓는다.

## 알려진 한계

- 같은 사건이 제목 낱말이 달라 두세 묶음으로 갈라지는 일이 있다(묶음 기준은 `collect.cluster` 를 그대로 쓴다).
- 급상승어 연결은 보수적이다. 딸린 기사 제목이 주제와 겹치지 않으면 연결하지 않으므로 연결 누락이 연결 오류보다 많다.
- 국내 커뮤니티는 읽지 않는다(약관과 차단 위험).
