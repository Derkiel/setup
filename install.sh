#!/bin/sh
# 이 레포의 설정을 현재 기기에 건다. 여러 번 실행해도 결과가 같다.
# 스킬은 심볼릭 링크로 건다: 레포를 git pull 하면 바로 갱신되고, 고친 것은 레포에서 바로 커밋된다.
set -eu
REPO=$(cd "$(dirname "$0")" && pwd)
BACKUP="$HOME/.claude/backups/setup-$(date +%Y%m%d-%H%M%S)"

# link <레포 안 원본> <설치 위치>: 이미 있던 것은 지우지 않고 백업 폴더로 옮긴 뒤 링크를 건다
link() {
  if [ "$(readlink "$2" 2>/dev/null || true)" = "$1" ]; then
    echo "ok       $2"
    return
  fi
  if [ -e "$2" ] || [ -L "$2" ]; then
    mkdir -p "$BACKUP"
    mv "$2" "$BACKUP/"
    echo "backup   $2 -> $BACKUP/"
  fi
  mkdir -p "$(dirname "$2")"
  ln -s "$1" "$2"
  echo "linked   $2"
}

for src in "$REPO"/skills/*/; do
  src=${src%/}
  link "$src" "$HOME/.claude/skills/$(basename "$src")"
done

# caveman: 플러그인이 켜져 있으면 세션 시작 훅이 매번 자동으로 켠다. 시작 모드는 이 설정 파일이 정한다.
link "$REPO/config/caveman/config.json" "$HOME/.config/caveman/config.json"

LINE="source \"$REPO/shell/aliases.zsh\""
RC="$HOME/.zshrc"
if grep -qF "$LINE" "$RC" 2>/dev/null; then
  echo "ok       $RC"
else
  printf '\n# Derkiel/setup\n%s\n' "$LINE" >> "$RC"
  echo "added    $RC (새 터미널부터 cc 사용 가능)"
fi

# rtk-oss (Apache-2.0 판): Bash 명령 출력을 줄여서 Claude 에 넘긴다. 공식 설치 스크립트는 체크섬을 확인하고 ~/.local/bin 에 둔다.
# 훅만 건다(--hook-only): CLAUDE.md 는 건드리지 않는다. 텔레메트리는 기본 꺼짐, 프록시는 설치하지 않는다.
RTK="$HOME/.local/bin/rtk"
command -v rtk >/dev/null 2>&1 && RTK=$(command -v rtk)
if [ ! -x "$RTK" ]; then
  curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | RTK_EDITION=oss sh >/dev/null
  echo "installed rtk $("$RTK" --version)"
fi
if grep -q '"rtk hook claude"' "$HOME/.claude/settings.json" 2>/dev/null; then
  echo "ok       rtk hook"
else
  "$RTK" init -g --hook-only --auto-patch --no-trust-filters </dev/null >/dev/null
  echo "added    rtk hook (Claude Code 를 다시 시작하면 적용)"
fi

# agent-browser: 브라우저 자동화 CLI + Claude 가 그것을 찾아 쓰게 하는 스킬
if command -v npm >/dev/null 2>&1; then
  if ! command -v agent-browser >/dev/null 2>&1; then
    npm install -g agent-browser >/dev/null
    echo "installed agent-browser"
  fi
  if [ ! -d "$HOME/.agent-browser/browsers" ]; then
    agent-browser install >/dev/null
    echo "installed agent-browser 용 Chrome"
  fi
  if [ -e "$HOME/.claude/skills/agent-browser/SKILL.md" ]; then
    echo "ok       skill agent-browser"
  else
    (cd "$HOME" && DISABLE_TELEMETRY=1 npx -y skills add vercel-labs/agent-browser -g -a claude-code -y >/dev/null 2>&1)
    echo "installed skill agent-browser"
  fi
else
  echo "주의: npm 이 없어 agent-browser 를 설치하지 못했습니다. node 설치 뒤 install.sh 를 다시 실행하세요."
fi

command -v node >/dev/null 2>&1 || echo "주의: node 가 없습니다. caveman 자동 켜기 훅은 node 로 돌므로, 없으면 조용히 꺼진 채 시작합니다. node 를 설치하세요."

# 플러그인: "마켓플레이스 저장소  플러그인@마켓플레이스". caveman 은 플러그인만 쓴다(npm CLI 는 외부 전송·과금 경로가 있어 넣지 않는다)
PLUGINS="JuliusBrussee/caveman caveman@caveman"
if command -v claude >/dev/null 2>&1; then
  echo "$PLUGINS" | while read -r market plugin; do
    if claude plugin list 2>/dev/null | grep -qF "$plugin"; then
      claude plugin enable "$plugin" >/dev/null 2>&1 || true  # 꺼져 있었으면 다시 켠다
      echo "ok       plugin $plugin"
    else
      claude plugin marketplace add "$market" >/dev/null 2>&1 || true  # 이미 등록돼 있으면 실패해도 된다
      claude plugin install "$plugin" >/dev/null && echo "installed plugin $plugin"
    fi
  done
else
  echo "주의: claude 명령이 없어 플러그인($PLUGINS)을 설치하지 못했습니다. Claude Code 설치 뒤 install.sh 를 다시 실행하세요: https://claude.com/claude-code"
fi
