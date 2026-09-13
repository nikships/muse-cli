#!/usr/bin/env python3
"""muse: CLI for your personal muse.ai agent. No browser needed (after cookie export).

Setup:
  1. Log in to https://muse.ai/ in Chrome (Auth profile).
  2. muse auth export   # saves session cookies locally (chmod 600)

Then: muse status | muse threads | muse history | muse send "hello" | ...
"""
import argparse
import json
import os
import sys
import time
import threading
import queue as queue_mod

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from muse import Gateway, AuthError, GatewayError, load_cookies  # noqa: E402

CONFIG_DIR = os.path.expanduser("~/.config/muse-cli")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
COOKIES_FILE = os.path.join(CONFIG_DIR, "cookies.txt")


def load_config():
    import secrets
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        cfg = json.load(open(CONFIG_FILE))
    changed = False
    cfg.setdefault("cookies_file", COOKIES_FILE)
    if "vm_id" not in cfg and os.environ.get("MUSE_VM_ID"):
        cfg["vm_id"] = os.environ["MUSE_VM_ID"]
    if "node_id" not in cfg:
        if os.environ.get("MUSE_NODE_ID"):
            cfg["node_id"] = os.environ["MUSE_NODE_ID"]
        else:
            cfg["node_id"] = secrets.token_hex(8)
            changed = True
    if changed:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        json.dump(cfg, open(CONFIG_FILE, "w"), indent=2)
    return cfg


def connect(cfg):
    cookies = load_cookies(cfg["cookies_file"])
    if not cookies.strip():
        raise AuthError(f"cookies file {cfg['cookies_file']} is empty; run `muse auth export`")
    return Gateway(cookies, vm_id=cfg.get("vm_id"))


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_auth_export(_args):
    import subprocess
    os.makedirs(CONFIG_DIR, exist_ok=True)
    r = None
    for argv in (["agent-browser", "cookies", "get", "--json"],
                 ["agent-browser", "--headed", "--auto-connect", "cookies", "get", "--json"]):
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode == 0:
            break
    if r is None or r.returncode != 0:
        print("cookie export failed; is Chrome running with muse.ai open?", file=sys.stderr)
        print("alternative: export cookies by hand, see README Setup.", file=sys.stderr)
        if r is not None:
            print(r.stderr[:500], file=sys.stderr)
        sys.exit(1)
    data = json.loads(r.stdout)["data"]["cookies"]
    jar = [c for c in data if "muse.ai" in c.get("domain", "")]
    if not any(c["name"] == "hatch_sess" for c in jar):
        print("warning: no hatch_sess cookie found; are you logged in to muse.ai?", file=sys.stderr)
    lines = ["# Netscape HTTP Cookie File"]
    for c in jar:
        dom = c["domain"]
        lines.append("\t".join([
            dom, "TRUE" if dom.startswith(".") else "FALSE", c.get("path", "/"),
            "TRUE" if c.get("secure") else "FALSE",
            str(int(c.get("expires", 0) or 0)), c["name"], c["value"],
        ]))
    with open(COOKIES_FILE, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(COOKIES_FILE, 0o600)
    print(f"saved {len(jar)} muse.ai cookies to {COOKIES_FILE}")


def cmd_status(_args):
    gw = connect(load_config())
    try:
        from muse import fetch_access_token  # noqa
        sess = gw.call_json("sessions.list")
        unread = gw.call_json("chat.unread_count")
        ident = gw.call_json("identity")
        out({"vm_id": gw.vm_id, "sessions": len(sess.get("sessions", [])),
             "unread": unread, "identity": ident})
    finally:
        gw.close()


def cmd_threads(args):
    gw = connect(load_config())
    try:
        d = gw.call_json("sessions.list")
        rows = [{
            "session_id": s.get("session_id"),
            "title": s.get("title"),
            "thread": s.get("is_thread"),
            "pinned": s.get("pinned"),
            "archived": s.get("archived"),
            "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(s.get("updated_at_ms", 0) / 1000)),
        } for s in d.get("sessions", [])]
        if args.archived is False:
            rows = [r for r in rows if not r["archived"]]
        out(rows)
    finally:
        gw.close()


def fmt_event(e):
    p = e.get("payload", {}) if isinstance(e.get("payload"), dict) else {}
    role = p.get("role") or e.get("event_name")
    text = p.get("display_text") or p.get("content") or ""
    return {"seq": e.get("seq"), "role": role,
            "message_id": p.get("message_id") or e.get("message_id"),
            "text": text}


def cmd_history(args):
    gw = connect(load_config())
    try:
        params = {"limit": args.limit}
        if args.thread:
            params["session_id"] = args.thread
        d = gw.call_json("chat.history", body=params)
        events = d.get("chat_events", [])
        if args.raw:
            out(d)
            return
        out([fmt_event(e) for e in events if (e.get("payload", {}) or {}).get("display_text")
             or (e.get("payload", {}) or {}).get("content")])
    finally:
        gw.close()


def cmd_send(args):
    cfg = load_config()
    gw = connect(cfg)
    try:
        params = {"items": [{"type": "text", "text": args.text}],
                  "node_id": cfg["node_id"], "capabilities": {}}
        if args.thread:
            params["session_id"] = args.thread
        # Open a live subscription first so we can watch the reply arrive.
        q: queue_mod.Queue = queue_mod.Queue()
        stop = False

        def reader():
            try:
                while not stop:
                    q.put(gw._read_frame())
            except Exception as e:  # noqa: BLE001
                q.put(e)

        threading.Thread(target=reader, daemon=True).start()
        from muse import ApplicationRequest, ServiceFrame
        import uuid as uuid_mod
        sub_body = json.dumps({"capabilities": {}}).encode()
        req = ApplicationRequest(verb="POST", path="/chat/subscribe", body=sub_body, end_body=True)
        h = req.headers.add(); h.key = "x-request-id"; h.value = str(uuid_mod.uuid4())
        h2 = req.headers.add(); h2.key = "content-type"; h2.value = "application/json"
        fr = ServiceFrame(stream_id=gw.stream)
        fr.request.CopyFrom(req)
        sub_sid = gw.stream; gw.stream += 1
        gw._send_envelope(0, fr.SerializeToString())

        stream_sid = gw._open("chat.stream", body=params)
        baseline = 0
        try:
            h = gw.call_json("chat.history", body={"limit": 1,
                             **({"session_id": args.thread} if args.thread else {})})
            evs = h.get("chat_events", [])
            if evs:
                baseline = max(e.get("seq", 0) for e in evs)
        except (GatewayError, TimeoutError):
            pass
        sent, bufs, reply = baseline, {}, None
        deadline = time.time() + args.wait
        while time.time() < deadline:
            try:
                sf = q.get(timeout=2)
            except queue_mod.Empty:
                continue
            if isinstance(sf, Exception):
                raise sf
            kind = sf.WhichOneof("kind")
            if kind == "response":
                if sf.response.body:
                    bufs[sf.stream_id] = bufs.get(sf.stream_id, b"") + bytes(sf.response.body)
            elif kind == "body_chunk":
                bufs[sf.stream_id] = bufs.get(sf.stream_id, b"") + bytes(sf.body_chunk.data)
            elif kind == "reset":
                continue
            buf = bufs.get(sf.stream_id, b"")
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                bufs[sf.stream_id] = buf
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                p = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
                if ev.get("event") == "message.assistant" and (ev.get("seq") or 0) > baseline \
                        and isinstance(p.get("display_text"), str) and p["display_text"]:
                    reply = fmt_event(ev)
                    break
            if reply:
                break
        result = {"sent": True, "stream": stream_sid}
        if reply:
            result["reply"] = reply
        elif args.wait:
            result["note"] = f"no assistant reply within {args.wait}s; check `muse history`"
        out(result)
    finally:
        gw.close()


def cmd_watch(args):
    gw = connect(load_config())
    try:
        recs = gw.subscribe_json("chat.subscribe", body={"capabilities": {}},
                                 max_records=args.n, idle_timeout=8,
                                 overall_timeout=args.timeout)
        for ev in recs:
            et = ev.get("event", ev.get("type"))
            if et in ("agent.status",) and not args.all:
                continue
            p = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
            row = {"event": et, "seq": ev.get("seq")}
            for k in ("display_text", "content", "activity_text", "status"):
                if p.get(k):
                    row[k] = str(p[k])[:300]
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        gw.close()


def cmd_feed(args):
    gw = connect(load_config())
    try:
        d = gw.call_json("feed.list", query={"limit": args.limit} if args.limit else None)
        if args.raw:
            out(d); return
        rows = []
        for day in d.get("days", []):
            for ed in day.get("editions", []):
                for u in ed.get("units", []):
                    rows.append({"id": u.get("unit_id"),
                                 "title": u.get("title"),
                                 "date": day.get("local_date"),
                                 "edition": ed.get("kind")})
                    if args.limit and len(rows) >= args.limit:
                        break
        out(rows)
    finally:
        gw.close()


def cmd_feed_status(_args):
    gw = connect(load_config())
    try:
        out(gw.call_json("feed.status"))
    finally:
        gw.close()


def cmd_feed_react(args):
    gw = connect(load_config())
    try:
        out(gw.call_json("feed.unit.reaction", path_params={"unit_id": args.unit},
                         body={"reaction": args.reaction}))
    finally:
        gw.close()


def cmd_feed_prompt(_args):
    gw = connect(load_config())
    try:
        out(gw.call_json("feed.prompt.get"))
    finally:
        gw.close()


def cmd_goals(_args):
    gw = connect(load_config())
    try:
        d = gw.call_json("goals.list")
        out([{"id": g.get("id") or g.get("goal_id"), "title": g.get("title"),
              "status": g.get("status"), "subtitle": g.get("subtitle")}
             for g in d.get("goals", [])])
    finally:
        gw.close()


def cmd_goal(args):
    gw = connect(load_config())
    try:
        out(gw.call_json("goals.get", path_params={"id": args.id}))
    finally:
        gw.close()


def cmd_ideas(_args):
    gw = connect(load_config())
    try:
        d = gw.call_json("api.idea-cards.list")
        rows = []
        for s in d.get("sections", []):
            for c in s.get("cards", s.get("ideas", [])):
                rows.append({"id": c.get("id") or c.get("ideaCardId"),
                             "title": c.get("title"), "section": s.get("title")})
        out(rows)
    finally:
        gw.close()


def cmd_idea(args):
    gw = connect(load_config())
    try:
        out(gw.call_json("api.idea-cards.detail", path_params={"ideaCardId": args.id}))
    finally:
        gw.close()


def cmd_idea_exec(args):
    gw = connect(load_config())
    try:
        body = {"ideaCardId": args.id, "mode": "full"}
        if args.thread:
            body["session_id"] = args.thread
        out(gw.call_json("api.idea-cards.execute", path_params={"ideaCardId": args.id}, body=body))
    finally:
        gw.close()


def cmd_unread(_args):
    gw = connect(load_config())
    try:
        out(gw.call_json("chat.unread_count"))
    finally:
        gw.close()


def cmd_seen(args):
    gw = connect(load_config())
    try:
        out(gw.call_json("chat.mark_seen", path_params={"thread_id": args.thread}))
    finally:
        gw.close()


def cmd_session_start(args):
    gw = connect(load_config())
    try:
        params = {"origin": "fresh", "lifecycle": "persistent"}
        if args.title:
            params["title"] = args.title
        out(gw.call_json("session.start",
                         body={"method": "/api/session/start", "params": params}))
    finally:
        gw.close()


def cmd_session_op(kind):
    def run(args):
        gw = connect(load_config())
        try:
            if kind == "rename":
                body = {"session_id": args.id, "title": args.title}
            else:
                body = {"method": f"/api/session/{kind}", "session_id": args.id}
            out(gw.call_json(f"session.{kind}", body=body))
        finally:
            gw.close()
    return run


def cmd_wake(_args):
    cfg = load_config()
    from muse import _hatch_headers, fetch_access_token, fetch_session_info, load_cookies
    from curl_cffi import requests as rq
    cookies = load_cookies(cfg["cookies_file"])
    at = fetch_access_token(cookies)
    vm_id = cfg.get("vm_id") or fetch_session_info(cookies)["vm_id"]
    resp = rq.post("https://muse.ai/api/hatch/vm/wake", headers=_hatch_headers(cookies, at),
                   json={"vm_id": vm_id, "retry_count": 0},
                   impersonate="chrome", timeout=15)
    out({"status": resp.status_code, "body": resp.json() if resp.text else None})


def cmd_raw(args):
    gw = connect(load_config())
    try:
        body = json.loads(args.body) if args.body else None
        pp = dict(kv.split("=", 1) for kv in (args.param or []))
        data = gw.request(args.method, path_params=pp or None, body=body,
                          query=None, timeout=args.timeout)
        try:
            out(json.loads(data) if data else {})
        except json.JSONDecodeError:
            print(data.decode("utf-8", "replace"))
    finally:
        gw.close()


def main():
    ap = argparse.ArgumentParser(prog="muse", description="CLI for your personal muse.ai agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("auth", help="auth helpers"); a = p.add_subparsers(dest="op", required=True)
    a.add_parser("export", help="export Chrome session cookies for the CLI").set_defaults(fn=cmd_auth_export)

    sub.add_parser("status", help="VM, session count, unread, identity").set_defaults(fn=cmd_status)
    p = sub.add_parser("threads", help="list chats and side chats")
    p.add_argument("--all", dest="archived", action="store_true", help="include archived")
    p.set_defaults(fn=cmd_threads)
    p = sub.add_parser("history", help="read chat messages")
    p.add_argument("--thread", default=None); p.add_argument("--limit", type=int, default=10)
    p.add_argument("--raw", action="store_true"); p.set_defaults(fn=cmd_history)
    p = sub.add_parser("send", help="send the agent a message")
    p.add_argument("text"); p.add_argument("--thread", default=None)
    p.add_argument("--wait", type=int, default=90, help="seconds to wait for reply (0 = don't)")
    p.set_defaults(fn=cmd_send)
    p = sub.add_parser("watch", help="tail live agent events")
    p.add_argument("--timeout", type=int, default=60); p.add_argument("--n", type=int, default=50)
    p.add_argument("--all", action="store_true"); p.set_defaults(fn=cmd_watch)
    p = sub.add_parser("feed", help="list feed units")
    p.add_argument("--limit", type=int, default=None); p.add_argument("--raw", action="store_true")
    p.set_defaults(fn=cmd_feed)
    sub.add_parser("feed-status", help="feed refresh status").set_defaults(fn=cmd_feed_status)
    p = sub.add_parser("feed-react", help="react to a feed unit")
    p.add_argument("unit"); p.add_argument("reaction", nargs="?", default="love")
    p.set_defaults(fn=cmd_feed_react)
    sub.add_parser("feed-prompt", help="show feed prompt").set_defaults(fn=cmd_feed_prompt)
    sub.add_parser("goals", help="list goals").set_defaults(fn=cmd_goals)
    p = sub.add_parser("goal", help="show one goal"); p.add_argument("id"); p.set_defaults(fn=cmd_goal)
    sub.add_parser("ideas", help="list idea cards").set_defaults(fn=cmd_ideas)
    p = sub.add_parser("idea", help="show one idea"); p.add_argument("id"); p.set_defaults(fn=cmd_idea)
    p = sub.add_parser("idea-exec", help="execute an idea (agent acts on it)")
    p.add_argument("id"); p.add_argument("--thread", default=None); p.set_defaults(fn=cmd_idea_exec)
    sub.add_parser("unread", help="unread counts").set_defaults(fn=cmd_unread)
    p = sub.add_parser("seen", help="mark a thread seen"); p.add_argument("thread")
    p.set_defaults(fn=cmd_seen)
    p = sub.add_parser("session-start", help="start a new side chat")
    p.add_argument("--title", default=None); p.set_defaults(fn=cmd_session_start)
    for kind, help_text in [("rename", "rename a session"), ("pin", "pin a session"),
                            ("unpin", "unpin a session"), ("archive", "archive a session"),
                            ("unarchive", "unarchive a session"), ("delete", "delete a session")]:
        p = sub.add_parser(f"session-{kind}", help=help_text)
        p.add_argument("id")
        if kind == "rename":
            p.add_argument("title")
        p.set_defaults(fn=cmd_session_op(kind))
    sub.add_parser("wake", help="request a VM wake").set_defaults(fn=cmd_wake)
    p = sub.add_parser("raw", help="call any gateway method (escape hatch)")
    p.add_argument("method"); p.add_argument("--body", default=None)
    p.add_argument("--param", action="append", default=[], help="path param k=v (repeatable)")
    p.add_argument("--timeout", type=int, default=30); p.set_defaults(fn=cmd_raw)

    args = ap.parse_args()
    try:
        args.fn(args)
    except AuthError as e:
        print(f"auth error: {e}", file=sys.stderr)
        sys.exit(2)
    except GatewayError as e:
        print(f"gateway error: {e}", file=sys.stderr)
        sys.exit(3)
    except TimeoutError as e:
        print(f"timeout: {e}", file=sys.stderr)
        sys.exit(4)


if __name__ == "__main__":
    main()
