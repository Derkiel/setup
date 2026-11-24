# ~/.zshrc 에서 불러온다:  source <이 레포>/shell/aliases.zsh
# cc = 권한 확인 없이 Claude Code 실행. 시스템의 C 컴파일러 cc 를 가린다(필요하면 `command cc`).
alias cc='claude --permission-mode bypassPermissions'

# rtk 가 설치되는 곳. Claude Code 의 훅이 `rtk` 를 이름으로 부르므로 PATH 에 있어야 한다.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
