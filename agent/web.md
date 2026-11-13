# 웹과 iOS 앱

이슈 기록을 독자에게 보이는 정적 사이트(`apps/web`)와, 운영 서버를 읽는 iOS 앱(`apps/ios`)의 규칙이다. 공통 규칙은 `CLAUDE.md` 에 있다.

## 웹 (`apps/web`)
- 정본: 명령과 환경 변수는 `apps/web/README.md`, 화면과 자료와 점검은 `apps/web/DESIGN.md`. 빌드는 JSON 자료 폴더를 읽어 HTML 을 쓰고, 서버에서 모델을 부르지 않는다.
- 빌드 명령(`apps/web` 에서): `npm run build:preview`(기준 경로 `/preview/`, 결과 `private/out/web_preview`), `npm run build:public`(기준 경로 `/`, 결과 `dist/`), `npm run preview:serve`(`127.0.0.1:4321/preview/`).
- 미리보기와 공개용의 차이: 미리보기는 모든 쪽이 noindex 이고 운영 정보(작업 상태, 검사 경고, 공개에서 빠지는 항목의 수와 까닭)를 쪽 위의 접힌 상자 한 곳에 모은다. 공개용은 그 정보를 출력하지 않는다. 공개용 빌드는 신고 연락처와 처리 절차 글(`src/content/report-procedure.md`)이 없으면 멈춘다. 2026-11-14 기준 그 글이 없어 `dist/` 로 가는 공개용 빌드는 멈춘다(신고 연락처를 사용자가 정한 뒤에 쓴다).
- 공개용인지 아닌지는 `meta.json` 의 `mode`, `test` 와 이슈의 `example` 표시로만 가른다. 미리보기 자료를 `test: true` 로 공개용 빌드한 결과는 시험 폴더 밖으로 내보내지 않는다.
- 실제 자료는 저장소 밖에서 읽는다: `python -m ozl.issues export --preview --out private/out/site_data` 를 만든 뒤 `OZL_SITE_DATA` 로 준다. 공개용 내보내기(`export --public`)는 사용자가 말했을 때만 한다.
- 검사: 두 빌드 모두 끝에 `scripts/check-html.mjs` 가 실행되는 인라인 스크립트, 인라인 이벤트 속성, `javascript:` 주소가 0개인지 본다. 그 밖에 `node scripts/check-links.mjs <결과 폴더> <기준 경로>`, `npm run check:shape`, `npm run check:offline`, `npm run check:csp`, `node checks/visual.mjs`. 운영 서버가 미리보기를 운영 화면과 같은 출처에서 내주므로, 빌드 결과에 실행되는 인라인 스크립트를 두지 않는다.
- 카드 그림(`npm run cards`, 1080×1350)은 미리보기 빌드에서 찍고 게시하지 않는다. 그림 전용 화면은 공개용 빌드에 만들지 않는다.
- 예시 자료 `apps/web/sample-data/` 는 모두 지어낸 것이다(가상의 지역과 회사, 주소는 `*.example`, 날짜는 2099년). 실제 이슈의 내용을 예시 자료, 화면 점검 사진, 테스트에 넣지 않는다. 화면 점검 결과는 `private/out/screens/` 에 둔다.

## iOS 앱 (`apps/ios/OZLPulse`)
- 표시 이름은 OZL 이다. 번들 식별자(`local.ozl.pulse`), 프로젝트와 폴더 이름(`OZLPulse`)은 그대로 둔다. 안쪽 이름은 웹과 운영 화면이 동작하는 것을 확인한 뒤 따로 옮긴다.
- 앱은 운영 서버의 옛 주소(`/`, `/deck`, `/api/*`)를 읽는다. 그래서 운영 서버는 그 주소를 로그인 없이 같은 모양으로 낸다.
- 이슈 탭(`IssuesView.swift`)은 운영 서버가 `/preview/` 아래에 내는 미리보기 사이트를 웹뷰로 연다.
- 서버 주소는 사용자가 앱 설정에 넣고 기기에만 저장된다(`@AppStorage("serverURL")`). 코드와 문서에는 실제 사설망 이름을 적지 않고 자리표(`기기이름.tailnet.ts.net`)나 `127.0.0.1:8765` 만 쓴다.
