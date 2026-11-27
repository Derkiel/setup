#!/bin/zsh
# appblock.sh 실동작 테스트. 복사본(라벨, 목록 파일 위치, 알림만 바꿈)으로 체스와 스티커를 실제로 띄워 본다.
# 진짜 차단 설정(local.appblock, ~/.config/appblock/apps)은 건드리지 않는다. 실행: ./test_appblock.sh (약 80초)
PATH=/usr/bin:/bin
SRC=${0:A:h}/appblock.sh
T=$(mktemp -d)
AB=$T/appblock.sh
LIST=$T/apps
LABEL=local.appblock.test
fail=0

pgrep -x Chess >/dev/null || pgrep -x Stickies >/dev/null && { print "체스나 스티커가 이미 실행 중이라 테스트하지 않음"; exit 2 }

cleanup() {
  launchctl bootout gui/$UID/$LABEL 2>/dev/null
  rm -rf $T $HOME/Library/LaunchAgents/$LABEL.plist
  pkill -x Chess; pkill -x Stickies
}
trap cleanup EXIT

# 편집기를 띄우는 부분(open -t)은 뺀다. 치환이 하나라도 안 먹으면 진짜 설정을 건드리게 되므로 그만둔다.
sed -e "s/^LABEL=.*/LABEL=$LABEL/" -e "s|^LIST=.*|LIST=$LIST|" -e 's/^say() .*/say() { print -r -- "$1" }/' -e 's/ && open -t \$LIST//' $SRC > $AB
grep -qx "LABEL=$LABEL" $AB && grep -qx "LIST=$LIST" $AB && ! grep -q -e 'open -t' -e 'display notification' $AB || { print "테스트용 복사본을 만들지 못함"; exit 2 }
chmod +x $AB

check() { if eval "$2"; then print "ok   $1"; else print "FAIL $1"; fail=1; fi }
alive() { pgrep -x $1 >/dev/null }
wpid() { launchctl print gui/$UID/$LABEL 2>/dev/null | awk '$1 == "pid" { print $3; exit }' }  # 감시 프로세스
helper() { pgrep -f "/appblock/fast-[0-9]+ $(wpid) " }                                          # 즉시 차단 보조 프로그램
# 주어진 초 동안 앱의 시스템 등록(WillLaunch)과 활성화(DidActivate) 알림을 "알림이름 번들ID"로 기록한다.
OBS='ObjC.import("AppKit"); function run(argv) { const log = [];
  ObjC.registerSubclass({ name: "TestObserver", methods: { "ev:": { types: ["void", ["id"]], implementation: n => {
    const a = n.userInfo.objectForKey("NSWorkspaceApplicationKey"); log.push(n.name.js + " " + (a.isNil() ? "" : ObjC.unwrap(a.bundleIdentifier))); } } } });
  const o = $.TestObserver.alloc.init, c = $.NSWorkspace.sharedWorkspace.notificationCenter;
  ["WillLaunch", "DidActivate"].forEach(x => c.addObserverSelectorNameObject(o, "ev:", "NSWorkspace" + x + "ApplicationNotification", $()));
  $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(parseFloat(argv[0]))); return log.join("\n"); }'
# 앱을 3번 실행하는 동안 그 앱이 한 번도 등록·활성화되지 않았는가 (포커스가 넘어가지 않았는가)
unseen() { osascript -l JavaScript -e "$OBS" 5 > $T/ev.txt & sleep 1.5; repeat 3; do open -a $1; sleep 1; done; wait; ! alive $1 && ! grep $2 $T/ev.txt }
# 감시 프로세스가 새 것으로 바뀌고 보조 프로그램까지 뜰 때까지 기다린다(최대 20초). 걸린 시간을 출력한다.
reloaded() { local old=$1 i; for i in {1..40}; do sleep 0.5; [[ -n $(wpid) && $(wpid) != $old ]] && helper >/dev/null && { print "     ($((i / 2)).$((i % 2 * 5))초 걸림)"; return 0 }; done; return 1 }

check "목록 파일이 없으면 안내를 적은 파일을 만들고 켜지지 않는다" '! $AB on >/dev/null && grep -q "^# " $LIST && [[ $($AB status) == 꺼짐 ]]'
check "꺼진 상태에서는 앱이 켜진다" 'open -a Chess; sleep 1.5; alive Chess'
print -r -- $'\n  "Chess",\nZoom-오타' >> $LIST
check "켜기 성공: 주석·빈 줄·따옴표·쉼표를 걸러 읽고, 틀린 이름만 못 찾음으로 알려준다" 'out=$($AB on) && [[ $out == "차단 켜짐: Chess, Zoom-오타 / 못 찾음(이름 확인): Zoom-오타" ]]'
check "켜는 순간 이미 떠 있던 앱이 종료된다" 'sleep 1; ! alive Chess'
check "상태 표시가 켜짐, 즉시 차단 보조 프로그램이 돌고 있다" '[[ $($AB status) == "켜짐: Chess, Zoom-오타" ]] && helper >/dev/null'
check "실행해도 포커스가 넘어가지 않는다 (파일 이름으로 적은 앱, 3회)" 'unseen Chess com.apple.Chess'
check "보조 프로그램이 죽어도 기존 방식으로 막고, 상태에 표시된다" 'kill $(helper); sleep 0.3; open -a Chess; sleep 1; ! alive Chess && [[ $($AB status) == *"즉시 차단 불가"* ]]'
for i in 1 2 3; do check "실행 즉시 종료 (${i}회차, 1초 안)" 'open -a Chess; sleep 1; ! alive Chess'; done
check "감시 프로세스를 죽여도 되살아나 막는다" 'old=$(wpid); kill $old; reloaded $old && open -a Chess && sleep 1 && ! alive Chess'
nfd=$(print -rn 스티커 | iconv -f UTF-8 -t UTF-8-MAC)  # Finder에서 복사한 것처럼 자모가 풀린 한글 이름
check "테스트용 이름이 실제로 자모가 풀린 형태다" '[[ $nfd != 스티커 ]]'
sleep 11  # 감시 프로세스가 뜬 지 10초가 안 됐으면 launchd가 다시 띄우기를 늦춘다. 평소처럼 오래 켜져 있던 상태에서 잰다.
check "목록 파일을 고쳐 저장하면 다시 켜지 않아도 반영된다 (자모 풀린 한글 이름)" 'old=$(wpid); print -r -- $nfd >> $LIST; reloaded $old && open -a Stickies && sleep 1.5 && ! alive Stickies'
check "실행해도 포커스가 넘어가지 않는다 (한글 표시 이름으로 적은 앱, 3회)" 'unseen Stickies com.apple.Stickies'
check "toggle 로 꺼진다" '$AB toggle >/dev/null; [[ $($AB status) == 꺼짐 ]]'
check "끄면 앱이 다시 켜진다" 'open -a Chess; sleep 1.5; alive Chess'
check "toggle 로 다시 켜지고 앱이 종료된다" '$AB toggle >/dev/null; sleep 1; ! alive Chess'
check "off 로 꺼진다" '$AB off >/dev/null; [[ $($AB status) == 꺼짐 ]]'
check "목록을 저장한 직후에 켜도 감시 프로세스가 죽지 않는다" 'print -r -- Chess > $LIST; $AB on >/dev/null; sleep 1.5; [[ $($AB status) == "켜짐: Chess" ]] && $AB off >/dev/null'
check "목록이 비면 켜지지 않는다" ': > $LIST; ! $AB on >/dev/null; [[ $($AB status) == 꺼짐 ]]'

(( fail )) && print "실패 있음" || print "전부 통과"
exit $fail
