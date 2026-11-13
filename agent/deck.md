# 슈카 자료와 덱

슈카월드 영상 자료(전사, 슬라이드 분석)와, 통과한 소재로 생방송용 덱을 만드는 일의 규칙이다. 공통 규칙(문장 대조의 기준 포함)은 `CLAUDE.md` 에 있다. 덱을 완성본까지 만드는 순서는 `skills/ozl/SKILL.md` §5 가 정본이다.

## 영상 자료 받기
- 다글로 제출: 동시 1건, 완료 후 다음, 간격 ≥ 60초, 일일 상한(초기 100), 402/429 즉시 중단. Trading 데몬 우선(계정 락 `~/.cache/daglo_submit.lock`). 다글로 인증은 `~/Trading` 모듈이 관리한다(호출만).
- Whisper: `nice -n 19`, 1프로세스, 메모리 상한. yt-dlp: sleep 간격, 프레임용 영상은 추출 후 삭제.
- 영상 목록과 전사 자료 DB 는 `python -m ozl.syuka`(`catalog`, `sample`, `put`, `agree`, `status`)가 다룬다.

## 슬라이드 분석 파이프라인 (Phase 2A 정본 · 2026-11-10)
- 장수와 구성: `slide_dense`(3초 표본 + 문자 인식 + 제목 묶음) → `slide_dense rebuild` → `slide_structure` → `compose_aggregate holdout`(모듈은 `src/ozl/analyze/`). `collect/frames.py`(장면 전환 + pHash) 프레임으로 장수를 세지 않는다 — 슬라이드의 44%를 놓친다(색, 폰트 측정에만 유효).
- 구성 라벨의 번호는 `private/slides_label_r2/`(고정본)와 맞는다. `slide_structure` 가 다시 쓰는 `slides_label/` 은 번호가 달라질 수 있다.
- 렌더 검증의 정본 = 파워포인트 내보내기(`src/ozl/render/ppt_export.py`). LibreOffice 는 맑은 고딕, 줄 간격이 달라 대체 경로로만.

## 덱 초안 생성기 (Phase 4 · 2026-11-10)
- 두 단계다. 카드와 검증 기록을 읽고 덱 사양(`private/decks/specs/<card_id>_<타임코드>.yaml`)을 쓰는 일은 세션(에이전트)이 하고, `python -m ozl.render check|build <사양>` 은 그 사양을 검사해 `pptx` 로 만든다. 코드는 문장을 짓지 않는다. 그 밖의 명령은 `python -m ozl.render bundle <사양>`(검토 묶음)과 `python -m ozl.render progress <card_id>`(진행 기록)이다.
- 숫자 규칙: 화면 글과 말로 할 문장의 수량은 인용한 검증 기록의 `observed`·`text` 에 같은 표기로 있어야 한다(환산해 적었으면 `conversions` 에 원문 표기). 엄격 모드는 '확인'(사람 대조로 `verified` 가 된 기록) 또는 「원문 일치」(기계 대조 — 쓸 때마다 사본 재해시, 문구와 자리 재대조) 기록만 받는다(`spec.acceptance_error`). 판독 규칙과 못 잡는 것은 `src/ozl/render/numbers.py` 머리말에 있다.
- 초안 모드(`build --draft --claims-dir private/desk/staging/<card_id>/`)는 아직 받아들여지지 않은 기록(사람 대조도 「원문 일치」도 아닌 것)과 대기 폴더 기록으로 미리 만들어 보는 용도다. 해당 쪽에 [검증 대기] 가 찍히고 산출물 이름에 `_draft` 가 붙는다. 완성본과 공개에 쓰는 판은 엄격 모드로만 만든다. `--claims-dir` 은 초안 모드에서만 쓸 수 있다.
- 보도 기사(T3)는 숫자의 근거가 되지 않는다(기계 대조는 T1·T2 원문만). 덱에서는 카드 `sources` 와 사양 `refs` 로 숫자 없이 기사로만 인용한다 — 각주에는 숫자 근거로 인용한 기록의 문서가 '출처:', refs 로만 인용한 회사와 기관 문서(카드 `sources` 의 T1·T2)가 '자료:', 그 밖의 refs 가 '보도:'로 찍힌다.
- 그림 자리(`image_text`, `number`, `photo_caption`, `image_pair` 의 각 자리)에는 `image`(회색 자리), `chart`, `capture`, `picture` 가운데 하나만 쓴다. 둘 이상이거나 그림 자리가 없는 종류에 쓰면 실패다. 엄격 모드는 `photo_caption` 과 `image_pair` 의 회색 자리를 받지 않는다.
- 장 종류가 셋 더 있다. `capture_full`(인용 장)은 제목 한 줄과 원문 캡처 한 장뿐이다(`capture`, `capture_focus` 를 그대로 쓰고 `body` 는 두지 않는다). 캡처 규칙은 왼쪽 그림 자리와 같고, "대조한 문구가 다 들어가는가"는 큰 자리 크기로 계산한다. `photo_caption`(사진과 설명)은 큰 그림 하나(`image` 또는 `picture`)와 그 아래 `caption` 한두 줄이다. `image_pair`(그림 두 장 비교)는 `pair:` 에 자리 둘을 두고, 자리마다 `image`, `chart`, `capture`, `picture` 가운데 하나와 짧은 `caption` 을 쓴다. 자리의 차트와 캡처가 쓴 기록은 그 쪽 `claim_ids` 안이어야 하고, 차트 점 값 대조와 캡처 규칙은 다른 종류와 같다. 설명 글의 수량은 숫자 규칙을 그대로 받는다.
- 그림 파일은 사양 맨 위 `pictures:` 목록(그림 검수 대장)에 오른 것만 `picture: <그림 번호>`(p1, p2 …)로 넣는다. 칸: `id`, `path`, `kind`(그림 종류), `source_url`, `origin`(원출처), `rights_holder`, `license`, `commercial_ok`, `modify_ok`, `attribution`(출처 표시 문구), `reverse_search`(`did`, `result`), `synthetic_check`, `content_check`(인물, 로고, 지도 점검), `checked_at`, `as_is`(원형 그대로), 경우에 따라 `edits`(고쳐 썼을 때), `map_check`(지도 — `east_sea`, `dokdo`), `permission`(기업 뉴스룸 이용 조건 확인), `meme_origin`(밈). 대장을 사양 안에 두는 것은 검토한 판(사양 sha256)과 같은 대장으로 빌드하게 하려는 것이다.
- 판정은 `src/ozl/render/pictures.py` 의 `KIND_RULES` 가 정본이다(설계 5-7절 그림 종류 표를 옮겼다). 직접 그린 도표, 지도, 공공누리 1유형, CC BY 는 쓴다. CC BY-SA 와 공공누리 3유형, 로고는 원형 그대로만, 기업 뉴스룸 그림은 사용 허락 기록이 있을 때만 원형으로 쓴다. 따로 허락을 요구하는 회사의 로고(`LOGO_BLOCKED`), 통신사, 언론사 사진, 방송 화면 캡처, 공공누리 2유형과 4유형, 실존 인물 AI 그림, 사실처럼 보이는 AI 장면, 상업적 이용이 안 되는 그림은 쓰지 않는다. 무료 스톡 인물 사진은 경고를 낸다(부정적인 소재의 쪽에는 쓰지 않는다 — 사람이 본다). AI 개념도 밑에는 "AI 생성 이미지, 실제 장면 아님"이 찍힌다. 칸이 하나라도 비었거나 판정이 '쓰지 않는다'거나 파일이 없으면 엄격 모드는 실패, 초안 모드는 그 쪽에 [그림 대기]를 찍는다.
- 밈은 원출처와 라이선스가 확인된 것만 초안 모드에서 쓴다. 엄격 모드의 `check`, `build` 는 밈을 빼고(photo_caption 이면 쪽을 빼고, 그 밖은 그림 자리를 비운다) 뺀 것을 출력(`[밈 제외]`)과 러닝시트 머리에 적는다.
- 그림 밑에는 출처 표시 문구와 라이선스가 찍히고(로고는 "상표는 각 소유자의 것"을 붙인다), 부록 「시각물 출처, 검증표(그림 파일)」에 그림마다 한 줄(번호, 쪽, 종류, 권리자, 라이선스, 출처 주소, 확인 시각)이 들어간다.
- 러닝시트 머리에는 말로 할 문장(`spoken`, `transition`)의 글자 수로 어림한 발표 시간(분당 300자, 공백 제외 — `build.SPEAK_CHARS_PER_MIN`)과 인용한 검증 기록 수가 적힌다.
- 검토는 3판까지다. `progress --mark 검토 --spec <사양>` 은 그 사양의 엄격 검사 실패를 큰 오류로 적고, 문장 대조가 찾은 근거 없는 사실 문장은 `--major "글"` 로 더한다. 3판째 검토 뒤에도 큰 오류가 남으면 진행 기록이 '미완성'이 되고, 큰 오류가 남은 동안 `--done` 은 거부된다(다시 하려면 `--start --force`).
- `chart:` 는 `src/ozl/render/charts.py` 의 입력 그대로다(`kind`, `title`, `unit`, `period`, `series`, `source`, `claims` 등). `chart.claims` 는 그 쪽 `claim_ids` 안이어야 하고, 그림에 찍히는 수량(제목, 꼬리표 등)은 위 숫자 규칙을 그대로 받는다.
- 차트의 모든 점 값(꼬리표 없는 점 포함)은 `chart.claims` 가운데 한 기록의 원문 사본 글에서 공백으로 나뉜 낱말 하나와 글자 그대로 같아야 한다(표시 문자열이 있으면 그것 · `capture.find_value`). 차트 자료는 표의 칸에서 온다 — `-0.8%` 안의 `0.8%`, `3%~5%` 안의 `5%`, `11,234` 안의 `1,234`, `4명이다.` 안의 `4명` 은 찾은 것이 아니고, 같은 칸에서 바로 앞이 부호나 범위 이음 낱말이거나 바로 뒤가 범위 이음 낱말인 자리도 세지 않는다. 사본이 없는 옛 기록은 `observed`·`text` 에서 찾는다.
- 프로그램은 값이 사본에 있는지만 본다. 어느 칸(어느 달, 항목)의 값인지는 문장 대조에서 본다. 세로축 눈금은 대조하지 않고, `y_from_zero: false` 는 러닝시트 차트 줄에 적힌다.
- 기계 대조 기록의 `observed`·`author.located`·`recheck.located` 는 문장(마침표까지), 줄, 표의 칸을 **통째로** 따온다. 문장 중간에서 끊지 않는다(`capture.passage_bounds_error` — 등급을 올릴 때와 덱 엄격 모드, 발행 판정의 재검사 모두). PDF 표는 줄 전체만 받는다.
- `capture: <claim_id>` 는 빌드 때 해시가 확인된 원문 사본에서 대조한 자리(`match.target`)의 그림을 새로 그려 넣는다(PDF 는 그 쪽에 문구가 한 번만 나오면 해당 줄 둘레 띠, 두 번 이상이면 쪽 전체 · 그 밖은 사본 글의 대목 — 원래 화면 모양 아님 · 대조한 문구가 그림 자리에 다 들어가지 않으면 엄격 모드 실패). 기록의 `verification.image` 는 미리 보기일 뿐 덱은 쓰지 않는다. 그림 밑에는 원문 주소의 호스트만 적는다(받은 시각은 부록 「시각물 출처·검증표」가 맡는다). 그 기록은 `claim_ids` 안이어야 하고, 엄격 모드는 받는 기록(`acceptance_error` 빈 문자열)이며 사본에서 그릴 수 있어야 한다. 초안 모드는 기록이 아직 받아들여지지 않으면 그 쪽에 [그림 대기]를 찍는다.
- `capture_focus: "<구절>"`(또는 구절 목록)을 쓰면 원문 캡처에서 그 구절만 형광으로 칠한다(PDF 띠는 그 낱말 자리만). 구절은 대조한 대목(`observed`) 안에 글자 그대로(공백만 정리) 있어야 하고, 아니면 검사 실패다. 안 쓰면 대목 전체가 형광이다. 대목을 옮겨 그린 그림에는 대목 글과 맨 아래 표기 한 줄만 두고, 기록 번호, 주소, 받은 시각, 사본 해시는 부록 「시각물 출처·검증표(차트·원문 캡처)」가 맡는다.
- 엄격 모드에서 그림이 없는 `image_text` 쪽은 경고만 낸다. 렌더한 차트 PNG 는 산출 폴더의 `visuals/` 에, 러닝시트 장별 표 끝 칸에 그림 종류(차트, 원문 캡처, 그림 자리, 없음)가 적힌다.
- 발행한 카드에 기록을 더하거나 문구를 고칠 때는 `private/desk/staging/<card_id>/` 에 모아 둔다(기록 초안과 반영 스크립트). 새 기록이 받을 수 있는 등급(「원문 일치」 — `machine-verify --claims-dir`)이 된 뒤에 한 번에 옮기고, 반영 스크립트는 그 전에 임시 사본에서 끝까지 돌려 본다. 옮기면 그 카드의 승인이 풀리므로 다시 공개하려면 사용자의 승인이 있어야 한다. 사용자에게 눈 대조를 요청하지 않는다.
- 검사기가 통과시켜도 문장은 따로 본다. 인과, 선후, 범위, 주체는 숫자 검사로 잡히지 않는다. 사양을 쓴 쪽과 다른 에이전트의 문장 대조(기준은 `CLAUDE.md` 의 「문장 대조의 기준」), 다른 모델 계열의 해석 점검, 구성과 화면 평가를 판마다 거친다(`skills/ozl/SKILL.md` §5).
- 산출물은 비공개다: 초안 `private/decks/drafts/`, 완성본 `private/decks/final/<card_id>_<타임코드>/`(pptx, PDF, 러닝시트, 사양 사본, `검증_요약.md`). 완성 절차 진행 기록은 `private/desk/builds/<card_id>/state.yaml`(검토 원문은 같은 폴더 `reviews/`). `tracks/syuka/decks/` 로 옮겨 공개하는 것은 사용자가 "올려"라고 한 뒤다. 공개 덱의 이름은 `tracks/syuka/decks/YYYYMMDD_<slug>.pptx|pdf` + `sources.md`.

## 그림
- 이미지, 로고, 지도는 공식 프레스킷, 기관 CI, 라이선스 스톡만. 역검색 + 400% 확대 검수. 지도는 동해와 독도 표기 확인란.
