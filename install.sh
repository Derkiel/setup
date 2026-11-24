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

# 스킬 라우팅 표: 어떤 상황에 어떤 스킬을 부를지. 전역 CLAUDE.md 가 이 파일을 불러오게 한다(@가져오기).
# CLAUDE.md 에 이미 같은 표를 직접 적어 둔 기기에서는 규칙이 두 벌이 되지 않게 건너뛴다.
link "$REPO/claude/skill-routing.md" "$HOME/.claude/skill-routing.md"
MD="$HOME/.claude/CLAUDE.md"
if grep -qxF "@skill-routing.md" "$MD" 2>/dev/null; then
  echo "ok       $MD (@skill-routing.md)"
elif grep -q "^## Skill routing" "$MD" 2>/dev/null; then
  echo "skip     $MD 에 라우팅 표가 이미 직접 적혀 있습니다. 레포 것을 쓰려면 그 절을 지우고 다시 실행하세요."
else
  printf '%s@skill-routing.md\n' "$([ -s "$MD" ] && printf '\n')" >> "$MD"
  echo "added    $MD (@skill-routing.md)"
fi

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

# 터미널(macOS + Homebrew): D2Coding 글꼴, cmux(Ghostty 엔진 기반, 에이전트 여러 개를 사이드바로 관리).
# 글꼴 설정은 ~/.config/ghostty/config 한 곳에 두면 Ghostty 와 cmux 가 함께 읽는다.
link "$REPO/config/ghostty/config" "$HOME/.config/ghostty/config"
# cmux 는 사용 통계 전송이 기본으로 켜져 있어 끈 설정을 넣는다. 앱이 이 파일을 고쳐 쓸 수 있어 링크가 아니라 복사하고, 이미 있으면 건드리지 않는다.
if [ -e "$HOME/.config/cmux/cmux.json" ]; then
  echo "ok       $HOME/.config/cmux/cmux.json"
else
  mkdir -p "$HOME/.config/cmux"; cp "$REPO/config/cmux/cmux.json" "$HOME/.config/cmux/cmux.json"
  echo "added    $HOME/.config/cmux/cmux.json (사용 통계 전송 끔)"
fi
if [ "$(uname)" = Darwin ] && command -v brew >/dev/null 2>&1; then
  if ls "$HOME/Library/Fonts" /Library/Fonts 2>/dev/null | grep -qi '^D2Coding'; then
    echo "ok       font D2Coding"
  elif brew install --cask font-d2coding >/dev/null 2>&1 </dev/null; then echo "installed font D2Coding"; else echo "실패: font D2Coding"; fi
  if [ -d /Applications/cmux.app ]; then
    echo "ok       cmux"
  else
    brew tap manaflow-ai/cmux >/dev/null 2>&1 </dev/null || true
    if brew install --cask cmux >/dev/null 2>&1 </dev/null; then echo "installed cmux"; else echo "실패: cmux"; fi
  fi
  # cmux 의 Cloud·로그인 화면 끄기. cmux 는 구성 프로파일로 강제된 값만 인정한다(defaults write 는 무시).
  # 프로파일은 재시동과 cmux 업데이트 뒤에도 남는다. macOS 가 자동 설치를 막아 두어서 승인은 사람이 한 번 해야 한다.
  cloud_off() {
    for f in "/Library/Managed Preferences/com.cmuxterm.app" "/Library/Managed Preferences/$(id -un)/com.cmuxterm.app"; do
      [ "$(defaults read "$f" DisableCloud 2>/dev/null)" = 1 ] && return 0
    done
    return 1
  }
  if cloud_off; then
    echo "ok       cmux Cloud 끔 (구성 프로파일)"
  else
    open "$REPO/config/cmux/disable-cloud.mobileconfig"
    echo "할 일:   시스템 설정 > 일반 > 기기 관리 에서 'cmux: Cloud 끄기' 프로파일을 설치하세요(한 번만). 그 뒤 cmux 를 다시 켜면 Cloud 화면이 사라집니다."
  fi
else
  echo "주의: macOS + Homebrew 가 아니어서 D2Coding 글꼴과 cmux 를 설치하지 못했습니다."
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
  # 외부 스킬: "저장소  스킬 이름들". 이미 있는 스킬은 건너뛴다(갱신은 `npx skills update -g`).
  SKILLS="vercel-labs/agent-browser agent-browser
emilkowalski/skills animate animation-performance apple-design break-ui emil-design-eng prototype review-animations
vercel-labs/agent-skills vercel-react-best-practices vercel-composition-patterns web-design-guidelines
remotion-dev/skills remotion-best-practices"
  echo "$SKILLS" | while read -r repo names; do
    want=""
    for n in $names; do
      [ -e "$HOME/.claude/skills/$n/SKILL.md" ] || want="$want $n"
    done
    if [ -z "$want" ]; then
      echo "ok       skills $repo"
    else
      # shellcheck disable=SC2086
      (cd "$HOME" && DISABLE_TELEMETRY=1 npx -y skills add "$repo" -g -a claude-code -y -s $want >/dev/null 2>&1) </dev/null
      for n in $want; do
        [ -e "$HOME/.claude/skills/$n/SKILL.md" ] && echo "installed skill $n" || echo "실패: skill $n ($repo)"
      done
    fi
  done
else
  echo "주의: npm 이 없어 agent-browser 를 설치하지 못했습니다. node 설치 뒤 install.sh 를 다시 실행하세요."
fi

command -v node >/dev/null 2>&1 || echo "주의: node 가 없습니다. caveman 자동 켜기 훅은 node 로 돌므로, 없으면 조용히 꺼진 채 시작합니다. node 를 설치하세요."

# 플러그인: "마켓플레이스 저장소  플러그인@마켓플레이스". caveman 은 플러그인만 쓴다(npm CLI 는 외부 전송·과금 경로가 있어 넣지 않는다)
PLUGINS="JuliusBrussee/caveman caveman@caveman
anthropics/claude-plugins-official mattpocock-skills@claude-plugins-official
DietrichGebert/ponytail ponytail@ponytail
anthropics/claude-plugins-official frontend-design@claude-plugins-official
anthropics/claude-plugins-official claude-md-management@claude-plugins-official
anthropics/claude-plugins-official skill-creator@claude-plugins-official
anthropics/claude-plugins-official context7@claude-plugins-official"
if command -v claude >/dev/null 2>&1; then
  echo "$PLUGINS" | while read -r market plugin; do
    if claude plugin list 2>/dev/null </dev/null | grep -qF "$plugin"; then
      claude plugin enable "$plugin" >/dev/null 2>&1 </dev/null || true  # 꺼져 있었으면 다시 켠다
      echo "ok       plugin $plugin"
    else
      claude plugin marketplace add "$market" >/dev/null 2>&1 </dev/null || true  # 이미 등록돼 있으면 실패해도 된다
      if claude plugin install "$plugin" >/dev/null 2>&1 </dev/null; then echo "installed plugin $plugin"; else echo "실패: plugin $plugin"; fi
    fi
  done
  # Playwright MCP: 브라우저를 직접 조작하는 도구(화면 검증, 네이버 카페 읽기)
  if claude mcp get playwright >/dev/null 2>&1; then
    echo "ok       mcp playwright"
  else
    claude mcp add -s user playwright -- npx -y @playwright/mcp@latest >/dev/null && echo "added    mcp playwright"
  fi
else
  echo "주의: claude 명령이 없어 플러그인($PLUGINS)을 설치하지 못했습니다. Claude Code 설치 뒤 install.sh 를 다시 실행하세요: https://claude.com/claude-code"
fi

# mattpocock 스킬 중 수동 전용(/이름)으로 배포된 것을 Claude 가 알아서 부를 수 있게 바꾼다.
# 플러그인이 갱신되면 원래대로 돌아가므로 세션 시작 훅으로 매번 돌린다(대상 목록은 tools/skill_autoinvoke.py 안).
link "$REPO/tools/skill_autoinvoke.py" "$HOME/.claude/tools/skill_autoinvoke.py"
HOOK='python3 ~/.claude/tools/skill_autoinvoke.py --quiet'
python3 - "$HOME/.claude/settings.json" "$HOOK" <<'PY'
import json, os, sys
path, cmd = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
except FileNotFoundError:
    cfg = {}
groups = cfg.setdefault("hooks", {}).setdefault("SessionStart", [])
if any(h.get("command") == cmd for g in groups for h in g.get("hooks", [])):
    print("ok       hook skill_autoinvoke")
else:
    groups.append({"matcher": "", "hooks": [{"type": "command", "command": cmd}]})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    print("added    hook skill_autoinvoke")
PY
python3 "$HOME/.claude/tools/skill_autoinvoke.py"  # 지금 설치된 스킬에도 바로 적용
