---
name: ozl
description: OZL 이슈 데스크 — 소재 발굴·검증·기록·PPT 초안. "오늘 소재", "/ozl pick <card_id>", "주간 종합" 요청 시 사용. 인자 = am|pm|weekly|pick <card_id>...
---
# /ozl (Phase 3에서 구현 — 현재 골격)
1. `am|pm`: 소스 수집 → 민감 필터(임시 기준) → 코퍼스 중복 대조 → 카드 5~8 → 상위 3 전수 검증(클레임 레코드·반증) → `daily/` md → Notion upsert → (위임 범위 내) commit/push.
2. `weekly`: 주중 카드 재평가 + 신규 → 일요 라이브용 Top 5.
3. `pick <card_id>`: 채택 카드 전수 검증 → `private/decks/drafts/` PPT 초안(python-pptx + template_syuka.pptx) → 사람 마감 안내.
규범 = `CLAUDE.md` · 검증 = `docs/methodology.md`.
