# setup

어느 기기에서든 Claude Code 환경을 같은 상태로 맞추는 레포.

```sh
git clone https://github.com/Derkiel/setup.git ~/setup && ~/setup/install.sh
```

아무것도 없는 새 맥에서는 `git` 을 처음 실행할 때 macOS 가 명령줄 개발자 도구 설치를 묻는다. 설치가 끝난 뒤 위 명령을 다시 실행한다.

끝나면 새 터미널을 열고 `claude` 를 한 번 실행해 로그인한다.

`install.sh` 가 하는 일 (여러 번 실행해도 안전):

- `skills/*` 를 `~/.claude/skills/` 에 심볼릭 링크로 건다. 같은 이름이 이미 있으면 `~/.claude/backups/setup-<시각>/` 으로 옮긴다.
- `~/.zshrc` 에 `shell/aliases.zsh` 를 불러오는 한 줄을 넣는다 (`cc` = 권한 확인 없이 Claude Code 실행).

- caveman 플러그인을 설치하고 `~/.config/caveman/config.json` 을 `config/caveman/config.json` 에 링크한다. 모든 새 세션이 caveman 모드로 시작한다 (node 필요. 끄려면 그 파일의 `defaultMode` 를 `"off"` 로).

- rtk-oss 를 `~/.local/bin` 에 설치하고 Claude Code 에 훅을 건다 (Bash 출력 압축. 텔레메트리 꺼짐, 프록시 없음. 빼려면 `rtk init -g --uninstall`).
- agent-browser CLI, 전용 Chrome, 스킬을 설치한다 (npm 필요).

- 플러그인 ponytail, frontend-design, claude-md-management, skill-creator, context7 과 외부 스킬 10개(Emil Kowalski 디자인·모션 7, Vercel 3)를 설치한다.
- mattpocock-skills 플러그인을 설치하고, 수동 전용 스킬 10개를 Claude 가 알아서 부르도록 세션 시작 훅(`tools/skill_autoinvoke.py`)을 건다.
- Playwright MCP 를 사용자 범위로 등록한다.
- macOS: D2Coding 글꼴과 cmux 를 Homebrew 로 설치하고, 글꼴 설정(`config/ghostty/config`)을 `~/.config/ghostty/config` 에 링크한다(Ghostty 와 cmux 가 함께 읽는다). cmux 사용 통계 전송은 끈다.
- cmux 의 Cloud·로그인 화면을 끄는 구성 프로파일(`config/cmux/disable-cloud.mobileconfig`)을 연다. 설치 승인은 시스템 설정 > 일반 > 기기 관리 에서 직접 한 번 해야 한다(macOS 가 자동 설치를 막는다). 재시동과 cmux 업데이트 뒤에도 유지된다.
- 스킬 라우팅 표(`claude/skill-routing.md`)를 `~/.claude/skill-routing.md` 에 링크하고 전역 `CLAUDE.md` 에 `@skill-routing.md` 한 줄을 넣는다. Claude 가 상황에 맞는 스킬을 알아서 고른다.
- 새 맥 준비: Homebrew, node, Claude Code 가 없으면 설치한다(Homebrew 는 맥 비밀번호를 묻는다). 명령줄 도구 `gh`, `jq`, `yq`, `fd`, `mise` 도 설치한다.
- Go·Java·Kotlin 코드 탐색: 언어 서버 `gopls`, `jdtls`, `kotlin-lsp` 와 공식 LSP 플러그인 3개. 언어 런타임(Go, JDK)은 프로젝트가 정한 버전을 `mise` 로 맞춘다.
- 비밀 파일 읽기 금지 규칙(`.env`, `~/.ssh`, `~/.aws`, `~/.kube`, gcloud, gnupg)을 `settings.json` 에 더한다. Claude 의 파일 도구만 막고 셸 `cat` 은 막지 못한다.
- 회사 관리 설정(`managed-settings.json`)이 있으면 알려 준다.
- BetterTouchTool 을 설치하고 프리셋(`config/btt/Default.bttpreset`) 가져오기 창을 띄운다. 라이선스 등록과 권한 허용은 직접 한다.
- 앱 차단 토글(`tools/appblock.sh`)을 `~/.local/bin/appblock` 에 링크한다. BetterTouchTool 단축키의 액션 "Execute Shell Script / Task" 에 `~/.local/bin/appblock toggle` 을 넣으면, 켜져 있는 동안 `~/.config/appblock/apps` 에 적은 앱(한 줄에 하나)이 실행하는 순간 종료된다. 창이 뜨지 않고 포커스도 넘어가지 않으며 재부팅해도 유지된다. 목록 파일은 처음 켤 때 만들어지고 이 레포에는 넣지 않는다. 시험: `tools/test_appblock.sh` (체스와 스티커를 실제로 띄운다).
- 한/영 전환을 cmd+space 로 바꾸고 Spotlight 의 cmd+space 는 끈다.

레포 폴더를 옮기면 `install.sh` 를 다시 실행한다. 토큰과 키는 이 레포에 넣지 않는다.
