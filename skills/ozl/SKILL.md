---
name: ozl
description: OZL 이슈 데스크 — 소재 발굴·검증·기록. "오늘 소재", "/ozl am|pm|weekly", "/ozl pick <card_id>", "/ozl verify <claim_id…>", "/ozl publish <card_id…>", "/ozl status" 요청 시 사용.
---

# /ozl — 일일 이슈 데스크 절차

작업 폴더는 `~/OZL`, 파이썬은 `~/OZL/.venv/bin/python`(아래 `PY`). 규범은 `~/OZL/CLAUDE.md`, 검증 규칙의 정본은 `~/OZL/docs/methodology.md` 이고 이 문서는 순서만 정한다. 모든 산문은 한국어.

인자: `am` · `pm` · `weekly` · `pick <card_id>` · `verify <claim_id…>` · `publish <card_id…>` · `status`. 날짜는 오늘(KST).

## 0. 가드 (예약 실행이면 가장 먼저)

1. **기기**: `hostname -s` 가 `Mac-mini` 가 아니면 아무것도 하지 않고 "다른 기기 발화 — 무동작 종료" 한 줄만 남긴다.
2. **모델**: 예약 실행인데 자기 모델이 Opus 계열이 아니면(`get_session` 의 `model`, 없으면 시스템 프롬프트의 모델명) 아무것도 하지 않고 "모델이 Opus 가 아님 — 무동작 종료. 앱의 모델 선택을 Opus 로 되돌려야 한다" 고 보고한다. 사용자가 대화로 직접 부른 경우에는 이 가드를 적용하지 않는다.
3. **쓰기 범위(예약 실행)**: `~/OZL/private/desk/` · `~/OZL/private/daily/` · `~/OZL/daily/` · `~/OZL/claims/` 와 Notion DB 「OZL 소재 카드」뿐. 코드·설정·`docs/`·스킬 문서·다른 저장소는 고치지 않는다. 고장이 의심되면 고치지 말고 근거(명령·출력)와 함께 보고한다.
4. **금지**: 예약 실행에서 Codex 호출 · 인증·스크래핑 코드를 외부 모델에 넘기기 · 봇 차단·유료 벽 우회 · `git add -A` · `scripts/push_delegated.sh` 밖의 push · `human-verify`/`publish` 를 사용자 말 없이 실행.

## 1. `am` / `pm` — 소재 카드 5~8장

**멱등**: `PY -m ozl.research status --date <오늘>` 에 이 회차 카드가 이미 있으면 새로 만들지 않는다. 수집만 다시 해서(같은 회차의 재수집은 `recheck_HHMM.md` 로 따로 쌓이고 첫 수집본은 그대로 둔다) ① 기존 카드의 계기가 바뀌었는지(발표가 나왔다·수치가 정정됐다) ② 빠진 큰 소재가 있는지 보고, 바뀐 카드만 고쳐 `revision` 을 올리고 6단계부터 다시 한다. 바뀐 것이 없으면 "변경 없음"으로 끝낸다.

1. **수집** — `PY -m ozl.research collect --slot am`(아침은 `--hours 24`, 저녁은 `--hours 14`). 명령이 찍어 주는 요약본(`private/desk/<날짜>_<회차>/candidates.md`)을 읽는다. 맨 위 "받지 못한 피드"·"커버리지 대조 실패"·"일정 재확인 필요" 줄이 있으면 보고에 옮긴다.
2. **고르기** — 후보 20~30개를 추린 뒤 5~8개로 줄인다. 기준은 `docs/methodology.md §7`:
   - 속보 요약이 아니라 **이면**(구조적 병목·해외 틈새·과거 평행·통계의 함정)이 있는가. 묶음 점수가 높다고 좋은 소재가 아니다.
   - **왜 오늘인가**를 날짜로 말할 수 있는가(공식 발표·예정 일정이 가장 단단하다 — 요약본의 "발표 일정"을 먼저 본다).
   - 민감 기준: RED 는 올리지 않는다. YELLOW 는 통계·해외 비교·시장 메커니즘으로만.
   - 슈카월드가 최근에 다룬 소재는 빼거나 "후속"으로 각도를 바꾼다. 회차 배치 관찰: 첫 주제는 해외 시사·기업, 마지막은 증시·투자가 많다(`tracks/syuka/analysis/bridge_patterns_public.md`).
3. **커버리지 대조** — 카드마다 `PY -m ozl.research coverage <낱말…> [--fulltext]`. 쓴 낱말을 카드 `coverage.searched` 에 적는다(찾아보지 않은 것과 없는 것을 구분). 전사 문장은 어디에도 옮기지 않는다.
4. **1차 출처 조사** — 상위 3장은 핵심 수치 3개 이상을 **T1/T2 원문을 직접 열어** 확보한다. 서브에이전트(읽기 전용 `Explore`·Opus)를 카드당 하나씩 병렬로 쓰고(동시 5개 이하), 각자 `주장 | 원문 표기 | URL | 기관 | 등급 | 원문 위치 | 기준 시점 | 주의점` 표와 "확인 실패 목록"을 1,800토큰 안으로 돌려받는다. 검색 요약만 본 값은 수치로 쓰지 않는다. 나머지 카드는 1차 출처 링크만 달고 `depth: light`.
5. **카드·클레임 쓰기** — `PY -m ozl.research ids --slot am -n <장수>` 로 번호를 받고, `skills/ozl/card_template.yaml`·`claim_template.yaml` 을 본떠 `private/desk/cards/<card_id>.yaml`, `private/desk/claims/<날짜>/<card_id>-cN.yaml` 을 쓴다.
   - ⑧ 예상 구성은 `tracks/syuka/style/composition_template_v0.md` 의 단계 이름(여는 장·배경·전개·반전·근거 수치·비교·시사점·닫는 장 …)으로 5단계 이상, 반전을 반드시 넣는다.
   - 클레임의 `status` 는 `pending`, `human_verified: false` 로 쓴다. 원문을 열어 맞춰 본 것은 `verifiers.claude` 에 무엇을 봤는지 적는다. `counter`(가장 강한 반례·분모·남는 불확실성)를 빈칸으로 두지 않는다.
   - 보도만 있고 공식 발표가 없는 사건은 "보도에 따르면"으로 쓰고 수치 클레임으로 만들지 않는다.
6. **검사** — `PY -m ozl.research validate --slot am` 이 오류 0건이어야 한다.
7. **독립 검증** — 새 서브에이전트(`Explore`·Opus)에게 카드 문장이 아니라 **클레임 표(주장·원문 표기·URL·원문 위치)만** 주고, 원문을 다시 열어 일치·불일치·열지 못함으로 판정하게 한다. 불일치는 고치고, 열지 못한 클레임은 `verifiers` 에 그 사실을 적는다. 작성한 세션이 스스로 채점하지 않는다. Gemini·ChatGPT 교차는 여력이 있을 때 `multimodel_request` 로 한 번 시도하고, 실패해도 이 단계를 대신하지 않는다.
8. **렌더** — `PY -m ozl.research render --slot am` → 전체본·검증 시트(`private/daily/…`)와 발행본(`daily/…`). 전체본은 `python3 ~/Claude/tools/md2pdf.py <전체본.md> --theme doc --footer-title` 로 PDF 를 만들고 첫 쪽을 눈으로 확인한다.
9. **Notion** — `PY -m ozl.research notion --slot am` 이 내는 속성 묶음으로 DB 「OZL 소재 카드」(식별자 `private/notion.json`)에 `card_id` 기준 upsert 한다: 먼저 `card_id` 로 조회해 있으면 속성만 갱신, 없으면 새 페이지(본문 = 전체본의 그 카드 부분). **이때 Notion 의 `상태` 가 `채택`·`보류`·`반려` 로 바뀌어 있으면 그것이 사용자 결정이다** — 카드 YAML 의 `state` 를 거기에 맞추고(§3) 덮어쓰지 않는다.
10. **커밋·발행** — `git add` 는 `daily/<…>.md`(와 승인된 카드가 있으면 `claims/<날짜>/`)만 pathspec 으로. 커밋 뒤 `scripts/push_delegated.sh` → `gh run watch` → `https://johyunbin.github.io/ozl/daily/<날짜>_<회차>/` 가 열리는지 확인한다. pre-commit(gitleaks·공개본 게이트)이 막으면 우회하지 않는다.
11. **보고** — 카드 표(번호·제목·배지·민감도), 받지 못한 피드, 독립 검증 결과(일치/불일치/미확인 건수), 커밋·CI·Pages·Notion 증거, 사용자에게 필요한 일(검증 시트 대조·채택) 순으로 짧게.

**저녁(`pm`)**: 아침 카드를 먼저 다시 본다 — 예정돼 있던 발표가 나왔으면 수치를 채우고 `revision` 을 올린다. 그 뒤 당일 국내 마감·속보에서 새 카드 2~4장.

## 2. `weekly` (토요일)

주중 카드 전체를 `status` 로 불러 다시 평가한다(계기가 아직 살아 있는가·그 사이 슈카월드가 다뤘는가·수치가 정정됐는가). 일요일 생방송용 Top 5 를 `wk` 회차 카드로 만든다(주중 카드를 올릴 때는 새 번호를 주고 `discovery` 에 원래 `card_id` 를 적는다). 채택률·반려 사유를 세어 보고에 넣는다.

## 3. 사용자 명령

- `pick <card_id>` — `PY -m ozl.research pick <card_id>` → Notion 상태도 `채택`. 그 카드의 나머지 주장까지 클레임으로 만들어 전수 검증하고(§1의 4~7), PPT 초안(`private/decks/drafts/`)은 Phase 4 절차로 넘긴다.
- `verify <claim_id…>` — **사용자가 "원문과 대조했다"고 말한 클레임만** `PY -m ozl.research human-verify <claim_id…> --by <사용자>`. 그 뒤 `render`.
- `publish <card_id…>` — `PY -m ozl.research publish <card_id…> --by <사용자>`. 배지가 확인·추정이 아니면 코드가 거부한다. 발행 직전에 출처 링크가 살아 있는지·수치가 그대로인지 다시 연다. 그 뒤 커밋(`daily/`·`claims/`)·`push_delegated.sh`·Notion `Pages 링크` 갱신.
- `status` — `PY -m ozl.research status`.

## 4. 고장 났을 때

- 피드가 죽었다 → 나머지로 진행하고 보고에 남긴다. 절반 넘게 죽으면 카드를 만들지 않고 보고한다.
- 1차 출처가 열리지 않는다 → 그 수치는 쓰지 않는다. 카드를 `light` 로 내리거나 다른 수치로 바꾼다.
- 발표 일정이 14일 안에 하나도 없다는 경고 → 공식 일정 페이지를 다시 열어 `calendar.yaml` 에 넣을 항목을 보고에 적는다(예약 실행은 파일을 고치지 않는다).
- push 가 막혔다(충돌·CI 실패) → 다시 밀지 않는다. 로컬 커밋 상태와 오류 원문을 보고한다.
