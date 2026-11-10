#!/usr/bin/env bash
# (2026-11-10) 승인된 커밋만 push 한다 — "push 대상 커밋 목록 = 승인된 목록" 을 대조하고 다르면 push 하지 않는다.
#   2026-11-06 프론트 push 명령이 디렉터리 이동 실패로 백엔드 워크트리에서 실행돼 미승인 커밋(dbeee7f)이 올라간 것을 막는 장치.
# 사용: tools/push_approved.sh [-C <repo_dir>] [-r <remote>] [-b <branch>] <승인 해시>...
#   예: tools/push_approved.sh f5d0e57 592562c c18526f e20b286
#       tools/push_approved.sh -C /Users/daniel/python_new/diagnosis-frontend ccd6988
#   승인 해시는 보고서에 적은 짧은 해시(7자 이상). origin/<branch>..HEAD 의 커밋과 순서·개수까지 같아야 push 한다.
set -euo pipefail
repo="$(pwd)"; remote="origin"; branch="main"
while getopts "C:r:b:" opt; do
  case "$opt" in C) repo="$OPTARG";; r) remote="$OPTARG";; b) branch="$OPTARG";; *) exit 2;; esac
done
shift $((OPTIND - 1))
if [ "$#" -eq 0 ]; then echo "승인 해시가 없습니다. push 하지 않습니다." >&2; exit 2; fi
git -C "$repo" fetch -q "$remote"
cur="$(git -C "$repo" rev-parse --abbrev-ref HEAD)"
if [ "$cur" != "$branch" ]; then echo "현재 브랜치 $cur ≠ $branch. push 하지 않습니다." >&2; exit 2; fi
pending=(); while IFS= read -r h; do [ -n "$h" ] && pending+=("$h"); done < <(git -C "$repo" log --reverse --format=%H "$remote/$branch..HEAD")   # macOS bash 3.2: mapfile 없음
if [ "${#pending[@]}" -ne "$#" ]; then
  echo "push 대상 ${#pending[@]}건 ≠ 승인 $#건. push 하지 않습니다." >&2
  git -C "$repo" log --oneline "$remote/$branch..HEAD" >&2; exit 1
fi
i=0
for want in "$@"; do
  full="$(git -C "$repo" rev-parse --verify --quiet "$want^{commit}" || true)"
  if [ -z "$full" ] || [ "$full" != "${pending[$i]}" ]; then
    echo "불일치: 승인 $((i + 1))번째 '$want' ≠ push 대상 $(git -C "$repo" rev-parse --short "${pending[$i]}"). push 하지 않습니다." >&2
    git -C "$repo" log --oneline "$remote/$branch..HEAD" >&2; exit 1
  fi
  i=$((i + 1))
done
echo "대조 일치($# 건) → push $remote $branch ($repo)"
git -C "$repo" log --oneline "$remote/$branch..HEAD"
git -C "$repo" push "$remote" "$branch"
