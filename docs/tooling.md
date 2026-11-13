# 도구

실제로 돌리고 있는 것만 적습니다.

## 매일 쓰는 것

| 도구 | 하는 일 |
|---|---|
| Claude Code | 후보 발굴과 완성 절차를 돌립니다. 예약 실행은 2026년 11월 13일부터 멈춰 두었습니다. 절차서는 저장소의 `skills/ozl/SKILL.md` 입니다 |
| feedparser, requests | 피드를 읽습니다 |
| PyYAML | 카드와 검증 기록을 YAML 파일로 읽고 씁니다 |
| MkDocs Material, GitHub Pages | 이 사이트를 만들고 올립니다 |
| Notion | 카드 상태를 바꾸는 작업판입니다. 기록의 원본은 파일이고 Notion 은 보는 창입니다 |
| gitleaks, pre-commit | 커밋 전에 비밀값과 비공개 문구가 섞이지 않았는지 검사합니다 |

## 슬라이드를 분석하고 만들 때 쓰는 것

| 도구 | 하는 일 |
|---|---|
| OpenCV, PySceneDetect, ImageHash, Pillow, NumPy | 방송 화면에서 슬라이드가 바뀌는 지점을 찾고 색과 글자 크기를 잽니다 |
| macOS Vision | 슬라이드 화면의 글자를 읽습니다(`tools/ocr/ocr.swift`) |
| python-pptx, lxml | 슬라이드 초안 파일을 만듭니다 |
| PowerPoint | 초안을 마감하고 PDF 로 내보냅니다 |
| yt-dlp | 슬라이드 분석에 쓸 화면을 뽑을 때 씁니다. 영상은 분석 뒤에 지우고 저장소에 올리지 않습니다 |

## 직접 만든 것

- 공개본 검사(`scripts/publish_gate.py`): 비공개 자료의 문장이 공개 파일에 섞였는지 커밋 전에 찾습니다.
- 범위 제한 푸시(`scripts/push_delegated.sh`): 예약 작업이 보고서와 검증 기록만 올리고 코드는 올리지 못하게 합니다.
- 카드 검사와 공개 판정(`src/ozl/research/cards.py`): 승인이 있고, 배지가 기준을 넘고, 승인 때의 내용과 지금 내용이 같을 때만 공개로 봅니다.

예전에 이 자리에 있던 오픈소스 조사 표는 쓰지 않는 도구가 대부분이어서 내렸습니다.
