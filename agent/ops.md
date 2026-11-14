# 운영 화면, 화제 엔진, 매시 수집

후보를 모으고 점수를 매기는 매시 수집, 그 결과로 후보 목록을 만드는 화제 엔진, 사용자가 고르고 승인하는 운영 화면의 규칙이다. 공통 규칙은 `CLAUDE.md` 에 있다.

## 지금 도는 것과 꺼진 것
- 돈다: 매시 수집 launchd `com.hyunbin.ozl-pulse`(매시 5분, `scripts/pulse_run.sh` 가 `python -m ozl.pulse run` 뒤에 `python -m ozl.signals run` 을 부른다. 모델 호출 없음)와 운영 서버 launchd `com.hyunbin.ozl-pulse-web`(`127.0.0.1:8765`).
- 꺼져 있다: 모델이 도는 예약 루틴(`ozl-am`, `ozl-pm`, `ozl-weekly`), [만들기] 실행기, 커뮤니티 인기글 수집, 유튜브 인기 영상 신호.
- 다른 예약 실행(Trading 의 것, `multi-model`, 그 밖의 `com.hyunbin.*`)은 건드리지 않는다.

## 수집이 읽는 파일의 저장 금지 시간
매시 :03 ~ :08 에는 아래 파일을 저장하지 않는다(반쯤 쓴 파일을 수집이 읽지 않게).
- 코드: `src/ozl/pulse/`, `src/ozl/signals/`, `src/ozl/research/`(수집이 부르는 모듈), `scripts/pulse_run.sh`
- 설정과 자료: `src/ozl/research/feeds.yaml`, `calendar.yaml`, `sources_ledger.yaml`, `src/ozl/signals/data/`
- 수집 자료: `private/pulse/` 아래 DB 와 출력(`pulse.db`, `engine.db`, `out/`)

## 운영 화면 (`src/ozl/ops/`)
- `python -m ozl.ops serve` 가 고르기(`/pick`), 게시 승인(`/approve`), 미리보기(`/preview/`), 운영 첫 화면(`/ops`)과 iOS 앱이 쓰는 옛 주소(`/`, `/deck`, `/api/*`)를 낸다. 서버는 `127.0.0.1`(또는 `::1`)에만 묶이고, 이 기기 밖에서는 `tailscale serve` 를 거쳐 닿는다. 사설망 이름은 문서에 적지 않는다.
- 운영 서버는 launchd 환경에서 돈다(PATH 가 터미널과 다르다). 서버가 부르는 바깥 도구는 PATH 에만 기대지 않게 짠다(`capture.find_pdftotext()` 가 그 예다). 이슈를 '게시 대기'로 올린 뒤에는 `/approve` 를 열어 그 건의 "점검" 줄을 본다. 터미널의 검사 통과가 승인 화면의 통과를 뜻하지 않는다. 코드를 고친 뒤에는 서버를 다시 띄워야 화면에 반영된다(`launchctl kickstart -k gui/$(id -u)/com.hyunbin.ozl-pulse-web`).
- 쓰기 요청(POST)은 로그인(토큰), Host와 Origin 검사, 요청 토큰, 본문 크기와 종류 검사를 모두 통과해야 한다. 이 기기 주소가 아닌 이름으로 들어온 읽기도 로그인이 필요하다. 설계와 남은 위험은 `private/plan/ops_spec_20261114.md` 3절, 9절, 16절, 코드가 생긴 뒤에는 코드가 정본이다.
- 로그인 토큰은 `private/ops/token` 에 있다. `python -m ozl.ops token --show` 만 토큰을 찍는다. 토큰을 문서, 로그, 외부 모델, 커밋에 넣지 않는다.
- 만들기 대기열(`<자료 루트>/ops/make_queue.json`)은 손으로 고치지 않는다. 늘 `python -m ozl.ops queue list|show|set` 으로 읽고 바꾼다(서버와 같은 잠금을 쓴다).
- 실행기 `python -m ozl.ops runner --once [--dry-run]` 는 대기열에서 한 건을 꺼내 화면 없는 Claude Code(Opus)로 `/ozl make` 를 띄운다. 설정 `<자료 루트>/ops/runner.json` 이 없거나 `enabled` 가 참이 아니면 돌지 않는다. 켜는 것은 사용자가 정한다. 처음 켤 때는 `--dry-run` 으로 명령을 보고 한 건을 지켜본다.
- 실행기가 띄운 세션은 Codex 를 부르지 않고, 승인, 철회, 공개 내보내기, `ozl.ops token`, `private/ops/` 읽기, 발행 목록과 번호 대장과 고정 사본과 운영 파일의 직접 쓰기가 막혀 있다. 막힌 것을 돌아가지 않는다.

## 화제 엔진 (`src/ozl/signals/`)
- 명령: `python -m ozl.signals run [--asof] [--out]`(밀린 매시 수집 시각을 따라잡아 계산하고 `board.json` 을 쓴다), `replay --from --to [--db] [--step runs|daily] [--reset]`(기간을 처음부터 다시 계산), `board`(계산 없이 `board.json` 만 다시 쓴다), `explain <이슈 번호>`(점수 내역).
- 수집 DB(`private/pulse/pulse.db`)는 읽기만 한다. 엔진이 쓰는 저장소는 `private/pulse/engine.db` 하나이고, 후보 목록은 `private/pulse/out/board.json` 이다.
- `replay` 는 기본으로 새 파일에 쓴다. 라이브 `engine.db` 를 바꾸려면 `--db private/pulse/engine.db --reset` 을 함께 줘야 하고, 그때 같은 폴더에 백업이 남는다.
- 점수는 후보의 순서를 정하는 데만 쓴다. 사실 여부와는 상관이 없다.

## 출처
- 피드 = `src/ozl/research/feeds.yaml`, 발표 일정 = `calendar.yaml`. 일정은 **공식 일정 페이지를 직접 열어 확인한 날짜만** 적는다(35일 지나면 재확인 표시가 뜬다).
- 출처마다 수집과 점수 사용의 허용 여부는 출처 대장 `src/ozl/research/sources_ledger.yaml` 에 적고, 수집 코드는 대장에서 허용이 아닌 곳에 요청하지 않는다.
- `docs/sources.md` 는 `scripts/build_sources.py` 로 만든다. 피드, 일정, 출처 대장을 고치면 다시 돌린다. 쓰지 않는 도구와 소스는 적지 않는다.
