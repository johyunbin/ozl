#!/usr/bin/env bash
# 비공개 기록(private/)을 백업 저장소(ozl-private)에 커밋하고 올린다.
#
#   scripts/backup_private.sh            # 바뀐 기록이 있으면 커밋·푸시
#   scripts/backup_private.sh --dry-run  # 올릴 파일만 보여 준다
#
# private/ 는 공개 저장소와 별개의 git 저장소다. 무엇이 올라가는지는 private/.gitignore 의 허용 목록이 정한다
# (카드·클레임 정본, 수집 원본, 전체본·검증 시트, 계획, 설명서, 태그 파일, 수집 DB 스냅숏, 열람 문서, 덱 완성본).
# 영상·전사·프레임·원문 사본·유튜브 통계는 올라가지 않는다.
# 올리기 전에 원격이 ozl-private 이고 비공개인지 확인한다. 아니면 멈춘다.
set -euo pipefail

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
die() { echo "[backup_private] $1" >&2; exit "${2:-1}"; }

cd "$(dirname "$0")/../private" || die "private/ 가 없다" 2
[ -d .git ] || die "private/ 가 git 저장소가 아니다" 2

URL="$(git remote get-url origin 2>/dev/null || true)"
case "$URL" in
  *github.com[:/]*/ozl-private|*github.com[:/]*/ozl-private.git) ;;
  *) die "원격이 ozl-private 가 아니다: ${URL:-없음}" 3 ;;
esac
SLUG="$(printf '%s' "$URL" | sed -E 's#^.*github\.com[:/]##; s#\.git$##')"
PRIVATE="$(gh repo view "$SLUG" --json isPrivate -q .isPrivate 2>/dev/null)" || die "원격 공개 범위를 확인하지 못했다" 3
[ "$PRIVATE" = "true" ] || die "원격 저장소가 비공개가 아니다 — 올리지 않는다" 3

# 허용 목록에 든 폴더만 이름으로 올린다(없는 폴더는 건너뛴다).
for p in .gitignore README.md notion.json desk daily plan guide research meta decks backup out briefs; do
  [ -e "$p" ] && git add -- "$p"
done

if git diff --cached --quiet; then
  echo "[backup_private] 바뀐 기록 없음"; exit 0
fi
git diff --cached --stat | tail -1
[ "$DRY" -eq 0 ] || { git diff --cached --name-status; git reset -q; exit 0; }

# 올리려는 목록에 원문 사본(폴더 이름이나 해시로 판정)이나 유튜브 통계가 섞였으면 멈춘다.
if [ -x ../.venv/bin/python ] && [ -f ../scripts/private_bundle.py ]; then
  ../.venv/bin/python ../scripts/private_bundle.py check-staged >/dev/null || {
    ../.venv/bin/python ../scripts/private_bundle.py check-staged >&2 || true
    git reset -q; die "올릴 목록에 원문 사본이나 유튜브 통계가 있다 — 커밋하지 않았다" 6; }
fi

if command -v gitleaks >/dev/null 2>&1; then
  gitleaks git --staged --redact >/dev/null 2>&1 || { git reset -q; die "gitleaks 가 비밀값을 찾았다 — 커밋하지 않았다" 4; }
fi
git commit -q -m "기록 $(date '+%Y-%m-%d %H:%M')"
git push -q origin main || die "push 실패 — 로컬 커밋은 남아 있다" 5
echo "[backup_private] 올림 $(git rev-parse --short HEAD)"
