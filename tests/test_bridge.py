import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from muse_cli import bridge, demo
from muse_cli.gateway import AuthError, GatewayError

NOT_FOUND = '{"ok":false,"error":{"code":"not_found","message":"session not found"}}'


def ev(seq, role="assistant", text="hi", status="completed", reply_to="", data=None,
       at=None, session_id=None):
    mid = f"{role}-msg-{seq}"
    payload = {"display_text": text, "content": text, "role": role, "message_id": mid,
               "reply_to_message_id": reply_to, "session_id": session_id or "main-uuid",
               "is_thread": bool(session_id)}
    if status:
        payload["status"] = status
    if data:
        payload["data"] = data
    e = {"event_name": f"message.{role}", "seq": seq, "message_id": mid, "role": role,
         "occurred_at_ms": 1794117896000 + seq if at is None else at,
         "display_text_updated_at_ms": 1794117899999, "reply_to_message_id": reply_to,
         "resources": [], "payload": payload}
    return e


def widget(seq, kind, text="", data=None, fallback=None, wid=None):
    mid = f"widget-msg-{seq}"
    payload = {"kind": kind, "id": wid or f"w{seq}", "role": "assistant", "message_id": mid,
               "display_text": text, "fallback_text": text if fallback is None else fallback,
               "data": data or {}, "state": {"data": {}, "version": 0}}
    return {"event_name": "delta.presentation", "seq": seq, "message_id": mid, "role": "assistant",
            "occurred_at_ms": 1794117896000 + seq, "reply_to_message_id": "", "resources": [],
            "payload": payload}


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeGW:
    vm_id = "vm-1"

    def __init__(self):
        self.events = []
        self.fail = None
        self.calls = []
        self.opened = []

    def call_json(self, method, path_params=None, body=None, query=None, timeout=30):
        self.calls.append((method, body))
        if self.fail:
            raise self.fail
        if method == "chat.history":
            evs = list(self.events)
            if body.get("before_seq"):
                evs = [e for e in evs if e["seq"] < body["before_seq"]]
            return {"chat_events": evs[-body.get("limit", 20):]}
        if method == "chat.unread_count":
            return {"unread_count": 2}
        if method == "identity":
            return {"name": "Muse"}
        return {}

    def _open(self, method, path_params=None, body=None, query=None):
        self.opened.append((method, body))
        return 3

    def close(self):
        pass


def make(gw=None, clock=None):
    events = []
    gw = gw or FakeGW()
    clock = clock or Clock()
    b = bridge.Backend(lambda name, data: events.append((name, data)), clock=clock,
                       connect=lambda cfg: gw, cfg={"node_id": "n1", "cookies_file": "x"})
    st = {"session_id": None, "title": "main chat"}
    b.load_state = lambda: dict(st)
    b.save_state = lambda s: st.update(s)
    return b, gw, clock, events


def names(events):
    return [n for n, _ in events]


class MessageMappingTest(unittest.TestCase):
    def test_final_reply_with_image(self):
        img = {"path": "sandbox://workspace/cat.png", "mime": "image/png", "byte_len": 123,
               "label": "cat", "variants": {"original": "https://x/media/raw/workspace/cat.png"}}
        m = bridge.to_message(ev(5, text="Here", data={"images": [img]}))
        self.assertEqual(m, {"seq": 5, "id": "assistant-msg-5", "role": "assistant",
                             "text": "Here", "at_ms": 1794117896005, "final": True,
                             "push": False,
                             "files": [{"path": "sandbox://workspace/cat.png", "kind": "image",
                                        "mime": "image/png", "label": "cat", "byte_len": 123}],
                             "choices": [], "card": None, "widget": False})

    def test_option_widget_becomes_choices(self):
        e = ev(10, text="Which one?\n\n[hatch_widget:widget-abc]\n\nTell me.")
        e["payload"]["widgets"] = [
            {"kind": "option", "widget_id": "widget-abc", "data": {"options": ["Red", "Blue", 3]},
             "state": {"data": {}, "version": 0}},
            {"kind": "map", "widget_id": "widget-map", "data": {}}]
        m = bridge.to_message(e)
        self.assertEqual(m["text"], "Which one?\n\n\n\nTell me.")
        self.assertEqual(m["choices"], [{"id": "widget-abc", "options": ["Red", "Blue"], "selected": None}])
        e["payload"]["widgets"][0]["state"] = {"data": {"selectedText": "Blue"}, "version": 1}
        self.assertEqual(bridge.to_message(e)["choices"][0]["selected"], "Blue")
        e["payload"]["display_text"] = e["payload"]["content"] = "Pick one\n\n[[hatch_widget:widget-abc]]"
        self.assertEqual(bridge.to_message(e)["text"], "Pick one")

    def test_user_attachment_becomes_a_file(self):
        e = ev(11, role="user", status=None,
               text="[image:image/jpeg workspace/uploads/u1/shot.jpg] what is this?")
        e["payload"]["metadata"] = {"attachments": [
            {"path": "workspace/uploads/u1/shot.jpg", "mime_type": "image/jpeg",
             "filename": "image_0.jpg", "bytes_len": 2048}]}
        m = bridge.to_message(e)
        self.assertEqual(m["text"], "what is this?")
        self.assertEqual(m["files"], [{"path": "sandbox://workspace/uploads/u1/shot.jpg", "kind": "image",
                                       "mime": "image/jpeg", "label": "image_0.jpg", "byte_len": 2048}])
        e["payload"]["display_text"] = e["payload"]["content"] = "[image:image/jpeg workspace/uploads/u1/shot.jpg]"
        self.assertEqual(bridge.to_message(e)["text"], "")

    def test_draft_push_user_and_fallback_time(self):
        self.assertFalse(bridge.to_message(ev(6, status=None))["final"])
        self.assertTrue(bridge.to_message(ev(7, reply_to="assistant-msg-7"))["push"])
        user = bridge.to_message(ev(8, role="user", status=None, at=0))
        self.assertEqual((user["role"], user["final"], user["push"]), ("user", True, False))
        self.assertEqual(user["at_ms"], 1794117899999)

    def test_skips_other_events_and_empty_messages(self):
        self.assertIsNone(bridge.to_message({"event_name": "agent.status", "seq": 1}))
        self.assertIsNone(bridge.to_message(ev(9, text="")))

    def test_presented_image_becomes_a_widget_message(self):
        img = {"path": "sandbox://workspace/imagine_media/sq.webp", "mime": "image/webp",
               "byte_len": 17394, "label": "blue square", "missing": False}
        m = bridge.to_message(widget(12, "image", text="blue square",
                                     data={"fallback_text": f"![blue square]({img['path']})", "images": [img]}))
        self.assertEqual(m, {"seq": 12, "id": "widget-msg-12", "role": "assistant", "text": "",
                             "at_ms": 1794117896012, "final": True, "push": False,
                             "files": [{"path": img["path"], "kind": "image", "mime": "image/webp",
                                        "label": "blue square", "byte_len": 17394}],
                             "choices": [], "card": None, "widget": True})

    def test_presented_file_keeps_its_details(self):
        f = {"path": "sandbox://workspace/seats.pdf", "mime": "application/pdf",
             "byte_len": 667438, "label": "Seat map PDF"}
        m = bridge.to_message(widget(13, "file", text="Seat map PDF",
                                     data={"fallback_text": f"[Seat map PDF]({f['path']})", "file": f}))
        self.assertEqual(m["files"], [{"path": f["path"], "kind": "file", "mime": "application/pdf",
                                       "label": "Seat map PDF", "byte_len": 667438}])

    def test_presented_links_and_tasks_become_cards(self):
        link = bridge.to_message(widget(14, "external_link", text="[Start the survey](https://e.com/s?a=1)",
                                        data={"url": "https://e.com/s?a=1"}))
        self.assertEqual(link["card"], {"id": "w14", "kind": "external_link", "title": "Start the survey",
                                        "subtitle": None, "url": "https://e.com/s?a=1", "status": None})
        conn = bridge.to_message(widget(15, "internal_link_action_card", text="",
                                        fallback="[Connect Google Calendar](https://agent.meta.ai/c/gc)",
                                        data={"title": "Google Calendar", "subtitle": "Connector",
                                              "data": {"url": "https://agent.meta.ai/c/gc"}}))["card"]
        self.assertEqual((conn["title"], conn["subtitle"], conn["url"]),
                         ("Google Calendar", "Connector", "https://agent.meta.ai/c/gc"))
        space = bridge.to_message(widget(16, "space_build_completed", text="\u2068Our trip\u2069 is ready",
                                         fallback="[Our trip](https://agent.meta.ai/space/our-trip)",
                                         data={"summary": "Our trip is ready \u2014 a scrapbook."}))["card"]
        self.assertEqual((space["title"], space["subtitle"], space["url"]),
                         ("Our trip is ready", "a scrapbook.", "https://agent.meta.ai/space/our-trip"))
        task = bridge.to_message(widget(17, "browser_task", text="Book a table",
                                        data={"title": "Browser", "status": "Completed",
                                              "display_state": "completed",
                                              "current_site": {"domain": "example.com"}}))["card"]
        self.assertEqual((task["title"], task["subtitle"], task["status"], task["url"]),
                         ("Book a table", "example.com", "completed", None))
        generic = bridge.to_message(widget(20, "browser_task", text="Task completed",
                                           data={"activity_title_source": "state", "display_state": "completed",
                                                 "current_site": {"domain": "e.com", "page_title": "Your trip"}}))
        self.assertEqual(generic["card"]["title"], "Your trip")
        bare = bridge.to_message(widget(21, "browser_task", text="Stopped",
                                        data={"activity_title_source": "state", "display_state": "stopped"}))
        self.assertEqual((bare["card"]["title"], bare["card"]["status"]), ("Browser task", "stopped"))
        note = bridge.to_message(widget(18, "html", text="Seat recheck\n\nChecks the map on Thursday.",
                                        data={"html": "<p>…</p>"}))["card"]
        self.assertEqual((note["title"], note["subtitle"]), ("Seat recheck", "Checks the map on Thursday."))
        self.assertIsNone(bridge.to_message(widget(19, "voice_options", text="", data={"options": []})))

    def test_repeated_widget_keeps_only_its_latest_version(self):
        rows = bridge.to_messages([ev(1), widget(2, "browser_task", text="Book", wid="bt"),
                                   ev(3), widget(4, "browser_task", text="Book", wid="bt")])
        self.assertEqual([m["seq"] for m in rows], [1, 3, 4])

    def test_sessions_main_first_then_pinned_then_recent(self):
        rows = [bridge.to_session(s) for s in [
            {"session_id": "a", "title": "old", "is_thread": True, "updated_at_ms": 1},
            {"session_id": "b", "title": "new", "is_thread": True, "updated_at_ms": 9},
            {"session_id": "p", "title": "pin", "is_thread": True, "pinned": True, "updated_at_ms": 2},
            {"session_id": "m", "title": "", "is_primary": True, "is_thread": False,
             "updated_at_ms": 0, "unread_count": 4},
        ]]
        out = bridge.sort_sessions(rows)
        self.assertEqual([r["title"] for r in out], ["main chat", "pin", "new", "old"])
        self.assertIsNone(out[0]["session_id"])
        self.assertEqual(out[0]["unread"], 4)


class FramingTest(unittest.TestCase):
    def run_lines(self, backend, lines):
        buf = io.StringIO()
        w = bridge.Writer(buf)
        for line in lines:
            bridge.handle(backend, w, line)
        return [json.loads(x) for x in buf.getvalue().splitlines()]

    def test_responses_match_ids_one_per_line(self):
        b, *_ = make()
        out = self.run_lines(b, ['{"id": 7, "method": "ping", "params": {}}',
                                 '{"id": "x", "method": "ping"}'])
        self.assertEqual(out, [{"id": 7, "result": {"pong": True}},
                               {"id": "x", "result": {"pong": True}}])

    def test_bad_requests(self):
        b, *_ = make()
        out = self.run_lines(b, ["not json", '{"id": 1, "method": "nope"}',
                                 '{"id": 2, "method": "ping", "params": [1]}',
                                 '{"id": 3, "method": "send", "params": {"text": "hi"}}',
                                 '{"id": 4, "method": "session_op", "params": {"op": "zap"}}'])
        self.assertEqual([o["id"] for o in out], [None, 1, 2, 3, 4])
        self.assertTrue(all(o["error"]["kind"] == "bad_request" for o in out))

    def test_shutdown_stops(self):
        b, *_ = make()
        w = bridge.Writer(io.StringIO())
        self.assertFalse(bridge.handle(b, w, '{"id": 1, "method": "shutdown"}'))
        self.assertTrue(bridge.handle(b, w, '{"id": 2, "method": "ping"}'))

    def test_send_events_follow_its_response(self):
        b, gw, *_ = make()
        gw.events = [ev(1)]
        out = self.run_lines(b, ['{"id": 1, "method": "open", "params": {"session_id": null}}',
                                 '{"id": 2, "method": "send", "params": {"text": "hello"}}'])
        self.assertEqual(out[-2], {"id": 2, "result": {"sent": True, "baseline": 1}})
        self.assertEqual(out[-1]["event"], "thinking")
        self.assertEqual(gw.opened[0][0], "chat.stream")
        self.assertEqual(gw.opened[0][1]["items"], [{"type": "text", "text": "hello"}])
        self.assertNotIn("session_id", gw.opened[0][1])


class ErrorKindTest(unittest.TestCase):
    def call(self, b, method, params=None):
        try:
            return {"result": b.dispatch(method, params or {})}
        except Exception as e:
            return {"error": b.error_of(e)}

    def test_auth_emits_auth_needed(self):
        b, gw, _, events = make()
        gw.fail = AuthError("expired")
        err = self.call(b, "sessions")["error"]
        self.assertEqual(err["kind"], "auth")
        self.assertEqual(events[-1], ("connection", {"state": "auth_needed", "detail": "expired"}))

    def test_auth_on_connect(self):
        def boom(cfg):
            raise AuthError("no cookies")
        b, *_ = make()
        b.connect_fn = boom
        self.assertEqual(self.call(b, "connect")["error"]["kind"], "auth")

    def test_not_found_gateway_timeout(self):
        b, gw, *_ = make()
        gw.fail = GatewayError(404, NOT_FOUND)
        err = self.call(b, "open", {"session_id": "gone"})["error"]
        self.assertEqual((err["kind"], err["status"]), ("not_found", 404))
        gw.fail = GatewayError(500, "boom")
        self.assertEqual(self.call(b, "feed")["error"]["kind"], "gateway")
        gw.fail = TimeoutError("slow")
        self.assertEqual(self.call(b, "goals")["error"]["kind"], "timeout")

    def test_gateway_error_uses_server_reason(self):
        b, gw, *_ = make()
        gw.fail = GatewayError(403, '{"ok":false,"error":{"code":"email_not_enabled",'
                                    '"message":"Muse mail is not enabled for this account"}}')
        err = self.call(b, "email")["error"]
        self.assertEqual(err, {"kind": "gateway", "status": 403, "code": "email_not_enabled",
                               "message": "Muse mail is not enabled for this account"})
        gw.fail = GatewayError(500, "boom")
        err = self.call(b, "feed")["error"]
        self.assertNotIn("code", err)
        self.assertIn("boom", err["message"])

    def test_internal_reconnects_once(self):
        b, gw, *_ = make()
        connects = []
        b.connect_fn = lambda cfg: connects.append(1) or gw
        gw.fail = OSError("connection reset")
        err = self.call(b, "ideas")["error"]
        self.assertEqual(err["kind"], "internal")
        self.assertEqual(len(connects), 2)

    def test_deleted_open_chat_resets_saved_chat(self):
        b, gw, *_ = make()
        b.save_state({"session_id": "gone", "title": "Old"})
        gw.fail = GatewayError(404, NOT_FOUND)
        self.call(b, "open", {"session_id": "gone"})
        self.assertIsNone(b.load_state()["session_id"])


class PollingTest(unittest.TestCase):
    def setUp(self):
        self.b, self.gw, self.clock, self.events = make()
        self.gw.events = [ev(1, role="user"), ev(2)]
        res = self.b.dispatch("connect", {})
        self.assertEqual(res["chat"], {"session_id": None, "title": "main chat"})
        res = self.b.dispatch("open", {"session_id": None})
        self.assertEqual([m["seq"] for m in res["messages"]], [1, 2])
        self.events.clear()

    def advance(self, seconds):
        self.clock.t += seconds
        self.b.tick()

    def messages(self):
        return [d["message"]["seq"] for n, d in self.events if n == "message"]

    def test_each_seq_once_and_not_already_opened(self):
        self.advance(8)
        self.assertEqual(self.messages(), [])
        self.gw.events += [ev(3, reply_to="assistant-msg-3", text="push")]
        self.advance(8)
        self.advance(8)
        self.assertEqual(self.messages(), [3])
        self.assertTrue(self.events[-1][1]["message"]["push"])

    def test_main_chat_keeps_its_name(self):
        res = self.b.dispatch("open", {"session_id": None, "title": "About the weather"})
        self.assertEqual(res["chat"], {"session_id": None, "title": "main chat"})
        self.assertEqual(self.b.load_state()["title"], "main chat")

    def test_idle_poll_is_slow(self):
        polls = lambda: sum(1 for m, _ in self.gw.calls if m == "chat.history")
        before = polls()
        self.advance(4)
        self.assertEqual(polls(), before)
        self.advance(4)
        self.assertEqual(polls(), before + 1)

    def test_draft_then_final(self):
        self.gw.events.append(ev(3, status=None, text="Hel"))
        self.advance(8)
        self.advance(8)
        self.gw.events[-1] = ev(3, status=None, text="Hello wor")
        self.advance(8)
        self.gw.events[-1] = ev(3, text="Hello world")
        self.advance(8)
        self.assertEqual([n for n in names(self.events) if n != "unread"],
                         ["draft", "draft", "message"])
        final = [d for n, d in self.events if n == "message"][0]
        self.assertEqual(final["message"]["text"], "Hello world")

    def test_widget_after_reply_is_a_message_not_a_reply(self):
        self.b.dispatch("send", {"text": "draw it"})
        self.gw.events += [ev(3, role="user", text="draw it"), ev(4, text="Here it is")]
        self.advance(1)
        self.gw.events.append(widget(5, "image", data={"images": [{"path": "sandbox://workspace/a.png"}]}))
        self.advance(1)
        msgs = [d["message"] for n, d in self.events if n == "message"]
        self.assertEqual([(m["seq"], m["widget"]) for m in msgs], [(3, False), (4, False), (5, True)])
        self.assertEqual(self.b.dispatch("files", {})["files"][0]["path"], "sandbox://workspace/a.png")

    def test_draft_seen_at_open_is_reported_when_done(self):
        self.gw.events = [ev(1), ev(2, status=None, text="half")]
        self.b.dispatch("open", {"session_id": None})
        self.events.clear()
        self.advance(8)
        self.assertEqual(self.events, [])
        self.gw.events[-1] = ev(2, text="half and whole")
        self.advance(8)
        self.assertEqual(self.messages(), [2])

    def test_send_polls_every_second_until_idle(self):
        self.b.dispatch("send", {"text": "hi"})
        self.gw.events.append(ev(3, role="user", status=None, text="hi"))
        self.advance(1)
        self.assertEqual(self.messages(), [3])
        self.gw.events.append(ev(4, status=None, text="Wri"))
        self.advance(1)
        self.gw.events[-1] = ev(4, text="Written")
        self.advance(1)
        self.assertEqual(self.messages(), [3, 4])
        self.advance(9)
        self.assertNotIn("idle", names(self.events))
        self.advance(1.01)
        self.assertEqual(self.events[-1], ("idle", {"session_id": None, "replied": True}))
        polls = sum(1 for m, _ in self.gw.calls if m == "chat.history")
        self.advance(1)
        self.assertEqual(sum(1 for m, _ in self.gw.calls if m == "chat.history"), polls)

    def test_follow_up_extends_quiet(self):
        self.b.dispatch("send", {"text": "hi"})
        self.gw.events.append(ev(3))
        self.advance(1)
        self.advance(6)
        self.gw.events.append(ev(4, text="one more thing"))
        self.advance(1)
        self.advance(5)
        self.assertNotIn("idle", names(self.events))
        self.advance(5)
        self.assertIn("idle", names(self.events))

    def test_no_reply_goes_idle_after_wait(self):
        self.b.dispatch("send", {"text": "hi"})
        self.gw.events.append(ev(3, reply_to="assistant-msg-3"))
        for _ in range(299):
            self.clock.t += 1
            self.b.tick()
        self.assertNotIn("idle", names(self.events))
        self.advance(1)
        self.assertEqual(self.events[-1], ("idle", {"session_id": None, "replied": False}))

    def test_unread_every_30s(self):
        for _ in range(8):
            self.advance(4)
        unread = [d for n, d in self.events if n == "unread"]
        self.assertEqual(unread, [{"unread_count": 2}])

    def test_three_failures_go_offline_then_reconnect(self):
        self.gw.fail = GatewayError(502, "bad gateway")
        self.advance(8)
        self.advance(8)
        self.assertNotIn("connection", names(self.events))
        self.advance(8)
        self.assertEqual(self.events[-1][1]["state"], "offline")
        self.gw.fail = None
        self.advance(2)
        states = [d["state"] for n, d in self.events if n == "connection"]
        self.assertEqual(states, ["offline", "connecting", "online"])

    def test_reconnect_backs_off(self):
        self.b.failures = 2
        self.b.failed(OSError("down"))
        self.b.connect_fn = MagicMock(side_effect=OSError("still down"))
        self.advance(2)
        self.assertEqual(self.b.backoff, 4)
        self.advance(3)
        self.assertEqual(self.b.connect_fn.call_count, 1)
        self.advance(1)
        self.assertEqual(self.b.connect_fn.call_count, 2)

    def test_auth_failure_stops_polling(self):
        self.gw.fail = AuthError("expired")
        self.advance(8)
        self.assertEqual(self.events[-1][1]["state"], "auth_needed")
        calls = len(self.gw.calls)
        self.advance(60)
        self.assertEqual(len(self.gw.calls), calls)

    def test_deleted_chat_stops_tracking(self):
        self.gw.events = []
        self.b.dispatch("open", {"session_id": "s1", "title": "Side"})
        self.gw.fail = GatewayError(404, NOT_FOUND)
        self.advance(8)
        self.assertFalse(self.b.tracker.active)
        self.assertEqual(self.events[-1][0], "log")

    def test_history_page_and_files(self):
        self.gw.events = [ev(i) for i in range(1, 6)]
        self.gw.events[1]["payload"]["data"] = {"videos": [{"path": "sandbox://workspace/a.mp4"}]}
        page = self.b.dispatch("history", {"limit": 2, "before_seq": 4})
        self.assertEqual([m["seq"] for m in page["messages"]], [2, 3])
        self.gw.events[3]["payload"]["metadata"] = {"attachments": [
            {"path": "workspace/up/me.png", "mime_type": "image/png", "filename": "me.png", "bytes_len": 9}]}
        files = self.b.dispatch("files", {})["files"]
        # Newest first.
        self.assertEqual(files, [{"seq": 4, "message_id": "assistant-msg-4",
                                  "path": "sandbox://workspace/up/me.png", "kind": "image",
                                  "mime": "image/png", "label": "me.png", "byte_len": 9},
                                 {"seq": 2, "message_id": "assistant-msg-2",
                                  "path": "sandbox://workspace/a.mp4", "kind": "video",
                                  "mime": None, "label": None, "byte_len": None}])
        self.advance(8)
        # 3 came back in the page above, so only 4 and 5 are new.
        self.assertEqual(self.messages(), [4, 5])


class LoginTest(unittest.TestCase):
    def test_captures_output_and_failure(self):
        b, *_ = make()

        def fail():
            print("cookie export failed.", file=sys.stderr)
            sys.exit(1)
        b.run_login = fail
        res = b.dispatch("login", {})
        self.assertEqual(res, {"ok": False, "log": "cookie export failed.\n"})

    def test_success_reconnects(self):
        b, *_ = make()
        b.run_login = lambda: print("saved 3 muse.ai cookies")
        connects = []
        gw = FakeGW()
        b.connect_fn = lambda cfg: connects.append(1) or gw
        res = b.dispatch("login", {})
        self.assertTrue(res["ok"])
        self.assertIn("saved 3", res["log"])
        self.assertEqual(len(connects), 1)


class StdoutIsolationTest(unittest.TestCase):
    def test_stray_print_goes_to_stderr(self):
        code = ("import os, sys\n"
                "from muse_cli import bridge\n"
                "w = bridge.Writer(bridge.isolate_stdout())\n"
                "print('stray print')\n"
                "os.write(1, b'raw fd write\\n')\n"
                "w.event('ready', {})\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout, '{"event":"ready","data":{}}\n')
        self.assertIn("stray print", r.stderr)
        self.assertIn("raw fd write", r.stderr)


class DemoBridgeTest(unittest.TestCase):
    """The demo bridge end to end, as the app runs it."""

    def setUp(self):
        env = dict(os.environ, MUSE_CLI_DEMO_SPEED="20")
        env.pop("MUSE_CLI_DEMO", None)
        self.p = subprocess.Popen([sys.executable, "-m", "muse_cli.bridge", "--demo"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env)
        self.next_id = 0
        self.seen = []

    def tearDown(self):
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait()
        self.p.stdin.close()
        self.p.stdout.close()

    def read(self):
        line = self.p.stdout.readline()
        self.assertTrue(line, "bridge closed its stdout")
        msg = json.loads(line)
        self.seen.append(msg)
        return msg

    def call(self, method, **params):
        self.next_id += 1
        self.p.stdin.write(json.dumps({"id": self.next_id, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        while True:
            msg = self.read()
            if msg.get("id") == self.next_id:
                self.assertNotIn("error", msg)
                return msg["result"]

    def test_full_session(self):
        start = time.time()
        self.assertEqual(self.read(), {"event": "ready",
                                       "data": {"version": bridge.__version__, "demo": True}})
        self.assertEqual(self.call("connect")["vm_id"], "demo-vm")
        sessions = self.call("sessions")["sessions"]
        self.assertEqual(len(sessions), 6)
        self.assertIsNone(sessions[0]["session_id"])
        self.assertTrue(sessions[1]["pinned"])
        self.assertTrue(any(s["unread"] for s in sessions))
        opened = self.call("open", session_id=None, title="main chat")
        msgs = opened["messages"]
        self.assertGreaterEqual(len(msgs), 10)
        self.assertTrue(any(m["files"] for m in msgs))
        self.assertTrue(any("```" in m["text"] for m in msgs))
        self.assertTrue(any(m["push"] for m in msgs))
        self.assertTrue(self.call("send", text="can you plan my week?")["sent"])
        kinds = []
        while "idle" not in kinds:
            msg = self.read()
            if "event" in msg:
                kinds.append(msg["event"])
            self.assertLess(time.time() - start, 10)
        self.assertEqual(kinds[0], "thinking")
        self.assertGreaterEqual(kinds.count("draft"), 3)
        finals = [m["data"]["message"] for m in self.seen if m.get("event") == "message"]
        self.assertEqual([m["role"] for m in finals], ["user", "assistant"])
        self.assertIn("Your week", finals[1]["text"])
        self.assertLess(kinds.index("draft"), kinds.index("message", 2))
        self.assertEqual(len({m["seq"] for m in finals}), 2)

        chat = self.call("new_chat", title="Garden ideas")["chat"]
        titles = [s["title"] for s in self.call("sessions")["sessions"]]
        self.assertIn("Garden ideas", titles)
        self.call("session_op", op="pin", session_id=chat["session_id"])
        self.call("session_op", op="delete", session_id="demo-books")
        self.assertEqual(len(self.call("sessions")["sessions"]), 6)
        self.assertEqual(len(self.call("feed")["units"]), 8)
        units = self.call("feed")["units"]
        self.assertTrue(all(u["summary"] and u["emoji"] and u["why"] for u in units))
        self.assertEqual(units[1]["source"], "Google Calendar")
        self.call("feed_react", unit="demo-unit-3", reaction="like")
        self.assertEqual(self.call("feed")["units"][2]["reaction"], "like")
        self.assertEqual(len(self.call("goals")["goals"]), 4)
        ideas = self.call("ideas")["ideas"]
        self.assertEqual((len(ideas), len({i["section"] for i in ideas})), (6, 2))
        tasks = self.call("tasks")["tasks"]
        self.assertEqual(len(tasks), 4)
        self.assertEqual(tasks[0]["schedule"], "daily@07:30:00")
        self.assertTrue(self.call("task_runs")["runs"])
        mail = self.call("email")
        self.assertEqual(len(mail["threads"]), 3)
        self.assertTrue(self.call("email_thread", id=mail["threads"][0]["id"])["messages"])
        self.call("open", session_id=None)
        files = self.call("files")["files"]
        self.assertTrue(files)
        with tempfile.TemporaryDirectory() as tmp:
            rows = self.call("download", path=files[0]["path"], dir=tmp)["rows"]
            with open(rows[0]["file"], "rb") as fh:
                self.assertTrue(fh.read().startswith(b"\x89PNG"))
        self.assertTrue(self.call("login")["ok"])
        self.assertEqual(self.call("shutdown"), {})
        self.assertEqual(self.p.wait(timeout=5), 0)

    def test_exits_on_stdin_eof(self):
        self.read()
        self.p.stdin.close()
        self.assertEqual(self.p.wait(timeout=5), 0)


class DemoWorldTest(unittest.TestCase):
    def test_reply_streams_then_completes(self):
        clock = Clock(0)
        w = demo.World(clock, speed=1)
        w.send(demo.MAIN, "any code tips?")
        clock.t = 1.0
        last = w.api_chat_history({}, {"limit": 1})["chat_events"][-1]
        self.assertEqual(last["event_name"], "message.user")
        clock.t = 1.5
        draft = w.api_chat_history({}, {"limit": 1})["chat_events"][-1]
        self.assertNotIn("status", draft["payload"])
        clock.t = 60
        done = w.api_chat_history({}, {"limit": 1})["chat_events"][-1]
        self.assertEqual(done["payload"]["status"], "completed")
        self.assertIn("```python", done["payload"]["display_text"])

    def test_keyword_replies(self):
        self.assertIn("getaway", demo.pick_reply("Book a trip to Lisbon"))
        self.assertEqual(demo.pick_reply("zzz"), demo.DEFAULT_REPLY)


if __name__ == "__main__":
    unittest.main()
