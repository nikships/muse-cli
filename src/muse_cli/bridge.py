"""JSON-lines bridge between the full-screen app and the gateway.

Run as `python -m muse_cli.bridge [--demo]`. The app (muse_cli/tui) spawns it
and talks to it over pipes; docs/TUI.md is the protocol.
"""
import argparse
import contextlib
import io
import json
import os
import queue
import re
import sys
import threading
import time

from . import __version__, cli
from .chat import QUIET, WAIT, is_not_found, load_state, save_state
from .gateway import AuthError, GatewayError

SEND_POLL = 1      # seconds between history reads from `send` until `idle`
IDLE_POLL = 8      # seconds between history reads otherwise
UNREAD_POLL = 30   # seconds between unread-count reads while online
POLL_LIMIT = 20    # events per poll; more than a reply burst ever adds
FAILS_OFFLINE = 3  # poll failures in a row before going offline
BACKOFF_MAX = 60
DOWNLOADS = os.path.join("~", "Downloads", "muse")

METHODS = ("connect", "login", "sessions", "open", "history", "send", "new_chat",
           "session_op", "status", "feed", "feed_react", "goals", "goal", "ideas", "idea",
           "idea_exec", "tasks", "task_runs", "email", "email_thread", "files", "download",
           "ping", "shutdown")
SESSION_OPS = ("rename", "pin", "unpin", "archive", "unarchive", "delete")
REACTIONS = ("like", "love", "dislike")
FILE_KEYS = ("seq", "message_id", "path", "kind", "mime", "label", "byte_len")


class BadRequest(Exception):
    pass


def _payload(ev):
    return ev.get("payload") if isinstance(ev.get("payload"), dict) else {}


# Placeholders the web app swaps for UI: an inline widget, and a file the user attached.
_WIDGET_RE = re.compile(r"[ \t]*\[\[?hatch_widget:[^\]\s]+\]\]?")
_UPLOAD_RE = re.compile(r"[ \t]*\[(?:image|video|audio|file|document):[^\]\s]+ [^\]]+\]")


def uploads(p):
    meta = p.get("metadata") if isinstance(p.get("metadata"), dict) else {}
    rows = []
    for a in meta.get("attachments") or []:
        path = a.get("path") if isinstance(a, dict) else None
        if not isinstance(path, str) or not path:
            continue
        mime = a.get("mime_type") or ""
        rows.append({"path": path if "://" in path else "sandbox://" + path.lstrip("/"),
                     "kind": mime.split("/")[0] if mime.split("/")[0] in ("image", "video", "audio") else "file",
                     "mime": mime or None, "label": a.get("filename"), "byte_len": a.get("bytes_len")})
    return rows


def choices(p):
    """Option widgets (quick replies) attached to a message."""
    rows = []
    for w in p.get("widgets") or []:
        if not isinstance(w, dict) or w.get("kind") != "option":
            continue
        opts = [o for o in (w.get("data") or {}).get("options") or [] if isinstance(o, str) and o]
        if not opts:
            continue
        picked = ((w.get("state") or {}).get("data") or {}).get("selectedText")
        rows.append({"id": w.get("widget_id"), "options": opts,
                     "selected": picked if isinstance(picked, str) and picked else None})
    return rows


def to_message(ev):
    """Map one chat.history event to a protocol Message, or None."""
    name = ev.get("event_name")
    if name == "delta.presentation":
        return _presentation(ev)
    if name not in ("message.user", "message.assistant"):
        return None
    p = _payload(ev)
    row = cli.fmt_event(ev)
    files = [{k: r.get(k) for k in FILE_KEYS[2:]} for r in cli.event_resources(ev)]
    for f in uploads(p):
        if f["path"] not in [x["path"] for x in files]:
            files.append(f)
    picks = choices(p)
    text = row["text"] or ""
    if picks:
        text = _WIDGET_RE.sub("", text)
    if files:
        text = _UPLOAD_RE.sub("", text)
    text = text.strip()
    if not text and not files and not picks:
        return None
    assistant = name == "message.assistant"
    return {"seq": ev.get("seq"), "id": row["message_id"],
            "role": "assistant" if assistant else "user", "text": text,
            "at_ms": (ev.get("occurred_at_ms") or ev.get("display_text_updated_at_ms")
                      or p.get("display_text_updated_at_ms")),
            # An assistant reply still being written has no status yet.
            "final": not assistant or bool(p.get("status")),
            "push": assistant and bool(ev.get("reply_to_message_id") or p.get("reply_to_message_id")),
            "files": files, "choices": picks, "card": None, "widget": False}


_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _plain(s):
    # Display text wraps names in Unicode isolates (U+2068 ... U+2069).
    return s.replace("\u2068", "").replace("\u2069", "").strip() if isinstance(s, str) else ""


def card(p):
    """A small card for a presentation the web app draws as a widget, or None."""
    kind = p.get("kind")
    d = p.get("data") if isinstance(p.get("data"), dict) else {}
    shown = _plain(p.get("display_text"))
    link = _LINK_RE.search(shown) or _LINK_RE.search(_plain(p.get("fallback_text")))
    title, subtitle, url, status = (link.group(1) if link else shown), None, None, None
    if kind == "external_link":
        url = d.get("url") if isinstance(d.get("url"), str) else link and link.group(2)
    elif kind == "internal_link_action_card":
        title = _plain(d.get("title")) or title
        subtitle = _plain(d.get("subtitle")) or None
        inner = d.get("data") if isinstance(d.get("data"), dict) else {}
        url = inner.get("url") if isinstance(inner.get("url"), str) else None
    elif kind == "space_build_completed":
        title = shown or title
        subtitle = _plain(d.get("summary"))
        if title and subtitle.startswith(title):
            subtitle = subtitle[len(title):].lstrip(" \u2014-–:,.")
        subtitle = subtitle or None
        url = link and link.group(2)
    elif kind == "browser_task":
        site = d.get("current_site") if isinstance(d.get("current_site"), dict) else {}
        # A "state" title is just the status again ("Task completed"); the page says more.
        if d.get("activity_title_source") == "state":
            shown = _plain(site.get("page_title"))
        title = shown or "Browser task"
        subtitle = site.get("domain") or None
        status = d.get("display_state") or (d.get("status") or "").lower() or None
    else:
        head, _, rest = shown.partition("\n")
        title, subtitle = (head.strip(), rest.strip() or None) if head.strip() else (title, None)
    if not title:
        return None
    return {"id": p.get("id"), "kind": kind, "title": title, "subtitle": subtitle,
            "url": url or None, "status": status}


def _presentation(ev):
    """An image, file, link or other widget the agent added after its text."""
    p = _payload(ev)
    files = [{k: r.get(k) for k in FILE_KEYS[2:]} for r in cli.event_resources(ev)]
    c = None if files else card(p)
    if not files and not c:
        return None
    return {"seq": ev.get("seq"), "id": p.get("message_id") or ev.get("message_id"),
            "role": "user" if p.get("role") == "user" else "assistant", "text": "",
            "at_ms": ev.get("occurred_at_ms") or p.get("display_text_updated_at_ms"),
            "final": True, "push": False, "files": files, "choices": [], "card": c, "widget": True}


def server_reason(e):
    """(code, message) from a gateway error body such as {"error": {...}}."""
    body = e.payload
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return None, None
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, str):
        return None, err
    if not isinstance(err, dict):
        return None, None
    code = err.get("code") if isinstance(err.get("code"), str) else None
    message = err.get("message") if isinstance(err.get("message"), str) else None
    return code, message


def to_messages(events):
    rows = [m for m in map(to_message, events) if m]
    # A widget that changes (a browser task finishing) comes back under its old id.
    last = {m["card"]["id"]: m["seq"] for m in rows if m["card"] and m["card"]["id"]}
    return [m for m in rows if not (m["card"] and m["card"]["id"]) or last[m["card"]["id"]] == m["seq"]]


def is_main(s):
    if "is_primary" in s:
        return bool(s.get("is_primary"))
    return not s.get("is_thread")


def to_session(s):
    main = is_main(s)
    return {"session_id": None if main else s.get("session_id"),
            "title": s.get("title") or ("main chat" if main else "untitled"),
            "is_thread": bool(s.get("is_thread")), "pinned": bool(s.get("pinned")),
            "archived": bool(s.get("archived")), "updated_at_ms": s.get("updated_at_ms") or 0,
            "unread": s.get("unread_count") or 0}


def sort_sessions(rows):
    return sorted(rows, key=lambda r: (r["session_id"] is not None, not r["pinned"],
                                       -(r["updated_at_ms"] or 0)))


def chat_of(session_id, title=None):
    # The server titles the main chat after its latest topic; it is always "main chat" here.
    if session_id is None:
        return {"session_id": None, "title": "main chat"}
    return {"session_id": session_id, "title": title or "untitled"}


def _str(p, key, required=True):
    v = p.get(key)
    if v is None and not required:
        return None
    if not isinstance(v, str) or not v:
        raise BadRequest(f"'{key}' must be a non-empty string")
    return v


def _int(p, key, default, low=1, high=500):
    v = p.get(key, default)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high:
        raise BadRequest(f"'{key}' must be an integer from {low} to {high}")
    return v


class Writer:
    """Writes protocol lines; events come from more than one thread."""

    def __init__(self, fh):
        self.fh = fh
        self.lock = threading.Lock()

    def send(self, obj):
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
        with self.lock:
            self.fh.write(line + "\n")
            self.fh.flush()

    def event(self, name, data):
        self.send({"event": name, "data": data})


class Tracker:
    """Turns repeated history reads of the active chat into events.

    Each final message is emitted once. Messages that `open` or `history`
    already returned count as reported, except replies that were still being
    written then: those are emitted when they finish.
    """

    def __init__(self, emit, quiet=QUIET, wait=WAIT):
        self.emit = emit
        self.quiet = quiet
        self.wait = wait
        self.close()

    def close(self):
        self.active = False
        self.session_id = None
        self.seen = set()
        self.pending = set()
        self.drafts = {}
        self.floor = 0
        self.sending = False
        self.got_reply = False
        self.baseline = 0
        self.deadline = None

    def open(self, session_id, events):
        self.close()
        self.active = True
        self.session_id = session_id
        self.prime(events)

    def prime(self, events, newest=True):
        """Mark events the app already has. newest=False for an older page."""
        for ev in events:
            seq = ev.get("seq") or 0
            if newest:
                self.floor = max(self.floor, seq)
            if ev.get("event_name") == "message.assistant" and not _payload(ev).get("status"):
                self.pending.add(seq)
                m = to_message(ev)
                if m:
                    self.drafts[seq] = m["text"]
            elif to_message(ev):
                self.seen.add(seq)

    def max_seq(self):
        return max([self.floor, *self.seen, *self.pending])

    def update(self, events, now):
        for ev in sorted(events, key=lambda e: e.get("seq") or 0):
            m = to_message(ev)
            if m is None:
                continue
            seq = m["seq"] or 0
            fresh = seq > self.floor or seq in self.pending
            if m["final"]:
                if seq in self.seen or not fresh:
                    continue
                self.seen.add(seq)
                self.pending.discard(seq)
                self.drafts.pop(seq, None)
                self.emit("message", {"session_id": self.session_id, "message": m})
                if self.sending and cli.is_reply(ev, self.baseline):
                    self.got_reply = True
                    self.deadline = now + self.quiet
            elif m["role"] == "assistant" and fresh and self.drafts.get(seq) != m["text"]:
                self.drafts[seq] = m["text"]
                self.emit("draft", {"session_id": self.session_id, "message": m})
                if self.sending:
                    self.deadline = max(self.deadline, now + self.quiet)

    def start_send(self, baseline, now):
        self.sending = True
        self.got_reply = False
        self.baseline = baseline
        self.deadline = now + self.wait

    def check_idle(self, now):
        if self.sending and now >= self.deadline:
            self.sending = False
            self.emit("idle", {"session_id": self.session_id, "replied": self.got_reply})
            return True
        return False


class Backend:
    """Handles requests and polling with one Gateway, all on one thread."""

    send_poll = SEND_POLL
    idle_poll = IDLE_POLL
    unread_poll = UNREAD_POLL
    quiet = QUIET
    wait = WAIT
    demo = False

    def __init__(self, emit, clock=time.monotonic, connect=None, cfg=None):
        self.emit = emit
        self.clock = clock
        self.connect_fn = connect or cli.connect
        self.cfg = cfg
        self.tracker = Tracker(emit, quiet=self.quiet, wait=self.wait)
        self._gw = None
        self.state = None
        self.failures = 0
        self.backoff = 0
        self.reconnect_at = None
        self.next_poll = 0
        self.next_unread = 0
        self.after = []

    # -- state the plain chat shares (overridden by the demo) ---------------
    def load_state(self):
        return load_state()

    def save_state(self, st):
        save_state(st)

    def config(self):
        if self.cfg is None:
            self.cfg = cli.load_config()
        return self.cfg

    def run_login(self):
        cli.cmd_auth_export(None)

    def download_dir(self):
        return os.path.expanduser(DOWNLOADS)

    # -- connection --------------------------------------------------------
    def set_state(self, state, detail=None):
        if (state, detail) != self.state:
            self.state = (state, detail)
            self.emit("connection", {"state": state, "detail": detail})

    def gw(self):
        if self._gw is None:
            self.set_state("connecting")
            try:
                self._gw = self.connect_fn(self.config())
            except AuthError as e:
                self.reconnect_at = None
                self.set_state("auth_needed", str(e))
                raise
            except Exception as e:
                self.set_state("offline", str(e))
                raise
            self.failures, self.backoff, self.reconnect_at = 0, 0, None
            now = self.clock()
            self.next_poll, self.next_unread = now, now + self.unread_poll
            self.set_state("online")
        return self._gw

    def drop_gw(self):
        if self._gw is not None:
            try:
                self._gw.close()
            except Exception:
                pass
            self._gw = None

    def close(self):
        self.drop_gw()

    def auth_lost(self, err):
        self.drop_gw()
        self.reconnect_at = None
        self.set_state("auth_needed", str(err))

    def failed(self, err):
        self.failures += 1
        if self.failures < FAILS_OFFLINE:
            return
        self.drop_gw()
        self.backoff = min(BACKOFF_MAX, self.backoff * 2 or 2)
        self.reconnect_at = self.clock() + self.backoff
        self.set_state("offline", str(err))

    def reconnect(self):
        try:
            self.gw()
        except AuthError:
            pass
        except Exception:
            self.backoff = min(BACKOFF_MAX, self.backoff * 2 or 2)
            self.reconnect_at = self.clock() + self.backoff

    # -- the worker loop's periodic work -------------------------------------
    def next_wake(self):
        now = self.clock()
        times = [now + 1]
        if self.reconnect_at is not None:
            times.append(self.reconnect_at)
        elif self._gw is not None:
            times.append(self.next_unread)
            if self.tracker.active:
                times.append(self.next_poll)
        if self.tracker.sending:
            times.append(self.tracker.deadline)
        return min(times)

    def tick(self):
        now = self.clock()
        if self.reconnect_at is not None:
            if now >= self.reconnect_at:
                self.reconnect()
        elif self._gw is not None:
            if self.tracker.active and now >= self.next_poll:
                self.poll()
            if self._gw is not None and now >= self.next_unread:
                self.poll_unread()
        if self.tracker.check_idle(self.clock()):
            self.next_poll = self.clock() + self.idle_poll

    def poll(self):
        t = self.tracker
        try:
            events = self.history_events(t.session_id, POLL_LIMIT)
        except AuthError as e:
            self.auth_lost(e)
            return
        except GatewayError as e:
            if is_not_found(e) and t.session_id:
                self.chat_gone(t.session_id)
                self.emit("log", {"level": "warn", "text": "This chat was deleted."})
            else:
                self.failed(e)
            return
        except Exception as e:
            self.failed(e)
            return
        finally:
            self.next_poll = self.clock() + (self.send_poll if t.sending else self.idle_poll)
        self.failures = 0
        t.update(events, self.clock())

    def poll_unread(self):
        self.next_unread = self.clock() + self.unread_poll
        try:
            d = self._gw.call_json("chat.unread_count")
        except AuthError as e:
            self.auth_lost(e)
            return
        except Exception as e:
            self.failed(e)
            return
        self.failures = 0
        self.emit("unread", d)

    def chat_gone(self, session_id):
        if self.tracker.active and self.tracker.session_id == session_id:
            self.tracker.close()
        if self.load_state().get("session_id") == session_id:
            self.save_state({"session_id": None, "title": "main chat"})

    # -- requests ----------------------------------------------------------
    def later(self, name, data):
        self.after.append((name, data))

    def dispatch(self, method, params):
        if method not in METHODS:
            raise BadRequest(f"unknown method '{method}'")
        if not isinstance(params, dict):
            raise BadRequest("params must be an object")
        return getattr(self, "m_" + method)(params)

    def error_of(self, e):
        """Map an exception to a protocol error object."""
        if isinstance(e, BadRequest):
            return {"kind": "bad_request", "message": str(e)}
        if isinstance(e, AuthError):
            self.auth_lost(e)
            return {"kind": "auth", "message": str(e)}
        if isinstance(e, GatewayError):
            kind = "not_found" if is_not_found(e) else "gateway"
            out = {"kind": kind, "message": str(e), "status": e.status}
            code, message = server_reason(e)
            if message:
                out["message"] = message
            if code:
                out["code"] = code
            return out
        if isinstance(e, TimeoutError):
            return {"kind": "timeout", "message": str(e)}
        # Most likely a dropped connection: reconnect so the next try works.
        if self._gw is not None:
            self.drop_gw()
            try:
                self.gw()
            except Exception:
                pass
        return {"kind": "internal", "message": f"{type(e).__name__}: {e}"}

    def history_events(self, session_id, limit, before_seq=None):
        body = {"limit": limit}
        if session_id:
            body["session_id"] = session_id
        if before_seq is not None:
            body["before_seq"] = before_seq
        d = self.gw().call_json("chat.history", body=body)
        return sorted(d.get("chat_events", []), key=lambda e: e.get("seq") or 0)

    def need_chat(self):
        if not self.tracker.active:
            raise BadRequest("no chat is open; call `open` first")
        return self.tracker.session_id

    def m_ping(self, p):
        return {"pong": True}

    def m_shutdown(self, p):
        return {}

    def m_connect(self, p):
        gw = self.gw()
        st = self.load_state()
        try:
            ident = gw.call_json("identity")
        except (GatewayError, TimeoutError):
            ident = None
        return {"vm_id": gw.vm_id, "chat": chat_of(st.get("session_id"), st.get("title")),
                "identity": ident}

    def m_login(self, p):
        buf = io.StringIO()
        ok = True
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                self.run_login()
            except SystemExit:
                ok = False
        if ok:
            self.drop_gw()
            try:
                self.gw()
            except Exception as e:
                buf.write(f"signed in, but could not connect: {e}\n")
        return {"ok": ok, "log": buf.getvalue()}

    def m_sessions(self, p):
        d = self.gw().call_json("sessions.list")
        rows = [to_session(s) for s in d.get("sessions", [])
                if p.get("archived") or not s.get("archived")]
        return {"sessions": sort_sessions(rows)}

    def m_open(self, p):
        sid = _str(p, "session_id", required=False)
        title = p.get("title") if isinstance(p.get("title"), str) else None
        try:
            events = self.history_events(sid, _int(p, "limit", 40))
        except GatewayError as e:
            if sid and is_not_found(e):
                self.chat_gone(sid)
            raise
        chat = chat_of(sid, title)
        self.tracker.open(sid, events)
        self.next_poll = self.clock() + self.idle_poll
        self.save_state(dict(chat))
        return {"chat": chat, "messages": to_messages(events)}

    def m_history(self, p):
        sid = self.need_chat()
        before = p.get("before_seq")
        if before is not None:
            before = _int(p, "before_seq", None, low=1, high=2 ** 62)
        events = self.history_events(sid, _int(p, "limit", 40), before)
        self.tracker.prime(events, newest=before is None)
        return {"messages": to_messages(events)}

    def m_send(self, p):
        text = _str(p, "text")
        sid = self.need_chat()
        gw = self.gw()
        try:
            evs = self.history_events(sid, 1)
            baseline = max([e.get("seq") or 0 for e in evs] or [self.tracker.max_seq()])
        except (GatewayError, TimeoutError):
            baseline = self.tracker.max_seq()
        body = {"items": [{"type": "text", "text": text}],
                "node_id": self.config()["node_id"], "capabilities": {}}
        if sid:
            body["session_id"] = sid
        gw._open("chat.stream", body=body)
        now = self.clock()
        self.tracker.start_send(baseline, now)
        self.next_poll = now + self.send_poll
        self.later("thinking", {"session_id": sid, "since_ms": int(time.time() * 1000)})
        return {"sent": True, "baseline": baseline}

    def m_new_chat(self, p):
        title = p.get("title") if isinstance(p.get("title"), str) and p.get("title") else None
        d = cli.start_session(self.gw(), title)
        sid = d.get("session_id") or d.get("id")
        if not sid:
            raise GatewayError(-1, "session.start returned no session id")
        try:
            events = self.history_events(sid, 40)
        except (GatewayError, TimeoutError):
            events = []
        chat = chat_of(sid, d.get("title") or title or "new conversation")
        self.tracker.open(sid, events)
        self.next_poll = self.clock() + self.idle_poll
        self.save_state(dict(chat))
        return {"chat": chat}

    def m_session_op(self, p):
        op = p.get("op")
        if op not in SESSION_OPS:
            raise BadRequest(f"'op' must be one of {', '.join(SESSION_OPS)}")
        sid = _str(p, "session_id")
        title = _str(p, "title") if op == "rename" else None
        res = cli.session_op(self.gw(), op, sid, title)
        if op in ("archive", "delete"):
            self.chat_gone(sid)
        elif op == "rename" and self.load_state().get("session_id") == sid:
            self.save_state({"session_id": sid, "title": title})
        return res

    def m_status(self, p):
        gw = self.gw()
        sess = gw.call_json("sessions.list")
        unread = gw.call_json("chat.unread_count")
        ident = gw.call_json("identity")
        return {"vm_id": gw.vm_id, "sessions": len(sess.get("sessions", [])),
                "unread": unread, "identity": ident}

    def m_feed(self, p):
        limit = _int(p, "limit", 50)
        d = self.gw().call_json("feed.list", query={"limit": limit})
        units = []
        for day, ed, u in cli.feed_units(d):
            row = cli.feed_row(day, ed, u)
            row["summary"] = u.get("summary") or u.get("body_md") or u.get("kicker")
            row["reaction"] = u.get("reaction") or u.get("viewer_reaction")
            row.update({"emoji": u.get("emoji"), "kicker": u.get("kicker"), "category": u.get("category"),
                        "source": u.get("connector_attribution"), "why": u.get("why_did_i_see_this")})
            units.append(row)
        return {"units": units[:limit]}

    def m_feed_react(self, p):
        unit = _str(p, "unit")
        reaction = p.get("reaction", "love")
        if reaction not in REACTIONS:
            raise BadRequest(f"'reaction' must be one of {', '.join(REACTIONS)}")
        return self.gw().call_json("feed.unit.reaction", path_params={"unit_id": unit},
                                   body={"reaction": reaction})

    def m_goals(self, p):
        d = self.gw().call_json("goals.list")
        goals = []
        for g in d.get("goals", []):
            row = cli.goal_row(g)
            row["subtitle"] = row["subtitle"] or g.get("summary")
            goals.append(row)
        return {"goals": goals}

    def m_goal(self, p):
        return self.gw().call_json("goals.get", path_params={"id": _str(p, "id")})

    def m_ideas(self, p):
        d = self.gw().call_json("api.idea-cards.list")
        ideas = []
        for s, c in cli.idea_cards(d):
            row = cli.idea_row(s, c)
            row["summary"] = c.get("summary") or (c.get("content") or {}).get("summary")
            ideas.append(row)
        return {"ideas": ideas}

    def m_idea(self, p):
        return self.gw().call_json("api.idea-cards.detail",
                                   path_params={"ideaCardId": _str(p, "id")})

    def m_idea_exec(self, p):
        idea = _str(p, "id")
        body = {"ideaCardId": idea, "mode": "full"}
        if self.tracker.active and self.tracker.session_id:
            body["session_id"] = self.tracker.session_id
        return self.gw().call_json("api.idea-cards.execute",
                                   path_params={"ideaCardId": idea}, body=body)

    def m_tasks(self, p):
        d = self.gw().call_json("tasks.list")
        return {"tasks": [cli.task_row(s) for s in d.get("schedules", [])]}

    def m_task_runs(self, p):
        body = {"limit": _int(p, "limit", 10)}
        job = _str(p, "job", required=False)
        if job:
            body["job_id"] = job
        d = self.gw().call_json("tasks.runs", body=body)
        return {"runs": [cli.task_run_row(r) for r in d.get("runs", [])]}

    def m_email(self, p):
        gw = self.gw()
        mailbox = gw.call_json("email.mailbox.get")
        d = gw.call_json("email.threads.list", body={})
        return {"mailbox": mailbox, "threads": [cli.email_thread_row(t) for t in d.get("data", [])]}

    def m_email_thread(self, p):
        d = self.gw().call_json("email.threads.get", path_params={"thread_id": _str(p, "id")})
        return {"messages": [cli._email_message(m) for m in d.get("messages", [])
                             if isinstance(m, dict)]}

    def m_files(self, p):
        sid = self.need_chat()
        rows = []
        # 200 is as far back as one chat.history call reaches.
        for m in reversed(to_messages(self.history_events(sid, _int(p, "limit", 200)))):
            for f in m["files"]:
                rows.append({"seq": m["seq"], "message_id": m["id"], **f})
        return {"files": [{k: r.get(k) for k in FILE_KEYS} for r in rows]}

    def m_download(self, p):
        path = _str(p, "path")
        if not (path.startswith("sandbox://") or "/media/raw/" in path):
            raise BadRequest("'path' must be a sandbox:// path or a media URL")
        directory = _str(p, "dir", required=False)
        directory = os.path.expanduser(directory) if directory else self.download_dir()
        return {"rows": cli.save_resources(self.gw(), [{"path": path}], directory)}


def handle(backend, writer, raw):
    """Answer one request line; False when the bridge should exit."""
    try:
        req = json.loads(raw)
    except ValueError as e:
        writer.send({"id": None, "error": {"kind": "bad_request", "message": f"bad JSON: {e}"}})
        return True
    rid = req.get("id") if isinstance(req, dict) else None
    method = req.get("method") if isinstance(req, dict) else None
    try:
        if not isinstance(method, str):
            raise BadRequest("a request is an object with 'id' and 'method'")
        result = backend.dispatch(method, req.get("params") or {})
    except Exception as e:
        backend.after.clear()
        writer.send({"id": rid, "error": backend.error_of(e)})
        return True
    writer.send({"id": rid, "result": result})
    for name, data in backend.after:
        writer.event(name, data)
    backend.after.clear()
    return method != "shutdown"


def serve(backend, fd, writer):
    """Read requests from file descriptor fd until EOF or `shutdown`."""
    q = queue.Queue()

    def reader():
        # os.read, not sys.stdin: a daemon thread blocked inside a buffered
        # reader aborts the interpreter at exit.
        buf = b""
        try:
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        q.put(line.decode("utf-8", "replace"))
            if buf.strip():
                q.put(buf.decode("utf-8", "replace"))
        except OSError:
            pass
        finally:
            q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    try:
        while True:
            timeout = min(1.0, max(0.01, backend.next_wake() - backend.clock()))
            try:
                raw = q.get(timeout=timeout)
            except queue.Empty:
                raw = ""
            if raw is None:
                break
            if raw and not handle(backend, writer, raw):
                break
            try:
                backend.tick()
            except Exception as e:
                backend.emit("log", {"level": "error", "text": f"poll failed: {e}"})
    finally:
        backend.close()


def isolate_stdout():
    """Keep fd 1 for the protocol; send stray prints to stderr instead."""
    sys.stdout.flush()
    fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return os.fdopen(fd, "w", encoding="utf-8", newline="\n")


def make_backend(demo, emit):
    if demo:
        from .demo import DemoBackend
        return DemoBackend(emit)
    return Backend(emit)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m muse_cli.bridge",
                                 description="JSON-lines bridge for the muse-cli app")
    ap.add_argument("--demo", action="store_true", help="made-up data, no network")
    args = ap.parse_args(argv)
    demo = args.demo or os.environ.get("MUSE_CLI_DEMO") == "1"
    writer = Writer(isolate_stdout())
    try:
        writer.event("ready", {"version": __version__, "demo": demo})
        serve(make_backend(demo, writer.event), sys.stdin.fileno(), writer)
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    try:
        writer.fh.close()
    except OSError:
        pass


if __name__ == "__main__":
    main()
