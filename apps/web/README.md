# OZL 웹

OZL 이슈 기록을 정적 사이트로 만든다(Astro). 화면, 자료, 색, 검색, 점검의 정본은 [DESIGN.md](DESIGN.md) 다. 빌드는 JSON 자료 폴더를 읽어 HTML 을 쓰고, 서버에서 모델을 부르지 않는다.

## 명령

```sh
cd apps/web
npm ci
npm run build:preview   # 기준 경로 /preview/ · 결과 ../../private/out/web_preview (OZL_WEB_OUT 로 바꿀 수 있다)
npm run build:public    # 기준 경로 / · 결과 dist/ (신고 연락처와 처리 절차 글이 없으면 멈춘다)
npm run preview:serve   # 미리보기 결과를 127.0.0.1:4321/preview/ 에 띄운다
node scripts/check-links.mjs <결과 폴더> <기준 경로>   # 깨진 안쪽 링크
npm run check:shape     # 예시 자료와 내보내기의 칸 이름 비교(목록만 낸다)
```

환경 변수:

| 이름 | 뜻 |
|---|---|
| `OZL_SITE_DATA` | 읽을 자료 폴더. 없으면 `sample-data/`(지어낸 예시) |
| `OZL_WEB_OUT` | 결과 폴더 |
| `OZL_REPORT_CONTACT` | 신고 연락처. `meta.json` 의 `report_contact` 보다 앞선다 |

빌드 전 검사(`scripts/guard.mjs`)의 종료 코드: 1 자료 형식, 2 신고 연락처나 처리 절차 글이 없음, 3 자료와 결과 폴더가 맞지 않음(미리보기 자료로 공개용, 시험 자료를 `dist/` 에, 미리보기 결과를 저장소 안에). 처리 절차 글 `src/content/report-procedure.md` 는 아직 없다. 그래서 지금은 `dist/` 로 가는 공개용 빌드가 늘 멈추고, 시험 자료(`meta.test: true`)를 시험 폴더로 만드는 공개용 빌드만 경고를 내고 지나간다.

guard.mjs 는 결과 폴더를 비우기 전에, 그 폴더가 저장소, 웹 폴더, 홈, 자료 폴더이거나 그것을 품으면 거부한다. 이미 있는 폴더는 비었거나 빌드가 남긴 표식 파일 `.ozl-web-out` 이 있거나 기본 폴더(`dist/`, `private/out/web_preview/`)일 때만 비운다.

공개용인지 아닌지는 `meta.json` 의 `mode`·`test` 와 이슈의 `example` 표시로만 가른다. 내보내기가 공개용 `index.json` 행에 승인 표식을 아직 주지 않아서, 이 검사가 미승인 이슈가 공개용에 실리는 것을 막는 유일한 선이다. 미리보기 내보내기에 `test: true` 를 붙여 시험 폴더로 공개용 빌드를 하면 미승인 이슈 쪽도 만들어진다(내부 칸은 지운다). 시험 폴더 밖으로 내보내지 않는다.

실제 자료는 저장소 밖에서 읽는다:

```sh
cd <저장소>
.venv/bin/python -m ozl.issues export --preview --out private/out/site_data
cd apps/web && OZL_SITE_DATA=../../private/out/site_data npm run build:preview
```

## 예시 자료 `sample-data/`

모두 지어낸 것이다(가상의 한빛시, 가람군, 다온구, 누리전자 · 주소는 `*.example` · 날짜는 2099년).

이슈 두 건은 저장소의 지어낸 예시(`tests/fixtures/issues/`)를 미리보기용으로 내보낸 것이다. 다시 만드는 명령:

```sh
cd <저장소>
T=$(mktemp -d) && mkdir -p "$T/desk" && cp -R tests/fixtures/issues "$T/desk/issues"
OZL_DESK_ROOT="$T/desk" .venv/bin/python -m ozl.issues export --preview --out "$T/desk/out"
```

- `issues/nuri-battery-recall.json` 과 `index.json` 의 그 줄은 내보낸 것 그대로다.
- `hanbit-bus-fare-400` 은 내보낸 본문을 틀로 판을 셋으로 늘렸다(1·2판은 '적자 200억' 이 확인 못 함, 2판에 정정, 3판에 판정 변경). 최신판 파일과 `r/1~3.json` 은 손으로 고친 것이다.
- 내보내기가 주지 않는 것(`days/` 의 화제 목록, 다가오는 일, 정리 전 화제, 정정이 있는 이슈, 60자 제목, 주장 0건 이슈, 키워드 겹침, 내림)은 내보내기 JSON 의 모양을 따라 손으로 쓴 것이다. 무엇을 시험하려고 넣었는지는 DESIGN.md 7절에 있다.
- `scripts/public-sample.mjs <원본> <새 폴더>` 는 예시를 공개용 모양(internal, publish_state, trend_now, 공개 제외 항목을 지움)으로 바꾼 사본을 만든다. 공개용 빌드 시험에 쓴다:

```sh
node scripts/public-sample.mjs sample-data /tmp/ozl-pub
OZL_SITE_DATA=/tmp/ozl-pub OZL_WEB_OUT=/tmp/ozl-pub-out OZL_REPORT_CONTACT=test@example.invalid npm run build:public
```

## 들어 있지 않은 것

DESIGN.md 8절의 화면 점검(Playwright), `check-real-words.mjs`, `make-year-data.mjs`, `tests/` 는 아직 만들지 않았다.
