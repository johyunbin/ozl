# OZL — 작업영역 SOP (규범만 · 전역 지침 `~/.claude/CLAUDE.md`는 자동 로드)

태그라인: **OZL — 오늘의 즐길거리. 매일 이슈를 발굴·검증·브리핑합니다.** 모든 일일 문서·사이트·README 상단에 고정.

## 진입 순서
1. 이 문서 → `README.md`(방법론 요약) → `docs/methodology.md`(검증 체계 정본)
2. 계획·결정 이력: `private/plan/`(비공개 사본) · 원본 `~/.claude/plans/ozl_plan_20261109_164333.md`
3. 오늘 할 일: 최신 `daily/` 보고서의 "채택 대기" + `tracks/syuka/analysis/STATUS.md`

## 공개/비공개 경계 (사용자 결정 2026-11-09)
- **공개**: 방법론·일일 보고서·클레임 레코드·사례 연구·코드·주제 분포 집계·스타일 가이드·템플릿 덱·**사용자 승인된** 제출 PPT.
- **비공개(`private/` · gitignore)**: 원본 영상·오디오·전사 전문·추출 프레임·원시 메타(API 정책)·PPT 초안·계획/검토 원문. 전사 전문은 어떤 형태로도 외부 공유 금지(집계만).
- 공개 산출물은 **공개본 추출 게이트**(`scripts/publish_gate.py` — 발표자 노트·숨김 슬라이드 제거, 내장 미디어 출처 메타 검사, 전사 연속 20자 인용 차단)를 통과한 것만 커밋.

## 검증 규칙 (정본 = docs/methodology.md)
- 모든 수치·주장은 `claims/` YAML 레코드(출처 티어·checks·counter·human_verified).
- `verified` = 원본성·정확성·해석 3차원 통과 + 사람 육안 대조. 모델 2/3 합의는 후보 승격 조건일 뿐.
- 이미지·로고·지도는 공식 프레스킷·기관 CI·라이선스 스톡만. 역검색 + 400% 확대 검수. 지도는 동해·독도 표기 확인란.
- 민감 소재: 전수 분석 전까지 임시 기준(국내 정당·선거·정치인 평가 제외 / 정책은 통계·해외 비교로만 / 젠더·종교·지역 비하·피해자 소재 제외 / 해외 정치·지정학 허용).

## 루틴·자동화
- 예약 루틴(07:30 / 21:00 / 토 10:00) = **Claude Opus 고정**(Fable 자동화 금지 · picker sticky 주의). 루틴 프롬프트에서 **Codex 호출 금지**(사용자 지시 세션에서만).
- 루틴의 자동 `git commit` + `push`는 **`daily/`·`docs/`·`claims/` 한정 사전 위임**(사용자 결정). 코드·설정·`tracks/`·`src/`는 수동 승인.
- 다글로 제출: 동시 1건·완료 후 다음·간격 ≥ 60초·일일 상한(초기 100)·402/429 즉시 중단. Trading 데몬 우선(계정 락 `~/.cache/daglo_submit.lock`).
- Whisper: `nice -n 19`·1프로세스·메모리 상한. yt-dlp: sleep 간격·프레임용 영상은 추출 후 삭제.

## 파일 규약
- 일일 보고서 `daily/YYYY/MM/YYYY-MM-DD_{am,pm}.md` · 주간 `daily/YYYY/weekly_YYYY-Www.md` · 카드 ID `YYYY-MM-DD-{am|pm|wk}-NN`(불변).
- 클레임 `claims/YYYY-MM-DD/<card_id>-cN.yaml` · 덱 `tracks/syuka/decks/YYYYMMDD_<slug>.pptx|pdf` + `sources.md`.
- 산출물 타임코드 `_YYYYMMDD_HHMMSS`, 버전 넘버 금지. 사용자 열람용 md는 PDF 쌍(전역 규칙).
- 외부 모델 디스패치 컨텍스트에 인증·스크래핑 코드 투입 금지(다글로 인증은 `~/Trading` 모듈이 관리 — 호출만).
