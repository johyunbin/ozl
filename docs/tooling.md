# 도구 조사 — GitHub 오픈소스 (2026-11-09 · star/push/license는 `gh api` 실측)


아카이브 제외: fhamborg/news-please · GeneralMills/pytrends · langchain-ai/open_deep_research. 이름 변경: Perplexica→ItzCrazyKns/Vane · mlx-audio→Neywa-Labs/mlx-audio.

## a. 뉴스 수집·RSS·본문
| repo | stars | push | license | 기능 | 적합 |
|---|---|---|---|---|---|
| kurtmckee/feedparser | 2,457 | 2026-11-02 | NOASSERTION | RSS/Atom 파싱 | 상 |
| adbar/trafilatura | 7,103 | 2026-11-06 | Apache-2.0 | 본문·메타 추출 | 상 |
| AndyTheFactory/newspaper4k | 1,170 | 2026-11-01 | MIT | 기사 파싱 | 중 |
| miniflux/v2 | 9,905 | 2026-11-07 | Apache-2.0 | 셀프호스팅 RSS+API | 중 |
| FreshRSS/FreshRSS | 16,536 | 2026-11-08 | AGPL-3.0 | RSS 집계 | 중 |
| DIYgod/RSSHub | 46,878 | 2026-11-09 | AGPL-3.0 | 비RSS 사이트→RSS | 상 |
## b. 트렌드
| flack0x/trendspyg | 64 | 2026-10-01 | MIT | pytrends 대체 | 중 |
| isnow890/naver-search-mcp | 87 | 2026-11-06 | MIT | 네이버 검색+데이터랩 MCP | 상 |
| praw-dev/praw | 4,292 | 2026-11-05 | BSD-2 | Reddit | 중 |
| HackerNews/API | 13,414 | 2025-01-01 | MIT | HN API | 중 |
- 네이버 데이터랩: 공식 REST 직접 호출 권장. 한국 커뮤니티 인기글 수집기는 신뢰 repo 없음 → RSSHub 라우트.
## c. 팩트체크·아카이브
| bellingcat/auto-archiver | 1,147 | 2026-11-05 | MIT | URL·SNS 자동 아카이브 | 상 |
| palewire/savepagenow | 197 | 2026-06-17 | MIT | Wayback 저장 | 상 |
| edgi-govdata-archiving/wayback | 94 | 2026-11-06 | BSD-3 | CDX 조회 | 중 |
| jjjake/internetarchive | 1,933 | 2026-11-06 | AGPL-3.0 | IA CLI | 중 |
| kitUIN/PicImageSearch | 738 | 2026-11-08 | MIT | 이미지 역검색 통합(스크래핑·취약) | 상 |
| googleapis/google-api-python-client | 8,968 | 2026-11-03 | Apache-2.0 | Fact Check Tools API | 중 |
| utaresearch/claimbuster-spotter | 87 | 2023-11-29 | GPL-3.0 | 영어 전용·방치 | 하 |
## d. 딥리서치 에이전트
| assafelovic/gpt-researcher | 30,591 | 2026-11-08 | Apache-2.0 | 계획→병렬검색→보고서, URL 인용 | 상 |
| stanford-oval/storm | 31,840 | 2025-09-30 | MIT | 문장단위 [n] 인용 | 중 |
| LearningCircuit/local-deep-research | 9,548 | 2026-11-09 | MIT | 로컬 LLM 딥리서치 | 상 |
| ItzCrazyKns/Vane(구 Perplexica) | 38,099 | 2026-09-01 | MIT | 검색 UI | 중 |
| dzhng/deep-research | 19,880 | 2026-04-11 | MIT | 최소 구현 | 하 |
## e. 전사·한국어 분석
| yt-dlp/yt-dlp | 206,322 | 2026-11-04 | Unlicense | 필수 | 상 |
| ggml-org/whisper.cpp | 55,031 | 2026-11-08 | MIT | Metal/CoreML — Apple Silicon 최속 | 상 |
| SYSTRAN/faster-whisper | 26,604 | 2026-11-06 | MIT | CPU(CTranslate2) | 중 |
| m-bain/whisperX | 25,163 | 2026-10-22 | BSD-2 | 화자분리(HF 토큰) | 중 |
| Neywa-Labs/mlx-audio | 8,219 | 2026-11-09 | MIT | MLX STT | 중 |
| MaartenGr/BERTopic | 7,945 | 2026-11-05 | MIT | 토픽 모델링 | 상 |
| MaartenGr/KeyBERT | 4,224 | 2026-08-25 | MIT | 키워드 | 중 |
| bab2min/kiwipiepy | 416 | 2026-10-20 | Apache-2.0 | 한국어 형태소 | 상 |
| FlagOpen/FlagEmbedding | 12,304 | 2026-10-27 | MIT | BGE-M3 다국어 임베딩 | 상 |
| jhgan00/ko-sentence-transformers | 218 | 2026-05-19 | CC-BY-SA-4.0 | 한국어 SBERT(구세대) | 중 |
## f. 슬라이드 생성
| scanny/python-pptx | 3,584 | 2024-08-07 | MIT | .potx 템플릿으로 폰트·색 완전 제어(1년+ 미갱신·사실상 표준) | 상 |
| MartinPacker/md2pptx | 516 | 2026-10-26 | MIT | MD→pptx(python-pptx 기반) | 상 |
| gitbrent/PptxGenJS | 6,362 | 2025-11-28 | MIT | JS | 중 |
| marp-team/marp-cli | 3,909 | 2026-09-08 | MIT | MD→PDF/PPTX(이미지형) | 중 |
| slidevjs/slidev | 49,405 | 2026-11-05 | MIT | 웹 슬라이드 | 중 |
| quarto-dev/quarto-cli | 6,161 | 2026-11-09 | NOASSERTION | MD→revealjs/pptx | 중 |
## g. 프레임·장면·중복
| Breakthrough/PySceneDetect | 5,410 | 2026-11-08 | BSD-3 | 장면 전환 | 상 |
| JohannesBuchner/imagehash | 3,887 | 2026-10-12 | BSD-2 | pHash 중복 제거 | 상 |
| idealo/imagededup | 5,682 | 2025-08-15 | Apache-2.0 | 무거움 | 중 |
## h. 사이트·Notion
| squidfunk/mkdocs-material | 27,602 | 2026-11-07 | MIT | Pages 표준 | 상 |
| ramnes/notion-sdk-py | 2,197 | 2026-11-07 | MIT | Notion API | 상 |
| gohugoio/hugo | 90,422 | 2026-11-07 | Apache-2.0 | | 중 |
| withastro/starlight | 9,533 | 2026-11-06 | MIT | | 중 |

## 추천 조합
- 가벼운 안: feedparser+trafilatura+RSSHub(공개)+데이터랩 직접호출+savepagenow+yt-dlp+whisper.cpp+kiwipiepy+md2pptx/python-pptx+MkDocs Material — 서버 불요, cron/Claude만으로.
- 표준 안: + Miniflux + naver-search-mcp + auto-archiver + gpt-researcher + BERTopic·BGE-M3 + PySceneDetect·imagehash + notion-sdk-py — Docker 1~2개.
- 풀 자동화: + local-deep-research ∥ STORM + WhisperX + PicImageSearch + trendspyg + praw/HN + Slidev — 스크래핑 계열 깨짐·유지보수 최대.
## 주의
- API 키: 데이터랩·Fact Check·Reddit·gpt-researcher(LLM/Tavily)·WhisperX(HF)·Notion·TinEye(유료). 한국어 약함: ClaimBuster·Fact Check·KeyBERT 기본·영어 임베딩. AGPL: RSSHub·FreshRSS·internetarchive(수정 후 공개 서비스 시 소스 공개 의무).
