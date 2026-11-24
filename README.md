# setup

어느 기기에서든 Claude Code 환경을 같은 상태로 맞추는 레포.

```sh
git clone https://github.com/Derkiel/setup.git ~/setup && ~/setup/install.sh
```

`install.sh` 가 하는 일 (여러 번 실행해도 안전):

- `skills/*` 를 `~/.claude/skills/` 에 심볼릭 링크로 건다. 같은 이름이 이미 있으면 `~/.claude/backups/setup-<시각>/` 으로 옮긴다.
- `~/.zshrc` 에 `shell/aliases.zsh` 를 불러오는 한 줄을 넣는다 (`cc` = 권한 확인 없이 Claude Code 실행).

- caveman 플러그인을 설치하고 `~/.config/caveman/config.json` 을 `config/caveman/config.json` 에 링크한다. 모든 새 세션이 caveman 모드로 시작한다 (node 필요. 끄려면 그 파일의 `defaultMode` 를 `"off"` 로).

- rtk-oss 를 `~/.local/bin` 에 설치하고 Claude Code 에 훅을 건다 (Bash 출력 압축. 텔레메트리 꺼짐, 프록시 없음. 빼려면 `rtk init -g --uninstall`).
- agent-browser CLI, 전용 Chrome, 스킬을 설치한다 (npm 필요).

- 플러그인 ponytail, frontend-design, claude-md-management, skill-creator, context7, swift-lsp 와 외부 스킬 11개(Emil Kowalski 디자인·모션 7, Vercel 3, Remotion 1)를 설치한다.
- mattpocock-skills 플러그인을 설치하고, 수동 전용 스킬 10개를 Claude 가 알아서 부르도록 세션 시작 훅(`tools/skill_autoinvoke.py`)을 건다.
- Playwright MCP 를 사용자 범위로 등록한다.

레포 폴더를 옮기면 `install.sh` 를 다시 실행한다. 토큰과 키는 이 레포에 넣지 않는다.
