---
name: ask-ui
description: Human-in-the-loop UI for Claude Code. Opens ONE persistent browser tab (a thread) where Claude pushes cards with rich content (markdown, code, diff, screenshots, video/GIF, live HTML, mermaid, side-by-side compare) and questions (single/multi/scale/text/rank/image choice, conditional show_if, recommended defaults, auto-submit). CLI blocks until the user answers, so the turn continues immediately. Use for preference discovery, design/UI choices that need seeing, A/B picks, multi-field intake, or whenever AskUserQuestion's 4 plain options are not enough. Triggers - "폼으로 물어봐", "UI로 물어봐", "보여주고 골라줘", "ask-ui", "선택지 띄워줘".
---

# ask-ui

하나의 브라우저 탭 = 대화 스레드. Claude가 카드(콘텐츠 + 질문)를 push하고, 사용자가 답하면 CLI가 즉시 반환되어 턴이 이어진다. 답한 카드는 한 줄 요약으로 접히고, 대기 중인 질문이 없어지면 탭은 스스로 닫힌다(다음 질문 때 이전 카드와 함께 다시 열린다).

## 핵심 명령
```bash
S=~/.claude/skills/ask-ui/scripts/ask_ui.py
python3 $S ask  spec.json          # push → 답 올 때까지 블로킹 → stdout JSON. Bash timeout 600000.
python3 $S show spec.json          # 콘텐츠만 보여주고 즉시 반환 (진행 상황, 결과 미리보기)
python3 $S wait <id>               # ask가 timeout(exit 2)으로 끝났을 때 이어서 대기
python3 $S cancel <id>             # 잘못 올린 카드 철회 (탭에서 "닫힌 질문"으로 접힌다). 고친 카드는 새로 ask
python3 $S status | list | open   [--session ID]
python3 $S stop                     # 데몬 종료 + 모든 세션의 스레드 이력 삭제(다른 세션의 대기 중인 질문도 끊긴다)
python3 $S ask - <<'JSON' ... JSON  # 스펙을 파일 없이 stdin 으로
```
- exit 0 제출 / 2 타임아웃(590초, `wait <id>`로 재대기) / 3 건너뛰기 / 1 오류.
- **exit 1 이면 stdout 의 `problems`(스펙 오류 목록) 또는 `error`(브라우저가 카드를 못 그림)를 읽고 스펙을 고쳐 다시 보낸다.** 스펙 점검은 탭에 올리기 전에 한다: 모르는 질문 type, 선택지 없는 선택 질문, 중복 id, 없는 질문을 가리키는 `show_if`. 질문 `id` 를 빼면 `q1`, `q2`… 로 채운다.
- 스펙에 적힌 로컬 파일이 없으면 카드는 올라가되 결과 JSON 에 `missing` 목록이 붙는다(그 칸은 빈 상자). 보고 고르는 카드라면 고쳐서 다시 보낸다.
- 질문 없는 스펙을 `ask` 하면 `show` 처럼 바로 돌아온다(status `shown`). `ask` 는 탭이 3초 안에 카드를 받아 가지 않으면 새 탭을 연다(브라우저가 꺼졌던 경우).
- **`late_answers` 가 결과 JSON 에 있으면 그것부터 반영한다.** ask 가 타임아웃(exit 2)된 뒤 사용자가 나중에 답한 카드의 답이다(실측: 답 6건 중 1건이 이렇게 온다). 그 세션의 다음 `ask`/`show`/`wait`/`cancel` 결과에 한 번만 실려 온다(`stop` 은 지우기 전에 출력한다). 건너뛴 카드(exit 3)와 늦은 답에도 `_note` 가 들어 있을 수 있다. 타임아웃 뒤 `wait <id>` 를 계속 붙잡고 있을 필요 없이 다른 일을 하다가 받으면 된다. `status` 의 `unread` 가 대기 중인 늦은 답 수.
- `warnings` 가 있으면 스펙에 페이지가 쓰지 않는 키가 있다는 뜻이다(오타, 없는 기능). 다음 카드부터 고친다.
- **세션마다 별도 탭.** 스레드 키는 `$CLAUDE_CODE_SESSION_ID`(자동) 또는 `--session ID`. URL `/t/<session>`, 탭 제목 `<작업폴더> · <세션 앞 6자>`. `/`는 열린 세션 목록. `list` 명령으로 전체 스레드 확인.
- 첫 호출이 데몬을 띄우고 그 세션의 탭을 연다. 그 세션 탭이 살아 있으면 새 탭을 열지 않고 macOS 알림만 보낸다. 다른 세션 탭에는 영향 없음.
- 답은 `~/.claude/ask-ui/history/`에 자동 저장. 취향 세션의 결론은 메모리로 옮긴다.

## 효율적인 인터랙션 원칙 (중요)
1. **물어보기 전에 추론하라.** 코드·메모리·이전 답에서 알 수 있는 건 묻지 않는다. 한 카드에 질문 3~5개 이하.
2. **보여주고 묻는다.** 선택이 "보면 바로 아는" 종류(UI, 디자인, 결과물, 문장)면 반드시 `content`나 `image` 옵션으로 실물을 넣는다. 우선순위: 라이브 HTML(`html`) > 스크린샷(`image`) > 코드/diff > 설명문. 설명문으로 UI를 묘사하지 않는다.
3. **움직임이 핵심일 때만 영상.** 전환 애니메이션, 인터랙션 흐름, 단계 순서는 GIF/`video`(Playwright 녹화 또는 `mcp__claude-in-chrome__gif_creator`)로. 정적인 것에 영상 금지. 흐름·구조 설명은 `mermaid`가 더 싸다.
4. **추천안을 기본 선택.** 옵션에 `recommended:true` 하나. 사용자는 Enter 한 번이면 끝. 단일 선택 1문항이면 자동 전송(클릭 = 제출).
5. **why 한 줄.** `why` 필드에 왜 묻는지, 답이 무엇을 바꾸는지. 선택지 `desc`에는 그 선택의 결과(트레이드오프)를 쓴다. 라벨은 5단어 이내.
6. **조건부로 깊게.** 세부 질문은 `show_if`로 숨겨두고 해당 답을 골랐을 때만 노출.
7. **터미널 대신 탭에 보고.** 긴 작업 중간 결과·완료 보고는 `show`로 탭에 올린다. 사용자가 터미널을 안 봐도 된다.
8. **답 받으면 한 줄로 반영 확인 후 바로 작업.** "제출됐나요?" 류 확인 질문 금지.
9. 2~4개 단순 선택지 + 보여줄 것 없음 → `AskUserQuestion`이 더 빠르다.

## 스펙 (JSON)
```json
{
  "title": "카드 제목", "why": "왜 묻는지 한 줄", "intro": "HTML 허용",
  "auto_submit": false, "submit_label": "보내기",
  "content": [
    {"type":"markdown","text":"## 제목\n- 목록"},
    {"type":"code","lang":"py","text":"...","caption":"..."},
    {"type":"diff","text":"unified diff"},
    {"type":"image","src":"/abs/path.png 또는 URL 또는 data:","caption":"..."},
    {"type":"video","src":"/abs/path.mp4|.webm","loop":true},
    {"type":"html","text":"<라이브 HTML>","height":240},
    {"type":"mermaid","text":"graph LR; A-->B"},
    {"type":"compare","items":[{"label":"A","image":"/a.png"},{"label":"B","html":"<...>"},{"label":"C","code":"..."}]}
  ],
  "questions": [
    {"id":"q1","type":"single","label":"...","desc":"...","required":true,"other":true,
     "options":[{"value":"a","label":"A","desc":"결과/트레이드오프","recommended":true},"b"]},
    {"id":"q2","type":"multi","label":"...","options":["a","b"]},
    {"id":"q3","type":"scale","label":"...","min":1,"max":5,"min_label":"약","max_label":"강","default":3},
    {"id":"q4","type":"text","label":"...","placeholder":"...","rows":3},
    {"id":"q5","type":"rank","label":"...","options":["x","y","z"]},
    {"id":"q6","type":"image","label":"...","options":[{"value":"a","label":"A","img":"/a.png"},{"value":"b","label":"B","html":"<live html>"}]},
    {"id":"q7","type":"text","label":"...","show_if":{"q":"q1","eq":"b"}}
  ]
}
```
- `show_if`: `{"q":id,"eq":v}` | `{"q":id,"neq":v}` | `{"q":id,"in":[..]}` | `{"q":id,"truthy":true}`. 숨겨진 질문은 검증·답에서 제외.
- 이미지 대량 평가: `{"type":"rate","aspect":"3/4","options":[{"value","label","img"}...]}` → 사진 오른쪽 절반 클릭 = 좋음, 왼쪽 = 싫음, 같은 쪽 다시 = 해제. 답 `{like:[],dislike:[]}`. rate 옵션에 `url` 을 넣으면 사진 아래에 '상세 보기' 링크가 붙는다.
- **나쁜 것만 걸러내는 카드는 `"mode":"reject"`** (`{"type":"rate","mode":"reject",...}`): 어디를 눌러도 '제외' 표시만 켰다 끄고, 누르는 법과 제외 수가 질문 아래에 항상 보인다. 답은 같은 모양(`dislike` 에 제외한 것, `like` 는 빈 배열)이라 '안 누른 것 = 남긴 것'으로 읽는다. `required` 여도 하나도 안 빼고 보낼 수 있고, `recommended` 는 이 모드에서 무시된다. 배지 글자는 `"labels":{"like":"살래","dislike":"빼기"}` 로 바꾼다(좋음/싫음이 뜻에 안 맞을 때). 클릭 설명을 `intro` 에 다시 쓰지 않는다. `multi` 옵션에 `img`를 넣으면 이미지 그리드 다중 선택. `aspect`는 image·multi·rate 그리드의 이미지 비율(기본 4/3).
- 로컬 파일은 절대경로, `~/`, 또는 스펙 파일 기준 상대경로(stdin 이면 현재 폴더 기준). 스펙에 적힌 파일만 서빙된다(화이트리스트). 지원: png jpg gif webp svg mp4 webm mov.
- 키보드: 숫자키 = 아직 손대지 않은 첫 선택 질문의 n번째 옵션, Enter = 전송, 여러 줄 입력칸에서는 Cmd/Ctrl+Enter = 전송.
- 로컬 페이지라 CSP 없음. 외부 URL 이미지, CDN 자유.
- 답 형식: `single`/`image` 문자열, `multi`/`rank` 배열, `scale` 숫자, `other`는 `"other:입력값"`.
- **`_note`**: 모든 질문 카드 아래에 'Claude에게 한마디' 칸이 자동으로 붙는다(클릭 = 전송 카드에서는 접힌 링크). 적으면 답에 `_note` 로 온다. 지시·되묻기·불만일 수 있으니 반드시 읽고, 무엇을 반영했는지 한 줄로 답한다. '덧붙일 말' 질문을 스펙에 따로 넣지 않는다(`id` 가 `note` 인 질문이 있으면 자동 칸은 생략). 끄려면 카드에 `"note":false`.
- **`_pass`**: `required` 질문에는 '판단 불가' 버튼이 붙고, 누르면 그 질문의 답이 `"_pass"` 로 온다. 억지 선택 대신 온 신호이므로 근거를 더 보여 주고 다시 묻거나, Claude 가 정하고 이유를 알린다.

## 패턴 예시
- **UI 변형 고르기**: Playwright로 변형별 스크린샷 → `image` 질문에 `img`로 넣고 `recommended` 표시. 움직임이 다르면 GIF.
- **취향 파악**: `show`로 "지금까지 파악한 취향" 마크다운 → `ask`로 scale 3개 + multi 1개 + text 1개(선택). 결과를 메모리에 저장.
- **설계 결정**: `mermaid`로 두 구조 → `single` 질문, 각 옵션 `desc`에 트레이드오프.
- **코드 리뷰 승인**: `diff` 블록 → `single` {적용(추천), 수정 요청, 보류} + `show_if` 수정 요청일 때 `text`.
- **긴 작업 보고**: 단계마다 `show`. 마지막에 결과 스크린샷 + "다음?" 질문.

## 설치된 프론트엔드 스킬과 함께 쓰기
- **frontend-design / prototype**: 방향·변형을 2~3개 만들면 설명하지 말고 `image` 질문에 `html`(라이브) 또는 스크린샷으로 넣어 고르게 한다. `recommended`로 추천안 표시.
- **web-design-guidelines / vercel-react-best-practices / review-animations**: 감사 결과는 `show`로 탭에 올리고(markdown 표), 고칠 항목은 `multi`로 고르게 한다.
- **animate / apple-design**: 모션 비교는 변형별 `html` 블록(실제 애니메이션 재생)으로. 스크린샷 금지. 복잡하면 GIF.
- **break-ui**: 깨진 케이스 스크린샷을 `compare`로 나란히.

## 주의
- 답이 끝나고 대기 중인 질문이 없으면 페이지가 스스로 탭을 닫는다. 열어두려면 그 `ask`/`show` 호출에 `ASK_UI_KEEP_OPEN=1`(세션별로 적용).
- 스레드 이력은 `~/.claude/ask-ui/threads/<세션>.json`에 저장(최근 30개, 12시간. 답이 없거나 Claude 가 아직 못 읽은 카드는 개수와 무관하게 7일). 데몬이 재시작돼도 이전 카드가 접힌 채로 복원된다. `stop`은 이력도 지운다.
- 대기 중인 질문은 데몬이 재시작돼도 살아 있다(7일까지). 열려 있던 탭에서 그대로 답할 수 있고 `wait <id>` 로 이어 받는다. 재시작 순간 멈춰 있던 `ask` 는 exit 1 로 끝나므로 같은 id 로 `wait` 한다.
- 탭이 없으면 새 탭을 연다(알림 없음). 탭이 살아 있으면 새 탭 대신 macOS 알림만. 페이지는 닫힐 때 `/bye`로 데몬에 알린다.
- 질문 카드를 띄우기 직전 터미널에 한 줄: "브라우저 탭에 올렸습니다. 고르면 바로 이어갑니다."
- 데몬은 3시간 유휴 후 자동 종료. 포트는 47821 고정(사용 중이면 임의 포트)이라 탭이 "연결 끊김"이어도 다음 `ask`가 새 데몬을 띄우면 같은 탭이 다시 붙는다.
- `ask_ui.py` 를 고치면 `VERSION` 을 올린다. 다음 호출 때 예전 데몬이 자동 교체되고(답을 기다리며 멈춘 `ask`/`wait` 가 없을 때만. 사용자가 답을 쓰던 카드가 있으면 그 탭은 보낸 뒤에 새 페이지를 받는다) 열린 탭도 새 페이지를 받는다. 고친 뒤 `python3 ~/.claude/skills/ask-ui/tests/test_ask_ui.py` 로 점검(임시 HOME 사용, 브라우저 안 엶).
- claude.ai artifact는 이 용도에 부적합: `watch`/댓글 알림은 cloud 세션만 깨우고, `db`는 MCP 폴링이 필요하다. 타인과 공유할 결과물일 때만 artifact.
