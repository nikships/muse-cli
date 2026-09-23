"""muse-cli: CLI for your personal muse.ai agent. No browser needed (after cookie export).

Setup:
  1. Log in to https://muse.ai/ in Chrome (Auth profile).
  2. muse-cli auth export   # saves session cookies locally (chmod 600)

Then: muse-cli status | muse-cli threads | muse-cli history | muse-cli send "hello" | ...
"""
import argparse
import json
import os
import shutil
import sys
import time

from . import __version__
from .gateway import Gateway, AuthError, GatewayError, load_cookies

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
    if not os.path.exists(cfg["cookies_file"]):
        raise AuthError(f"no cookies at {cfg['cookies_file']}; log in to https://muse.ai/ "
                        "in Chrome, then run `muse-cli auth export`")
    cookies = load_cookies(cfg["cookies_file"])
    if not cookies.strip():
        raise AuthError(f"cookies file {cfg['cookies_file']} is empty; run `muse-cli auth export`")
    return Gateway(cookies, vm_id=cfg.get("vm_id"))


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _browser_run(argv):
    """Run agent-browser, parsing its JSON envelope. NOTE: it exits 0 even
    on failure, reporting {"success": false, "error": ...} on stdout."""
    import subprocess
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[:200] or f"exit {r.returncode}")
    try:
        doc = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError((r.stdout or r.stderr)[:200] or "empty output")
    if isinstance(doc, dict) and doc.get("success") is False:
        raise RuntimeError(str(doc.get("error") or "unknown error")[:200])
    return doc.get("data", {}) if isinstance(doc, dict) else doc


def _browser_cookies(headed):
    """Read the cookie jar via agent-browser. Headed auto-connect attaches
    to the user's real Chrome; plain mode uses a fresh browser (no login)."""
    base = ["agent-browser"] + (["--headed", "--auto-connect"] if headed else [])
    if shutil.which("agent-browser") is None:
        print("agent-browser not found; install it with: npm i -g agent-browser", file=sys.stderr)
        print("alternative: export cookies by hand, see README Setup notes.", file=sys.stderr)
        sys.exit(1)
    last_err = "unknown error"
    for _ in range(3):
        try:
            if headed:
                # Cookies follow the active tab: focus a muse.ai tab first,
                # else the export comes back empty even when logged in.
                data = _browser_run(base + ["tab", "list", "--json"])
                tabs = data.get("tabs", []) if isinstance(data, dict) else []
                muse_tabs = [t for t in tabs
                             if isinstance(t, dict) and "muse.ai" in (t.get("url") or "")
                             and (t.get("id") or t.get("tabId"))]
                if not muse_tabs:
                    return None, "no muse.ai tab open in Chrome"
                _browser_run(base + ["tab", muse_tabs[0].get("id") or muse_tabs[0]["tabId"]])
            data = _browser_run(base + ["cookies", "get", "--json"])
            jar = data.get("cookies", []) if isinstance(data, dict) else []
            return [c for c in jar if "muse.ai" in c.get("domain", "")], None
        except RuntimeError as e:
            last_err = str(e)
            time.sleep(2)
    return None, last_err


def cmd_auth_export(_args):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    jar, err = _browser_cookies(headed=True)
    if jar is None and err != "no muse.ai tab open in Chrome":
        # Headed attach failed (no Chrome, old agent-browser, ...): a plain
        # browser shares no login, so this is a last resort at best.
        jar, err = _browser_cookies(headed=False)
    if jar is None:
        print(f"cookie export failed: {err}", file=sys.stderr)
        print("is Chrome running with muse.ai open?", file=sys.stderr)
        print("alternative: export cookies by hand, see README Setup.", file=sys.stderr)
        sys.exit(1)
    # Never clobber a working login with an empty or logged-out jar.
    if not any(c["name"] == "hatch_sess" for c in jar):
        print("refusing to overwrite cookies: no hatch_sess in export "
              "(are you logged in to muse.ai?). Existing file left intact.",
              file=sys.stderr)
        sys.exit(1)
    lines = ["# Netscape HTTP Cookie File"]
    for c in jar:
        dom = c["domain"]
        lines.append("\t".join([
            dom, "TRUE" if dom.startswith(".") else "FALSE", c.get("path", "/"),
            "TRUE" if c.get("secure") else "FALSE",
            str(int(c.get("expires", 0) or 0)), c["name"], c["value"],
        ]))
    if os.path.exists(COOKIES_FILE):
        os.replace(COOKIES_FILE, COOKIES_FILE + ".bak")
    with open(COOKIES_FILE, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(COOKIES_FILE, 0o600)
    print(f"saved {len(jar)} muse.ai cookies to {COOKIES_FILE}")


def cmd_status(_args):
    gw = connect(load_config())
    try:
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


def is_reply(ev, baseline):
    """True for a genuine assistant reply (not a proactive push).

    In history, genuine replies are message.assistant events with an empty
    reply_to_message_id; proactive pushes (Telegram drafts, background task
    updates) are self-referential there.
    """
    if ev.get("event_name") != "message.assistant":
        return False
    if (ev.get("seq") or 0) <= baseline:
        return False
    p = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
    if (ev.get("reply_to_message_id") or p.get("reply_to_message_id")):
        return False
    if not (p.get("display_text") or p.get("content")):
        return False
    if "display_text_ready" in p and not p["display_text_ready"]:
        return False
    return True


def cmd_send(args):
    cfg = load_config()
    gw = connect(cfg)
    try:
        params = {"items": [{"type": "text", "text": args.text}],
                  "node_id": cfg["node_id"], "capabilities": {}}
        if args.thread:
            params["session_id"] = args.thread
        # chat.history without session_id reads the main chat; with it, the
        # thread. Either way the scope matches where the reply will land.
        scope = {"session_id": args.thread} if args.thread else {}
        baseline = 0
        try:
            h = gw.call_json("chat.history", body={"limit": 1, **scope})
            evs = h.get("chat_events", [])
            if evs:
                baseline = max(e.get("seq", 0) for e in evs)
        except (GatewayError, TimeoutError):
            pass
        stream_sid = gw._open("chat.stream", body=params)
        if not args.wait:
            out({"sent": True, "stream": stream_sid,
                 "note": "fire-and-forget; check `muse-cli history` for the reply"})
            return

        # The reply is picked up by polling history, not by watching the
        # live stream: threaded replies never arrive as live events, live
        # chat events use delta.* shapes (not message.*), and only the
        # history shape carries the reply_to discriminator that tells
        # genuine replies apart from proactive pushes. Sequential unary
        # calls also mean a single frame consumer: no Noise races, ever.
        reply, deadline = None, time.time() + args.wait
        while time.time() < deadline and reply is None:
            try:
                h = gw.call_json("chat.history", body={"limit": 10, **scope})
            except (GatewayError, TimeoutError):
                time.sleep(4)
                continue
            for ev in sorted(h.get("chat_events", []), key=lambda e: e.get("seq", 0)):
                if is_reply(ev, baseline):
                    reply = fmt_event(ev)
                    break
            if reply is None:
                time.sleep(4)
        result = {"sent": True, "stream": stream_sid}
        if reply:
            result["reply"] = reply
        else:
            result["note"] = f"no assistant reply within {args.wait}s; check `muse-cli history`"
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
            for k in ("display_text", "content", "text", "activity_text", "status"):
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
        out(rows[:args.limit] if args.limit else rows)
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
    from .gateway import _hatch_headers, fetch_access_token, fetch_session_info
    from curl_cffi import requests as rq
    cookies = load_cookies(cfg["cookies_file"])
    at = fetch_access_token(cookies)
    vm_id = cfg.get("vm_id") or fetch_session_info(cookies)["vm_id"]
    resp = rq.post("https://muse.ai/api/hatch/vm/wake", headers=_hatch_headers(cookies, at),
                   json={"vm_id": vm_id, "retry_count": 0},
                   impersonate="chrome", timeout=15)
    out({"status": resp.status_code, "body": resp.json() if resp.text else None})


def cmd_raw(args):
    from .gateway import ROUTES
    if args.method not in ROUTES:
        print(f"unknown method '{args.method}' (see routes.json for the {len(ROUTES)} known methods)",
              file=sys.stderr)
        sys.exit(2)
    try:
        body = json.loads(args.body) if args.body else None
    except json.JSONDecodeError as e:
        print(f"invalid --body JSON: {e}", file=sys.stderr)
        sys.exit(2)
    pp = {}
    for kv in (args.param or []):
        if "=" not in kv:
            print(f"bad --param '{kv}': expected k=v", file=sys.stderr)
            sys.exit(2)
        k, v = kv.split("=", 1)
        pp[k] = v
    gw = connect(load_config())
    try:
        data = gw.request(args.method, path_params=pp or None, body=body,
                          query=None, timeout=args.timeout)
        try:
            out(json.loads(data) if data else {})
        except json.JSONDecodeError:
            print(data.decode("utf-8", "replace"))
    finally:
        gw.close()


def main():
    ap = argparse.ArgumentParser(prog="muse-cli", description="CLI for your personal muse.ai agent")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
