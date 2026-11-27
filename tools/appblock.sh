#!/bin/zsh
# appblock: 켜 두면 목록의 앱을 실행하는 순간 강제 종료한다(창이 안 뜨고 포커스도 안 넘어간다). 끌 때까지, 재부팅해도 유지된다.
# 목록: ~/.config/appblock/apps 에 한 줄에 앱 하나. 이름(Google Chrome, 메모, zoom.us)이나 번들 ID(com.apple.Notes).
#   이름은 Finder 응용 프로그램 폴더에 보이는 그대로, 전체가 일치해야 한다(대소문자 무관). "Chrome"은 안 되고 "Google Chrome".
#   틀린 이름은 켤 때 알림에 "못 찾음"으로 나온다. 켜진 상태에서 고쳐도 저장하면 몇 초 안에 반영된다.
# BTT 연결: 단축키 추가 → 액션 "Execute Shell Script / Task" → ~/.local/bin/appblock toggle
# 직접 실행: appblock [toggle|on|off|status]
zmodload zsh/datetime; BORN=$EPOCHREALTIME  # 목록을 읽기 직전의 시각 (감시 프로세스가 쓴다. 목록을 읽는 줄보다 위에 있어야 한다)

LABEL=local.appblock
PATH=/usr/bin:/bin
SELF=${0:a}  # 링크를 풀지 않는다: launchd에는 설치 위치(~/.local/bin/appblock)가 등록되어, 원본 폴더를 옮겨도 링크만 다시 걸면 된다
SVC=gui/$UID/$LABEL
PLIST=$HOME/Library/LaunchAgents/$LABEL.plist
LIST=$HOME/.config/appblock/apps
# 목록 읽기: #으로 시작하는 줄과 빈 줄은 건너뛰고, 습관대로 붙인 따옴표와 끝의 쉼표는 떼어 낸다.
APPS=(${(f)"$(sed -e '/^[[:space:]]*#/d' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*,\{0,1\}[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' $LIST 2>/dev/null)"})

say() { print -r -- "$1"; osascript -e 'on run a' -e 'display notification (item 1 of a) with title "앱 차단"' -e 'end run' "$1" &>/dev/null }
loaded() { launchctl print $SVC &>/dev/null }
running() { launchctl print $SVC 2>/dev/null | grep -q 'state = running' }

# launchd가 실행하는 감시 프로세스(osascript JXA). 앱 실행 알림을 받아 즉시 종료하고, 5초마다 전체를 한 번 더 훑는다.
# 인자: 목록 파일 경로, 시작 시각, 앱 이름들
JXA='
ObjC.import("AppKit");
function run(argv) {
  // NFC: Finder에서 복사한 한글 이름은 자모가 풀린 형태(NFD)일 수 있다.
  const norm = s => s.normalize("NFC").toLowerCase().replace(/\.app$/, "");
  const KEYS = ["bundleIdentifier", "localizedName", "bundleURL.lastPathComponent"];
  // 앱 목록을 키별로 한 번에 읽는다: 앱마다 따로 읽으면 CPU를 두 배 넘게 쓴다(실측).
  // 값에 줄바꿈이 들어 있어 개수가 안 맞으면 그 키는 건너뛴다: 순서가 밀려 목록에 없는 앱을 종료하면 안 된다.
  const each = (apps, f) => KEYS.forEach(k => {
    const v = apps.valueForKeyPath(k).componentsJoinedByString("\n").js.split("\n");
    if (v.length === Number(apps.count)) v.forEach(f); // JXA는 count를 문자열로 준다
  });
  const all = () => $.NSWorkspace.sharedWorkspace.runningApplications;
  const fm = $.NSFileManager.defaultManager;
  const list = argv[0];
  const want = new Set(argv.slice(2).map(norm).filter(Boolean));
  const scan = apps => each(apps, (v, i) => { if (want.has(norm(v))) apps.objectAtIndex(i).forceTerminate; });
  const stamp = () => {
    const a = fm.attributesOfItemAtPathError(list, $());
    return a.isNil() ? null : a.fileModificationDate.timeIntervalSince1970;
  };
  ObjC.registerSubclass({ name: "AppBlockObserver", methods: { "launched:": { types: ["void", ["id"]],
    implementation: n => scan($.NSArray.arrayWithObject(n.userInfo.objectForKey("NSWorkspaceApplicationKey"))) } } });
  const observer = $.AppBlockObserver.alloc.init, center = $.NSWorkspace.sharedWorkspace.notificationCenter;
  ["NSWorkspaceWillLaunchApplicationNotification", "NSWorkspaceDidLaunchApplicationNotification"]
    .forEach(name => center.addObserverSelectorNameObject(observer, "launched:", name, $()));
  const started = stamp();
  scan(all());
  // zsh가 목록을 읽은 뒤 여기 오기 전에 또 저장됐으면 옛 목록을 들고 있는 것이므로 다시 시작한다.
  // 시작 시각(argv[1])은 목록을 읽기 전에 잰 것이라, 그보다 먼저 저장된 목록은 이미 읽은 것이다(여유를 두면 저장 직후에 켤 때 죽는다).
  if (started >= Number(argv[1]) && started <= Date.now() / 1000) return;
  for (;;) {
    $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(5));
    const now = stamp();
    if (now !== null && now !== started) return; // 목록이 수정됨: 종료하면 launchd가 새 목록으로 다시 띄운다.
    scan(all());
  }
}'

# 즉시 차단 보조 프로그램(C 소스). 감시 프로세스는 앱이 시스템에 등록된 뒤(실행 약 0.1초 뒤)에야 알림을 받아서
# 그 사이에 포커스가 한 번 넘어갔다 온다. 이 프로그램은 launchd가 프로세스를 만드는 순간을 kqueue로 받아
# 앱 실행 파일이 올라오자마자(실측 약 0.01초) 종료한다: 앱이 등록되기 전이라 창도 안 뜨고 포커스도 안 바뀐다.
# 인자: 감시 프로세스 pid, 앱 이름들
fast_src() { cat <<'EOF'
#include <CoreFoundation/CoreFoundation.h>
#include <libproc.h>
#include <sys/event.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>

enum { MAXPID = 100000 };
static CFMutableArrayRef want;

// 감시 프로세스(JXA)의 norm과 같은 규칙: NFC, 소문자, 끝의 .app 제거
static CFStringRef norm(CFStringRef s) {
  CFMutableStringRef m = CFStringCreateMutableCopy(NULL, 0, s);
  CFStringNormalize(m, kCFStringNormalizationFormC);
  CFStringLowercase(m, NULL);
  if (CFStringHasSuffix(m, CFSTR(".app"))) CFStringDelete(m, CFRangeMake(CFStringGetLength(m) - 4, 4));
  return m;
}

static int wanted(CFStringRef s) {
  if (!s) return 0;
  CFStringRef n = norm(s);
  int hit = CFArrayContainsValue(want, CFRangeMake(0, CFArrayGetCount(want)), n);
  CFRelease(n);
  return hit;
}

// 앱(".../X.app")의 파일 이름, 번들 ID, 표시 이름 중 하나가 목록에 있는가
static int listed(const char *app) {
  CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)app, (CFIndex)strlen(app), true);
  if (!url) return 0;
  CFStringRef file = CFURLCopyLastPathComponent(url), shown = NULL;
  CFBundleRef bundle = NULL;
  // 빠른 것부터 본다: 파일 이름은 문자열 비교뿐이고, 번들 ID와 표시 이름은 디스크를 읽는다.
  int hit = wanted(file)
      || ((bundle = CFBundleCreate(NULL, url)) && wanted(CFBundleGetIdentifier(bundle)))
      || (CFURLCopyResourcePropertyForKey(url, kCFURLLocalizedNameKey, &shown, NULL) && wanted(shown));
  if (shown) CFRelease(shown);
  if (bundle) CFRelease(bundle);
  CFRelease(file);
  CFRelease(url);
  return hit;
}

// 실행 파일이 ".../X.app/Contents/MacOS/실행파일"이고 X가 목록에 있으면 종료한다.
static void check(pid_t pid) {
  static const char mid[] = ".app/Contents/MacOS";
  const size_t m = sizeof mid - 1;
  char path[PROC_PIDPATHINFO_MAXSIZE];
  if (proc_pidpath(pid, path, sizeof path) <= 0) return;
  char *exe = strrchr(path, '/');
  if (!exe || (size_t)(exe - path) < m || strncmp(exe - m, mid, m)) return;
  *(exe - m + 4) = 0; // path = ".../X.app"
  if (listed(path)) kill(pid, SIGKILL);
}

int main(int argc, char **argv) {
  if (argc < 3) return 2;
  want = CFArrayCreateMutable(NULL, 0, &kCFTypeArrayCallBacks);
  for (int i = 2; i < argc; i++) {
    CFStringRef s = CFStringCreateWithCString(NULL, argv[i], kCFStringEncodingUTF8);
    if (!s) continue;
    CFStringRef n = norm(s);
    CFArrayAppendValue(want, n);
    CFRelease(n);
    CFRelease(s);
  }
  // 표시 이름을 처음 읽을 때만 약 0.01초가 걸린다(실측). 첫 차단이 늦지 않게 미리 한 번 읽어 둔다.
  listed("/System/Library/CoreServices/Finder.app");
  pid_t watcher = atoi(argv[1]);
  int kq = kqueue();
  struct kevent ev[2], e;
  EV_SET(&ev[0], 1, EVFILT_PROC, EV_ADD, NOTE_FORK, 0, NULL);       // launchd가 프로세스를 만들 때
  EV_SET(&ev[1], watcher, EVFILT_PROC, EV_ADD, NOTE_EXIT, 0, NULL); // 감시 프로세스가 끝날 때
  if (kq < 0 || kevent(kq, ev, 2, NULL, 0, NULL) < 0) return 1;

  static unsigned char known[2][MAXPID];
  static pid_t pids[MAXPID];
  int cur = 0, n = proc_listallpids(pids, sizeof pids);
  for (int i = 0; i < n; i++) if (pids[i] > 0 && pids[i] < MAXPID) known[cur][pids[i]] = 1;
  for (;;) {
    if (kevent(kq, NULL, 0, &e, 1, NULL) < 1) continue;
    if (e.ident == (uintptr_t)watcher) return 0;            // 감시 프로세스와 같이 끝난다
    if (e.ident != 1) { check((pid_t)e.ident); continue; } // 새 프로세스가 실행 파일을 올림(exec)
    // launchd가 프로세스를 만듦: 직전 목록에 없던 pid를 지금 한 번 보고, 실행 파일을 올릴 때 다시 보도록 건다.
    // (launchd가 만든 직후에는 아직 앱이 아니라 xpcproxy이고, 실측 약 0.01초 뒤에 앱 실행 파일로 바뀐다.)
    int next = !cur;
    memset(known[next], 0, sizeof known[next]);
    n = proc_listallpids(pids, sizeof pids);
    for (int i = 0; i < n; i++) {
      pid_t p = pids[i];
      if (p <= 1 || p >= MAXPID) continue;
      known[next][p] = 1;
      if (known[cur][p]) continue;
      check(p);
      EV_SET(&ev[0], p, EVFILT_PROC, EV_ADD, NOTE_EXEC, 0, NULL);
      kevent(kq, ev, 1, NULL, 0, NULL);
    }
    cur = next;
  }
}
EOF
}

# 보조 프로그램의 경로를 출력한다. 없으면 컴파일한다(처음 한 번). 실패하면 감시 프로세스만으로 막는다.
fast_bin() {
  # 실행 파일에 내장할 Info.plist. 이게 없으면 실행 파일이 놓인 위치에 따라 앱의 표시 이름이 영어로 읽혀서
  # 한글로 적은 이름("메모")이 맞지 않는다(실측).
  local plist='<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleIdentifier</key><string>local.appblock.fast</string><key>CFBundleAllowMixedLocalizations</key><true/></dict></plist>'
  local src=$(fast_src) sum
  sum=$(cksum <<<$src$plist)
  local bin=$HOME/Library/Caches/appblock/fast-${sum%% *}  # 소스가 바뀌면 이름이 바뀌어 다시 컴파일된다
  if [[ ! -x $bin ]]; then
    xcode-select -p &>/dev/null || return 1  # 컴파일러가 없으면 clang이 설치 안내 창을 띄우므로 부르지 않는다
    mkdir -p ${bin:h} && rm -f ${bin:h}/fast-*(N) && print -r -- $plist > $bin.plist
    clang -O2 -x c -o $bin.$$ - -framework CoreFoundation -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker $bin.plist <<<$src 2>/dev/null && mv -f $bin.$$ $bin
    rm -f $bin.plist $bin.$$
    [[ -x $bin ]] || return 1
  fi
  print -r -- $bin
}
# 보조 프로그램이 지금 돌고 있는가
fast_on() {
  local pid=$(launchctl print $SVC 2>/dev/null | awk '$1 == "pid" { print $3; exit }')
  [[ -n $pid ]] && pgrep -qf "/appblock/fast-[0-9]+ $pid "
}

# 설치된 앱 중에 없는 이름을 출력한다(Spotlight 조회). 틀린 이름도 막지는 않고 켤 때 알리기만 한다.
missing() {
  local app='kMDItemContentType == "com.apple.application-bundle"' a n out=()
  # Spotlight 색인이 꺼져 있으면 전부 못 찾음으로 나오므로 판단하지 않는다.
  [[ -n "$(mdfind "$app && kMDItemCFBundleIdentifier == 'com.apple.finder'" 2>/dev/null)" ]] || return
  for a in $APPS; do
    n=${${a%.app}//\'/\\\'}
    [[ -n "$(mdfind "$app && (kMDItemDisplayName == '$n'c || kMDItemFSName == '$n.app'c || kMDItemCFBundleIdentifier == '$n'c)" 2>/dev/null)" ]] || out+=($a)
  done
  print -r -- ${(j:, :)out}
}

on() {
  if (( ! $#APPS )); then
    # 목록 파일이 아직 없으면 안내를 적은 파일을 만들어 편집기로 연다.
    [[ -e $LIST ]] || { mkdir -p ${LIST:h} && print -r -- "# 차단할 앱을 한 줄에 하나씩 적는다. 예: Google Chrome, 메모, zoom.us, com.apple.Notes
# 이름은 Finder 응용 프로그램 폴더에 보이는 그대로. 저장하면 켜진 상태에서도 몇 초 안에 반영된다." > $LIST && open -t $LIST }
    say "차단할 앱이 없음: $LIST 에 한 줄에 하나씩 적기"
    return 1
  fi
  local xmlpath=${${SELF//&/&amp;}//</&lt;}
  local plist="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$xmlpath</string><string>watch</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>"
  # 내용이 같으면 다시 쓰지 않는다: 쓸 때마다 macOS가 "백그라운드 항목 추가됨" 알림을 띄울 수 있다.
  mkdir -p ${PLIST:h}
  [[ -f $PLIST && "$(<$PLIST)" == "$plist" ]] || print -r -- "$plist" > $PLIST
  fast_bin >/dev/null  # 처음이면 여기서 컴파일해 둔다
  launchctl enable $SVC
  launchctl bootstrap gui/$UID $PLIST 2>/dev/null
  repeat 30; do running && break; sleep 0.1; done
  running || { say "켜기 실패: launchctl print $SVC 로 확인"; return 1 }
  local miss=$(missing) slow=" / 즉시 차단 불가: 창이 잠깐 뜰 수 있음"
  repeat 10; do fast_on && { slow=; break }; sleep 0.1; done
  say "차단 켜짐: ${(j:, :)APPS}${miss:+ / 못 찾음(이름 확인): $miss}$slow"
}

off() {
  # disable까지 해야 재부팅 후에도 꺼진 상태가 유지된다.
  launchctl disable $SVC
  launchctl bootout $SVC 2>/dev/null
  repeat 30; do loaded || { say "차단 꺼짐"; return 0 }; sleep 0.1; done
  say "끄기 실패: launchctl print $SVC 로 확인"
  return 1
}

case ${1:-toggle} in
  toggle) if loaded; then off; else on; fi ;;
  on) on ;;
  off) off ;;
  status) if running; then print -r -- "켜짐$(fast_on || print -rn -- "(즉시 차단 불가)"): ${(j:, :)APPS}"; elif loaded; then print -r -- "켜짐이지만 감시 프로세스가 죽어 있음"; else print -r -- "꺼짐"; fi ;;
  watch)  # launchd가 실행한다: 보조 프로그램을 옆에 띄우고 감시 프로세스가 된다
    { bin=$(fast_bin) && exec $bin $$ "${APPS[@]}" } &!
    exec osascript -l JavaScript -e "$JXA" "$LIST" "$BORN" "${APPS[@]}" ;;
  *) print -r -- "사용: $0 [toggle|on|off|status]"; exit 2 ;;
esac
