#!/bin/sh
# 이 레포의 설정을 현재 기기에 건다. 여러 번 실행해도 결과가 같다.
# 스킬은 심볼릭 링크로 건다: 레포를 git pull 하면 바로 갱신되고, 고친 것은 레포에서 바로 커밋된다.
set -eu
REPO=$(cd "$(dirname "$0")" && pwd)
BACKUP="$HOME/.claude/backups/setup-$(date +%Y%m%d-%H%M%S)"

mkdir -p "$HOME/.claude/skills"
for src in "$REPO"/skills/*/; do
  src=${src%/}
  dst="$HOME/.claude/skills/$(basename "$src")"
  if [ "$(readlink "$dst" 2>/dev/null || true)" = "$src" ]; then
    echo "ok       $dst"
    continue
  fi
  if [ -e "$dst" ] || [ -L "$dst" ]; then  # 이미 있던 것은 지우지 않고 옮겨 둔다
    mkdir -p "$BACKUP"
    mv "$dst" "$BACKUP/"
    echo "backup   $dst -> $BACKUP/"
  fi
  ln -s "$src" "$dst"
  echo "linked   $dst"
done

LINE="source \"$REPO/shell/aliases.zsh\""
RC="$HOME/.zshrc"
if grep -qF "$LINE" "$RC" 2>/dev/null; then
  echo "ok       $RC"
else
  printf '\n# Derkiel/setup\n%s\n' "$LINE" >> "$RC"
  echo "added    $RC (새 터미널부터 cc 사용 가능)"
fi

command -v claude >/dev/null 2>&1 || echo "주의: claude 명령이 없습니다. Claude Code 를 먼저 설치하세요: https://claude.com/claude-code"
