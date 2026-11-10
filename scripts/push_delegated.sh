#!/bin/bash
# 위임 범위(daily/ docs/ claims/)만 건드린 커밋을 origin/main 에 올린다 — 루틴과 `/ozl` 이 쓰는 유일한 push 경로.
#
#   scripts/push_delegated.sh            # 로컬 main 의 미푸시 커밋 중 위임 범위 커밋만 올린다
#   scripts/push_delegated.sh --dry-run  # 무엇을 올릴지만 보여 준다
#
# 로컬에 코드·설정 커밋(사용자 승인이 필요한 것)이 함께 쌓여 있어도 그것은 올리지 않는다:
#   1) 미푸시 커밋이 전부 위임 범위면 검사한 그 커밋(OID)까지만 `git push`.
#   2) 섞여 있으면 origin/main 위에 임시 작업 트리를 만들어 위임 범위 커밋만 cherry-pick 해 올리고,
#      로컬 main 은 origin/main 위로 rebase 한다(올린 커밋은 중복으로 빠지고 코드 커밋만 남는다).
# 병합 커밋은 올리지 않는다(부모 대비 변경을 한 줄로 판정할 수 없다). 파일 목록을 읽지 못하면 '통과'가 아니라 중단이다.
# force·reset 은 쓰지 않는다. 충돌하면 아무것도 올리지 않고 멈춘다.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
ALLOWED='^(daily|docs|claims)/'
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

die() { echo "[push_delegated] $*" >&2; exit "${2:-9}"; }

# 커밋 하나(또는 두 지점 사이)가 건드린 파일 목록을 받아 위임 범위 밖이 있으면 1, 없으면 0. 목록을 못 읽으면 중단.
outside() {   # 인자: 파일 목록(줄바꿈 구분) — 비어 있으면 "건드린 파일 없음"이라 범위 밖으로 친다
  local files="$1"
  [ -n "$files" ] || return 0
  if printf '%s\n' "$files" | grep -Ev "$ALLOWED" >/dev/null; then return 0; else return 1; fi
}

BR=$(git rev-parse --abbrev-ref HEAD)
[ "$BR" = "main" ] || die "main 브랜치가 아니다: $BR" 2
git fetch -q origin main || die "origin 을 받지 못했다" 2
HEAD_OID=$(git rev-parse HEAD)          # 이 시점의 커밋만 다룬다 — 검사 뒤에 main 이 움직여도 딸려 올라가지 않게
BASE_OID=$(git rev-parse origin/main)

AHEAD=$(git rev-list --count "$BASE_OID..$HEAD_OID")
BEHIND=$(git rev-list --count "$HEAD_OID..$BASE_OID")
[ "$AHEAD" -gt 0 ] || { echo "[push_delegated] 올릴 커밋 없음"; exit 0; }

PICK=()   # 위임 범위만 건드린 커밋(오래된 것부터)
HOLD=()   # 그 밖의 파일이 섞인 커밋·병합 커밋
LIST=$(git rev-list --reverse "$BASE_OID..$HEAD_OID") || die "커밋 목록을 읽지 못했다"
while read -r c; do
  [ -n "$c" ] || continue
  if [ "$(git rev-list --parents -n 1 "$c" | wc -w)" -gt 2 ]; then HOLD+=("$c"); continue; fi   # 병합 커밋
  FILES=$(git diff-tree --no-commit-id --name-only -r "$c") || die "커밋 $c 의 파일 목록을 읽지 못했다"
  if outside "$FILES"; then HOLD+=("$c"); else PICK+=("$c"); fi
done <<< "$LIST"

echo "[push_delegated] 미푸시 ${AHEAD}건 — 위임 범위 ${#PICK[@]}건 · 보류(코드·설정·병합) ${#HOLD[@]}건 · origin 보다 ${BEHIND}건 뒤"
for c in ${PICK[@]+"${PICK[@]}"}; do echo "  올림: $(git log -1 --format='%h %s' "$c")"; done
for c in ${HOLD[@]+"${HOLD[@]}"}; do echo "  보류: $(git log -1 --format='%h %s' "$c")"; done
[ "${#PICK[@]}" -gt 0 ] || { echo "[push_delegated] 위임 범위 커밋 없음 — 올리지 않는다"; exit 0; }
[ "$DRY" -eq 0 ] || exit 0

if [ "${#HOLD[@]}" -eq 0 ] && [ "$BEHIND" -eq 0 ]; then
  ALL=$(git diff --name-only "$BASE_OID" "$HEAD_OID") || die "변경 목록을 읽지 못했다"
  if outside "$ALL"; then die "위임 범위 밖 파일이 섞였다 — 중단" 4; fi
  git push origin "$HEAD_OID:refs/heads/main"
  echo "[push_delegated] 올림: $(git rev-parse --short "$HEAD_OID")"
  exit 0
fi

WT=$(mktemp -d "${TMPDIR:-/tmp}/ozl-push.XXXXXX")
cleanup() { git worktree remove --force "$WT" >/dev/null 2>&1 || true; rm -rf "$WT"; }
trap cleanup EXIT
git worktree add -q --detach "$WT" "$BASE_OID"
for c in "${PICK[@]}"; do
  if ! git -C "$WT" cherry-pick -x "$c" >/dev/null 2>&1; then
    git -C "$WT" cherry-pick --abort >/dev/null 2>&1 || true
    die "cherry-pick 충돌($(git log -1 --format='%h' "$c")) — 올리지 않고 멈춘다. 코드 커밋을 먼저 정리해야 한다." 3
  fi
done
NEW_OID=$(git -C "$WT" rev-parse HEAD)
ALL=$(git -C "$WT" diff --name-only "$BASE_OID" "$NEW_OID") || die "임시 트리의 변경 목록을 읽지 못했다"
if outside "$ALL"; then die "위임 범위 밖 파일이 섞였다 — 중단" 4; fi
git -C "$WT" push origin "$NEW_OID:refs/heads/main"
echo "[push_delegated] 올림: $(git rev-parse --short "$NEW_OID")"

git fetch -q origin main
if [ "$(git rev-parse HEAD)" != "$HEAD_OID" ]; then
  echo "[push_delegated] 그 사이 로컬 main 이 움직였다 — rebase 는 건너뛴다(나중에 'git rebase origin/main')"; exit 0
fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "[push_delegated] 작업 트리에 고치던 파일이 있어 rebase 는 건너뛴다(로컬 main 은 origin 과 갈라진 채) — 나중에 'git rebase origin/main'"
  exit 0
fi
if git rebase origin/main >/dev/null 2>&1; then
  echo "[push_delegated] 로컬 main 을 origin/main 위로 옮김 — 남은 미푸시 $(git rev-list --count origin/main..HEAD)건(코드·설정)"
else
  git rebase --abort >/dev/null 2>&1 || true
  die "rebase 충돌 — 되돌렸다. 원격에는 올라갔고 로컬 main 은 갈라진 상태다(사람이 정리)." 5
fi
