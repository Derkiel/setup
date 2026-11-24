#!/usr/bin/env python3
"""ask-ui 자체 점검. 임시 HOME 에서 데몬을 띄우므로 실제 이력과 브라우저는 건드리지 않는다.

    python3 ~/.claude/skills/ask-ui/tests/test_ask_ui.py
"""
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "ask_ui.py")
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                    "0000000d49444154789c6360606060000000050001a5f645400000000049454e44ae426082")


class AskUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="askui-test-")
        cls.env = dict(os.environ, HOME=cls.home, ASK_UI_KEEP_OPEN="1", ASK_UI_PORT="0")
        cls.env.pop("CLAUDE_CODE_SESSION_ID", None)
        cls.png = os.path.join(cls.home, "a.png")
        with open(cls.png, "wb") as f:
            f.write(PNG)

    @classmethod
    def tearDownClass(cls):
        cls.cli("stop")
        time.sleep(0.4)  # 데몬이 내려간 뒤 임시 HOME 을 치운다
        shutil.rmtree(cls.home, ignore_errors=True)

    @classmethod
    def cli(cls, *args, spec=None, session="t1"):
        """Run the CLI. Returns (exit code, parsed stdout or raw text, stderr)."""
        cmd = [sys.executable, SCRIPT] + list(args) + ["--session", session, "--no-open", "--quiet"]
        p = subprocess.run(cmd, input=json.dumps(spec) if spec is not None else None, capture_output=True, text=True,
                           env=cls.env, cwd=cls.home, timeout=40)
        try:
            out = json.loads(p.stdout)
        except ValueError:
            out = p.stdout
        return p.returncode, out, p.stderr

    def port(self):
        with open(os.path.join(self.home, ".claude", "ask-ui", "daemon.json")) as f:
            return json.load(f)["port"]

    def http(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port(), timeout=10)
        c.request(method, path, json.dumps(body) if body is not None else None, headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, r, data

    def answer(self, id_, session="t1", **kw):
        body = dict({"session": session, "id": id_, "status": "submitted", "answers": {}}, **kw)
        return json.loads(self.http("POST", "/answer", body)[2])

    def ask_async(self, spec, session="t1"):
        """Start a blocking ask; return (result holder, id of the pushed card)."""
        box = {}
        before = self.cli("status", session=session)[1].get("items", 0)
        th = threading.Thread(target=lambda: box.update(r=self.cli("ask", "-", "--timeout", "20", spec=spec, session=session)))
        th.start()
        for _ in range(100):
            time.sleep(0.05)
            st = self.cli("status", session=session)[1]
            if st.get("pending") and st.get("items", 0) > before:
                break
        ev = json.loads(self.http("GET", "/events?since=0&wait=0&s=" + session)[2])
        return box, th, ev["items"][-1]["id"], ev

    # ---- spec checks (no daemon needed)
    def test_bad_specs_fail_before_reaching_the_tab(self):
        bad = {"content": [{"type": "diff"}],
               "questions": [{"id": "a", "type": "single"}, {"id": "a", "type": "radio"},
                             {"type": "text", "show_if": {"q": "nope", "eq": 1}}]}
        code, out, err = self.cli("ask", "-", spec=bad)
        self.assertEqual(code, 1)
        text = " | ".join(out["problems"])
        for want in ("content[1] (diff) needs", "'a' (single) needs non-empty 'options'",
                     "used twice", "unknown type 'radio'", "show_if points at unknown question 'nope'"):
            self.assertIn(want, text)

    def test_relative_path_and_missing_id_are_fixed(self):
        code, out, _ = self.cli("show", "-", spec={"content": [{"type": "image", "src": "a.png"}]})
        self.assertEqual((code, out["status"]), (0, "shown"))
        ev = json.loads(self.http("GET", "/events?since=0&wait=0&s=t1")[2])
        self.assertEqual(ev["items"][-1]["content"][0]["src"], os.path.realpath(self.png))

    def test_missing_file_is_reported_but_the_card_still_goes_up(self):
        spec = {"content": [{"type": "image", "src": "missing.png"}, {"type": "image", "src": "https://example.com/x.png"}],
                "questions": [{"type": "single", "other": True}]}  # 선택지 없이 '기타'만 있는 질문은 허용
        code, out, err = self.cli("show", "-", spec=spec)
        self.assertEqual((code, out["status"], out["missing"]), (0, "shown", ["file not found: missing.png"]))
        self.assertIn("warning: file not found: missing.png", err)

    def test_ask_without_questions_returns_at_once(self):
        t0 = time.time()
        code, out, _ = self.cli("ask", "-", "--timeout", "20", spec={"title": "보고만"})
        self.assertEqual((code, out["status"]), (0, "shown"))
        self.assertLess(time.time() - t0, 5)

    def test_cancel_withdraws_a_pending_card(self):
        box, th, id_, _ = self.ask_async({"questions": [{"type": "text"}]}, session="t4")
        code, out, _ = self.cli("cancel", str(id_), session="t4")
        self.assertEqual((code, out["status"]), (0, "withdrawn"))
        th.join()
        self.assertEqual(box["r"][0], 3)
        ev = json.loads(self.http("GET", "/events?since=0&wait=0&s=t4")[2])
        self.assertEqual(ev["open"], [])  # 페이지는 이 목록을 보고 카드를 닫는다
        self.assertEqual(self.cli("cancel", str(id_), session="t4")[0], 1)

    # ---- late answers: the answer comes after the ask gave up
    def test_late_answer_is_handed_to_the_next_call_once(self):
        code, out, _ = self.cli("ask", "-", "--timeout", "1", spec={"title": "늦게 답할 카드", "questions": [{"type": "text"}]}, session="late")
        self.assertEqual((code, out["status"]), (2, "timeout"))
        id_ = out["id"]
        res = self.answer(id_, session="late", answers={"q1": "한참 뒤의 답"})
        self.assertEqual((res["ok"], res["waiting"]), (True, False))  # 페이지는 '저장됨'으로 표시
        self.assertEqual(self.cli("status", session="late")[1]["unread"], 1)
        code, out, _ = self.cli("show", "-", spec={"title": "다음 호출"}, session="late")
        late = out["late_answers"]
        self.assertEqual([(x["id"], x["title"], x["answers"]) for x in late], [(id_, "늦게 답할 카드", {"q1": "한참 뒤의 답"})])
        self.assertNotIn("late_answers", self.cli("show", "-", spec={"title": "그다음"}, session="late")[1])  # 한 번만

    def test_answer_read_by_a_waiting_ask_is_not_repeated(self):
        box, th, id_, _ = self.ask_async({"questions": [{"type": "text"}]}, session="ontime")
        self.assertTrue(self.answer(id_, session="ontime", answers={"q1": "a"})["waiting"])
        th.join()
        self.assertNotIn("late_answers", box["r"][1])
        self.assertNotIn("late_answers", self.cli("show", "-", spec={"title": "x"}, session="ontime")[1])

    def test_answer_after_the_ask_was_interrupted_is_kept_for_later(self):
        cmd = [sys.executable, SCRIPT, "ask", "-", "--session", "intr", "--no-open", "--quiet", "--timeout", "60"]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=self.home, text=True)
        p.stdin.write(json.dumps({"questions": [{"type": "text"}]}))
        p.stdin.close()
        for _ in range(100):
            time.sleep(0.05)
            if self.cli("status", session="intr")[1].get("waiting_total"):
                break
        p.kill()  # 사용자가 Claude 를 중단한 경우
        p.wait()
        p.stdout.close()
        p.stderr.close()
        for _ in range(80):  # 데몬은 5초 안에 끊긴 것을 알아챈다
            time.sleep(0.1)
            if not self.cli("status", session="intr")[1].get("waiting_total"):
                break
        self.assertFalse(self.answer(1, session="intr", answers={"q1": "중단 뒤의 답"})["waiting"])
        out = self.cli("show", "-", spec={"title": "x"}, session="intr")[1]
        self.assertEqual(out["late_answers"][0]["answers"], {"q1": "중단 뒤의 답"})

    def test_caller_cancel_is_not_reported_as_a_late_answer(self):
        code, out, _ = self.cli("ask", "-", "--timeout", "1", spec={"questions": [{"type": "text"}]}, session="wd")
        self.assertEqual(self.cli("cancel", str(out["id"]), session="wd")[0], 0)
        self.assertNotIn("late_answers", self.cli("show", "-", spec={"title": "x"}, session="wd")[1])

    def test_open_cards_outlive_the_card_limit_and_numbers_never_restart(self):
        code, out, _ = self.cli("ask", "-", "--timeout", "1", spec={"questions": [{"type": "text"}]}, session="keep")
        first = out["id"]
        for n in range(31):
            self.cli("show", "-", spec={"title": "진행 %d" % n}, session="keep")
        self.http("POST", "/stop", {})  # 데몬만 내린다(스레드 파일은 남는다)
        time.sleep(0.5)
        code, out, _ = self.cli("show", "-", spec={"title": "재시작 뒤"}, session="keep")
        self.assertEqual(out["id"], first + 32)
        self.assertTrue(self.answer(first, session="keep", answers={"q1": "아직 답할 수 있다"})["ok"])
        self.assertEqual(self.cli("show", "-", spec={"title": "x"}, session="keep")[1]["late_answers"][0]["id"], first)

    def test_stop_prints_unread_answers_before_deleting(self):
        code, out, _ = self.cli("ask", "-", "--timeout", "1", spec={"title": "지워지기 전", "questions": [{"type": "text"}]}, session="st")
        self.answer(out["id"], session="st", answers={"q1": "남겨 줘"})
        r = subprocess.run([sys.executable, SCRIPT, "stop"], env=self.env, cwd=self.home, capture_output=True, text=True)
        lines = r.stdout.strip().splitlines()
        self.assertEqual(lines[-1], "stopped")
        self.assertEqual(json.loads(lines[0])["late_answers"][0]["answers"], {"q1": "남겨 줘"})

    def test_compare_with_bad_items_is_a_problem_not_a_crash(self):
        code, out, _ = self.cli("show", "-", spec={"content": [{"type": "compare", "items": 5}]})
        self.assertEqual((code, out["problems"]), (1, ["content[1] (compare) needs 'items'"]))

    # ---- spec keys the page ignores
    def test_unknown_keys_warn_but_do_not_block(self):
        spec = {"title": "t", "screen": True, "questions": [{"type": "rate", "mode": "reject", "labels": {"dislike": "빼기"}, "colour": 1,
                                                             "options": [{"value": "a", "img": self.png, "pic": 1}]}]}
        code, out, err = self.cli("show", "-", spec=spec)
        self.assertEqual(code, 0)
        self.assertEqual(out["warnings"], ["unknown card key 'screen' is ignored", "unknown option key 'pic' is ignored",
                                           "unknown question key 'colour' is ignored"])
        self.assertIn("warning: unknown card key 'screen'", err)

    def test_event_log_records_the_life_of_a_card_without_its_contents(self):
        box, th, id_, _ = self.ask_async({"title": "기록 확인", "questions": [{"type": "text", "label": "비밀 질문"}]}, session="ev")
        self.answer(id_, session="ev", answers={"q1": "비밀 답"})
        th.join()
        with open(os.path.join(self.home, ".claude", "ask-ui", "events.jsonl"), encoding="utf-8") as f:
            text = f.read()
        rows = [json.loads(x) for x in text.splitlines()]
        mine = [r["kind"] for r in rows if r.get("session") == "ev"]
        self.assertEqual(mine, ["push", "seen", "answer", "read"])
        self.assertEqual([r["late"] for r in rows if r.get("session") == "ev" and r["kind"] == "answer"], [False])
        self.assertNotIn("비밀", text)
        self.assertIn("daemon", [r["kind"] for r in rows])

    def test_wait_needs_an_id(self):
        self.assertEqual(self.cli("wait")[0], 2)

    # ---- ask / answer round trip
    def test_ask_returns_the_answer_and_logs_it(self):
        box, th, id_, ev = self.ask_async({"title": "t", "questions": [{"type": "single", "options": ["x", "y"]}]})
        self.assertEqual(ev["items"][-1]["questions"][0]["id"], "q1")
        self.assertTrue(ev["keep"])
        self.assertTrue(ev["epoch"])
        self.assertEqual(ev["open"], [id_])
        st = self.cli("status")[1]
        self.assertEqual((st["delivered"], st["waiting_total"]), (id_, 1))  # 페이지가 받아 갔고, CLI 하나가 기다리는 중
        self.assertTrue(self.answer(id_, answers={"q1": "y"})["ok"])
        th.join()
        code, out, _ = box["r"]
        self.assertEqual((code, out["status"], out["answers"]), (0, "submitted", {"q1": "y"}))
        self.assertTrue(os.path.isfile(out["log"]))
        self.assertTrue(out["log"].startswith(os.path.realpath(self.home)) or out["log"].startswith(self.home))
        # 이미 끝난 카드에 다시 답하면 받지 않는다 → 페이지는 '만료됨'으로 표시
        self.assertFalse(self.answer(id_, answers={"q1": "x"})["ok"])

    def test_render_failure_reaches_the_cli_as_an_error(self):
        box, th, id_, _ = self.ask_async({"questions": [{"type": "text"}]}, session="t2")
        self.answer(id_, session="t2", status="error", error="render failed: boom")
        th.join()
        code, out, _ = box["r"]
        self.assertEqual((code, out["status"], out["error"]), (1, "error", "render failed: boom"))

    def test_skip_exits_3(self):
        box, th, id_, _ = self.ask_async({"questions": [{"type": "text"}]}, session="t3")
        self.answer(id_, session="t3", status="cancelled")
        th.join()
        self.assertEqual(box["r"][0], 3)

    # ---- the local server only talks to its own page and the CLI
    def test_other_origins_and_hosts_are_refused(self):
        self.cli("show", "-", spec={"title": "x"})
        push = {"session": "evil", "spec": {"title": "x"}}
        self.assertEqual(self.http("POST", "/push", push, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.http("POST", "/stop", {}, {"Origin": "null"})[0], 403)
        self.assertEqual(self.http("GET", "/health", headers={"Host": "evil.example:%d" % self.port()})[0], 403)
        own = "http://127.0.0.1:%d" % self.port()
        self.assertEqual(self.http("POST", "/bye", {"session": "t1"}, {"Origin": own})[0], 200)
        self.assertEqual(self.http("GET", "/health")[0], 200)

    def test_files_only_listed_media_with_ranges(self):
        self.cli("show", "-", spec={"content": [{"type": "image", "src": self.png}]})
        q = "/file?s=t1&p=" + os.path.realpath(self.png)
        status, r, data = self.http("GET", q)
        self.assertEqual((status, r.getheader("Content-Type"), data), (200, "image/png", PNG))
        status, r, data = self.http("GET", q, headers={"Range": "bytes=1-3"})
        self.assertEqual((status, data, r.getheader("Content-Range")), (206, PNG[1:4], "bytes 1-3/%d" % len(PNG)))
        self.assertEqual(self.http("GET", q, headers={"Range": "bytes=-4"})[2], PNG[-4:])
        self.assertEqual(self.http("GET", q, headers={"Range": "bytes=999-"})[0], 416)
        self.assertEqual(self.http("GET", "/file?s=t1&p=" + SCRIPT)[0], 403)
        self.assertEqual(self.http("GET", "/file?s=t1&p=/etc/hosts")[0], 403)

    # ---- daemon lifecycle
    def test_second_daemon_does_not_take_over(self):
        self.cli("show", "-", spec={"title": "x"})
        pid = self.cli("status")[1]["pid"]
        p = subprocess.run([sys.executable, SCRIPT, "serve"], env=self.env, timeout=10)
        self.assertEqual(p.returncode, 0)  # 잠금을 못 잡고 바로 끝난다
        self.assertEqual(self.cli("status")[1]["pid"], pid)

    def test_zz_older_daemon_is_replaced_and_history_survives(self):
        self.cli("show", "-", spec={"title": "before upgrade"}, session="up")
        self.cli("stop")  # stop 은 스레드 이력도 지우므로 아래에서 다시 만든다
        code = "import sys;sys.argv=['x'];sys.path.insert(0,%r);import ask_ui;ask_ui.VERSION=-1;ask_ui.run_daemon(0)" % os.path.dirname(SCRIPT)
        old = subprocess.Popen([sys.executable, "-c", code], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                time.sleep(0.1)
                st = self.cli("status")[1]
                if st.get("running"):
                    break
            self.assertEqual(st["version"], -1)
            self.http("POST", "/push", {"session": "up", "spec": {"title": "kept"}})
            lost = json.loads(self.http("POST", "/push", {"session": "up", "spec": {"questions": [{"id": "q", "type": "text"}]}})[2])["id"]
            code, out, _ = self.cli("show", "-", spec={"title": "after upgrade"}, session="up")
            self.assertEqual(code, 0)
            st = self.cli("status", session="up")[1]
            self.assertNotEqual(st["pid"], old.pid)
            self.assertEqual(st["items"], 3)  # 예전 데몬에 있던 카드가 새 데몬에서 복원됐다
            # 대기 중이던 질문은 데몬이 바뀌어도 살아 있다: 늦게 온 답을 wait 로 받는다
            self.assertEqual(st["pending"], 1)
            self.assertTrue(self.answer(lost, session="up", answers={"q": "늦은 답"})["ok"])
            code, out, _ = self.cli("wait", str(lost), session="up")
            self.assertEqual((code, out["answers"]), (0, {"q": "늦은 답"}))
            self.assertEqual(old.wait(timeout=5), 0)
        finally:
            if old.poll() is None:
                old.kill()


if __name__ == "__main__":
    unittest.main(verbosity=1)
