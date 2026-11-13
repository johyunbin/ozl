# OZL 웹

OZL 이슈 기록을 정적 사이트로 만든다(Astro). 화면, 자료, 색, 검색, 점검의 정본은 [DESIGN.md](DESIGN.md) 다. 빌드는 JSON 자료 폴더를 읽어 HTML 을 쓰고, 서버에서 모델을 부르지 않는다.

## 명령

```sh
cd apps/web
npm ci
npm run build:preview   # 기준 경로 /preview/ · 결과 ../../private/out/web_preview (OZL_WEB_OUT 로 바꿀 수 있다). 끝에 HTML 안전 검사
npm run build:public    # 기준 경로 / · 결과 dist/ (신고 연락처와 처리 절차 글이 없으면 멈춘다)
npm run preview:serve   # 미리보기 결과를 127.0.0.1:4321/preview/ 에 띄운다
node scripts/check-links.mjs <결과 폴더> <기준 경로>   # 깨진 안쪽 링크
npm run check:shape     # 예시 자료와 내보내기의 칸 이름 비교(목록만 낸다)
npm run cards           # 카드 그림(아래 절)
npm run check:offline   # 서비스 워커 저장분과 내림(아래 절)
npm run check:csp       # 공개용 빌드의 콘텐츠 보안 정책(아래 절)
node checks/visual.mjs  # 화면 점검(카드 화면 포함). 결과 private/out/screens/web_<타임코드>/
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

## 넘겨 보는 카드와 카드 그림

이슈 화면마다 `<기준>i/<slug>/cards/` 에 세로 4:5 카드가 있다(표지, 이번 판, 주장마다 한 장, 아직 모르는 것, 출처와 정정). 이슈 화면 위쪽의 "카드" 링크로 간다. 스크립트가 있으면 카드 띠 안에서 옆으로 넘기고(손가락, 이전·다음 단추, 좌우 화살표 키, "3 / 11" 표시), 없으면 세로로 이어 읽는다. 글이 길면 글자를 줄이지 않고 "(이어서)" 장을 더한다. 넘침은 빌드 때 글자 수로 정한다(`src/lib/cards.ts`). 장의 차례와 크기 규칙은 DESIGN.md 1-14, 4-17 에 있다.

카드 그림(1080×1350 PNG, 인스타그램 세로 규격)은 미리보기 빌드의 그림 전용 화면(`<기준>i/<slug>/cards/print/`)을 Playwright 로 찍어 만든다. 게시는 하지 않는다.

```sh
npm run build:preview
npm run cards                                             # 결과 폴더 기본값의 모든 이슈
npm run cards -- --build <결과 폴더> --out <그림 폴더> <slug> ...
```

- 그림 자리: `<그림 폴더>/<slug>/r<판>/NN.png` 와 `cards.json`(장마다 파일 이름, 실린 글과 그 글이 자료에서 왔는지 화면이 붙인 머리인지, 판정, 출처, 판 번호). 그림 폴더 기본값은 `private/out/cards/`, `OZL_CARDS_OUT` 이나 `--out` 으로 바꾼다. 결과 폴더는 `OZL_WEB_OUT` 이나 `--build`, 대조할 자료는 `OZL_SITE_DATA` 나 `--data`.
- 찍은 뒤 스스로 확인한다: 파일 크기 0 아님과 1080×1350, 카드 안에서 넘친 상자 0개, 그림 장 수와 카드 화면 장 수가 같음, 자료에서 온 문장과 판정, 출처, 판 번호, 판정 집계가 그 판의 사본(`issues/<slug>/r/<판>.json`, 판 사본이 없는 작업본은 최신 본문 — `cards.json` 의 `copy: "latest"`)과 같음. 하나라도 어긋나면 종료 코드 1.
- 고정 주소는 사이트 주소를 모르면 경로만 적는다. `OZL_SITE_ORIGIN=https://…` 를 주면 앞에 붙인다.
- 그림 전용 화면은 공개용 빌드에 만들지 않는다. 공개 사이트에 같은 내용의 쪽을 하나 더 두지 않고, 무료 호스팅의 파일 수를 늘리지 않으려는 것이다. 미리보기 빌드는 모든 쪽이 noindex 이고 robots.txt 가 전부 막으며, 그림 전용 화면에는 검색 색인 표시(`data-pagefind-body`)가 없다.

## 홈 화면 추가와 최근 판 저장

`manifest.webmanifest`(이름 OZL, 글자 로고 아이콘 SVG·PNG 192·512)와 서비스 워커 `sw.js` 하나를 기준 경로 바로 밑에 둔다. 미리보기(`/preview/`)에서는 scope 가 `/preview/` 다. 아이콘 PNG 는 `npm run icons` 가 `public/icons/icon.svg` 에서 다시 그린다.

저장 규칙(DESIGN.md 4-18):
- 화면 틀(CSS, 글꼴, 스크립트, 아이콘)은 캐시 우선. 문서(HTML)와 자료(JSON)는 네트워크 우선이고, 연결이 없을 때만 저장분을 "연결이 없어 저장된 판을 보여 준다(저장 시각 …)" 띠와 함께 보여 준다.
- 저장하는 문서는 이슈 화면(최신판, 카드, 고정판)뿐이고 최근에 연 이슈 20건까지다. 첫 화면, 날짜 쪽, 키워드 쪽, 검색 결과와 색인, 자료 JSON 은 저장하지 않는다.
- 연결될 때마다 `offline.json`(지금 있는 이슈의 주소, 최신판과 고정판 번호, 내린 판)을 받아, 거기 없는 이슈와 판, 최신판 번호가 바뀐 최신판·카드의 저장분을 지운다. 캐시 이름에 빌드 식별자(자료 JSON 전체의 해시, `OZL_BUILD_ID` 로 바꿀 수 있다)를 넣어, 자료가 바뀐 빌드가 오면 옛 캐시를 버린다.

내린 글이 사라지는 범위와 남는 범위(`npm run check:offline` 으로 확인):
- 사라진다: 기기가 다시 연결되어 사이트의 쪽을 하나라도 열면(또는 홈 화면 앱을 켜면) 내린 이슈의 최신판, 카드, 고정판 저장분과 저장 목록의 그 줄. 정정이나 판정 변경으로 최신판 번호가 바뀐 이슈의 옛 최신판·카드 저장분도 지운다(다시 열면 새 판이 저장된다).
- 남는다: 연결이 끊긴 기기는 다시 연결될 때까지 내린 글의 저장분을 볼 수 있다. 사이트를 다시 열지 않은 기기에서는 서비스 워커가 깨어나지 않아 지울 수 없다. 브라우저가 따로 저장한 것(화면 갈무리, 읽기 목록, 공유한 그림, 내려받은 카드 그림, 브라우저의 일반 HTTP 캐시와 뒤로 가기 캐시)은 서비스 워커가 지울 수 없다.

## 화면에서 운영 정보를 빼는 방식

공개용 빌드에는 작업 상태(검토 대기, 작성 중), 검사 경고, 수집 실패, 정리 전 빈 항목, 공개에서 빠지는 항목을 출력하지 않는다. 미리보기 빌드에서는 본문에 섞지 않고 쪽 맨 위(미리보기 띠 밑)의 접힌 "운영 정보" 상자 한 곳에 모은다(`src/lib/ops.ts`, `src/components/OpsBox.astro`). 공개에서 빠지는 항목은 미리보기에서도 제목과 출처를 그리지 않고 "공개에서 빠지는 항목(사생활) 1건"처럼 수와 까닭만 적는다.

## 스크립트와 주소의 안전

운영 서버가 미리보기를 운영 화면과 같은 출처에서 내주므로, 빌드 결과에 실행되는 인라인 스크립트를 두지 않는다(DESIGN.md 6-1).
- `astro.config.mjs` 가 작은 스크립트의 인라인을 끈다(`vite.build.assetsInlineLimit: 0`). 글꼴 목록을 늦게 붙이는 일은 `src/scripts/fonts.ts` 가 한다.
- 두 빌드 모두 마지막에 `scripts/check-html.mjs` 가 실행되는 인라인 `<script>`, 인라인 이벤트 속성(`on…=`), `javascript:` 주소가 0개인지 보고, 하나라도 있으면 빌드가 실패한다. 공개용이면 쪽마다 콘텐츠 보안 정책 meta 가 하나씩 있는지도 본다.
- 공개용 빌드의 콘텐츠 보안 정책은 `src/layouts/Base.astro` 의 `CSP` 다. 검색 색인의 WebAssembly 때문에 `'wasm-unsafe-eval'`, 스크립트가 꺼졌을 때의 검색 상자 제출 때문에 `form-action 'self'` 를 연다. 미리보기 빌드에는 넣지 않는다(서버가 응답 머리로 준다). `npm run check:csp` 가 공개용 시험 빌드에서 위반 0건과 검색 동작을 확인한다.
- 자료에서 온 주소는 `http://`, `https://` 로 시작할 때만 링크로 쓴다(`src/lib/data.ts` 의 `safeHref`). 검색 결과는 DOM 으로 만들고 발췌에서 `<mark>` 만 남긴다.

## 예시 자료 `sample-data/`

모두 지어낸 것이다(가상의 한빛시, 가람군, 다온구, 누리전자 · 주소는 `*.example` · 날짜는 2099년).

이슈 두 건은 저장소의 지어낸 예시(`tests/fixtures/issues/`)를 미리보기용으로 내보낸 것이다. 다시 만드는 명령:

```sh
cd <저장소>
T=$(mktemp -d) && mkdir -p "$T/desk" && cp -R tests/fixtures/issues "$T/desk/issues"
OZL_DESK_ROOT="$T/desk" .venv/bin/python -m ozl.issues export --preview --out "$T/desk/out"
```

- `issues/nuri-battery-recall.json` 과 `index.json` 의 그 줄은 내보낸 것 그대로다.
- 주장과 작은 주장의 `basis`(판정을 받치는 확인된 사실 문장)와 `scope`(확인한 범위)는 내보내기 2판부터 싣는다. 예시 자료에는 `basis` 를 `hanbit-bus-fare-400`(최신판과 `r/3`)과 `garam-reservoir-levee` 의 몇 건에, `scope` 를 `hanbit-bus-fare-400`(최신판과 `r/3`)의 '확인' 주장 1건과 작은 주장 1건에 지어 넣었다. `meta.json` 의 `export_version` 은 2다.
- `hanbit-bus-fare-400` 은 내보낸 본문을 틀로 판을 셋으로 늘렸다(1·2판은 '적자 200억' 이 확인 못 함, 2판에 정정, 3판에 판정 변경). 최신판 파일과 `r/1~3.json` 은 손으로 고친 것이다.
- 내보내기가 주지 않는 것(`days/` 의 화제 목록, 다가오는 일, 정리 전 화제, 정정이 있는 이슈, 60자 제목, 주장 0건 이슈, 키워드 겹침, 내림)은 내보내기 JSON 의 모양을 따라 손으로 쓴 것이다. 무엇을 시험하려고 넣었는지는 DESIGN.md 7절에 있다.
- `scripts/public-sample.mjs <원본> <새 폴더>` 는 예시를 공개용 모양(internal, publish_state, trend_now, 공개 제외 항목을 지움)으로 바꾼 사본을 만든다. 공개용 빌드 시험에 쓴다:

```sh
node scripts/public-sample.mjs sample-data /tmp/ozl-pub
OZL_SITE_DATA=/tmp/ozl-pub OZL_WEB_OUT=/tmp/ozl-pub-out OZL_REPORT_CONTACT=test@example.invalid npm run build:public
```

## 들어 있지 않은 것

화면 점검은 `checks/visual.mjs`, `checks/offline.mjs`, `checks/csp.mjs`, `scripts/cards.mjs` 의 자체 확인으로 한다. DESIGN.md 8-3 의 `tests/build.test.mjs`, `check-real-words.mjs`, `make-year-data.mjs` 는 아직 만들지 않았다.
