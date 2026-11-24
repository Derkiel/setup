# ~/.zshrc 에서 불러온다:  source <이 레포>/shell/aliases.zsh
# cc = 권한 확인 없이 Claude Code 실행. 시스템의 C 컴파일러 cc 를 가린다(필요하면 `command cc`).
alias cc='claude --permission-mode bypassPermissions'

# rtk 가 설치되는 곳. Claude Code 의 훅이 `rtk` 를 이름으로 부르므로 PATH 에 있어야 한다.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac

# Homebrew (Apple Silicon 은 기본 PATH 에 없다)
if ! command -v brew >/dev/null 2>&1 && [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
# mise: 프로젝트의 mise.toml / .tool-versions 에 적힌 Go·Java 등 런타임 버전을 자동으로 맞춘다
if command -v mise >/dev/null 2>&1; then eval "$(mise activate zsh)"; fi
