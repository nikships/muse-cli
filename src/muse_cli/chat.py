"""Interactive chat with your muse.ai agent: `muse-cli chat` (or bare `muse-cli`).

Plain, line-by-line text so it reads well in a terminal and with a screen
reader. Picks up the conversation you used last. Type /help for commands.
"""
import json
import os
import time

from .cli import CONFIG_DIR, cmd_auth_export, connect, fmt_event, load_config
from .gateway import AuthError, GatewayError

WAIT = 300   # seconds to wait for the first reply
QUIET = 10   # seconds of silence after a reply before taking the next message
STATE = os.path.join(CONFIG_DIR, "chat.json")

HELP = """Commands:
  /chats          list your conversations
  /open N         switch to conversation number N from /chats
  /main           switch to your main chat
  /new [title]    start a new conversation
  /history [N]    read the last N messages here (default 10)
  /login          save your muse.ai login from Chrome again (same as `muse-cli auth export`)
  /exit           quit (Ctrl+C works too)"""


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, ValueError):
        return {"session_id": None, "title": "main chat"}


def save_state(st):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    json.dump(st, open(STATE, "w"), indent=2)


class Chat:
    def __init__(self):
        self.cfg = load_config()
        self.st = load_state()
        self.gw = connect(self.cfg)
        self.listing = []

    def scope(self):
        return {"session_id": self.st["session_id"]} if self.st["session_id"] else {}

    def events(self, limit):
        evs = self.gw.call_json("chat.history", body={"limit": limit, **self.scope()})
        return sorted(evs.get("chat_events", []), key=lambda e: e.get("seq", 0))

    def messages(self, limit):
        out = []
        for ev in self.events(limit):
            m = fmt_event(ev)
            name = ev.get("event_name", "")
            if m["text"] and name in ("message.user", "message.assistant"):
                out.append(("You" if name == "message.user" else "Muse", m["text"]))
        return out

    def show_history(self, n=10):
        msgs = self.messages(n * 3)[-n:]
        if not msgs:
            print("No messages here yet.")
        for who, text in msgs:
            print(f"\n{who}: {text}")

    def last_seq(self):
        evs = self.events(1)
        return evs[-1].get("seq", 0) if evs else 0

    def new_replies(self, after):
        found = []
        for ev in self.events(15):
            p = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            if (ev.get("event_name") == "message.assistant" and ev.get("seq", 0) > after
                    and p.get("display_text_ready", True) and fmt_event(ev)["text"]):
                found.append(ev)
        return found

    def send(self, text):
        seen = self.last_seq()
        body = {"items": [{"type": "text", "text": text}],
                "node_id": self.cfg["node_id"], "capabilities": {}, **self.scope()}
        self.gw._open("chat.stream", body=body)
        print("Muse is thinking...")
        deadline, got_any = time.time() + WAIT, False
        while time.time() < deadline:
            time.sleep(3)
            try:
                evs = self.new_replies(seen)
            except (GatewayError, TimeoutError):
                continue
            for ev in evs:
                print(f"\nMuse: {fmt_event(ev)['text']}")
                seen = ev["seq"]
            if evs:
                got_any = True
                # keep listening briefly: the agent often sends follow-ups
                deadline = time.time() + QUIET
        if not got_any:
            print(f"(No reply within {WAIT} seconds. Type /history later to check.)")

    def list_chats(self):
        d = self.gw.call_json("sessions.list")
        self.listing = [s for s in d.get("sessions", []) if not s.get("archived")]
        for i, s in enumerate(self.listing, 1):
            when = time.strftime("%Y-%m-%d %H:%M",
                                 time.localtime(s.get("updated_at_ms", 0) / 1000))
            main = "" if s.get("is_thread") else " (main chat)"
            print(f"{i}. {s.get('title') or 'untitled'}{main}, updated {when}")
        print("Type /open and a number to switch.")

    def switch(self, session_id, title):
        self.st = {"session_id": session_id, "title": title}
        save_state(self.st)
        print(f"Now in: {title}")
        self.show_history(3)

    def open_chat(self, arg):
        if not self.listing:
            self.list_chats()
            return
        try:
            n = int(arg)
        except ValueError:
            print("Type /open and a number from /chats.")
            return
        if 1 <= n <= len(self.listing):
            s = self.listing[n - 1]
            self.switch(s["session_id"], s.get("title") or "untitled")
        else:
            print("No conversation with that number. Type /chats to see them.")

    def new_chat(self, title):
        params = {"origin": "fresh", "lifecycle": "persistent"}
        if title:
            params["title"] = title
        d = self.gw.call_json("session.start",
                              body={"method": "/api/session/start", "params": params})
        self.switch(d.get("session_id") or d.get("id"), title or "new conversation")

    def reconnect(self):
        self.gw.close()
        self.gw = connect(self.cfg)

    def handle(self, line):
        cmd, _, arg = line.partition(" ")
        arg = arg.strip()
        if cmd in ("/help", "/?"):
            print(HELP)
        elif cmd == "/chats":
            self.list_chats()
        elif cmd == "/open":
            self.open_chat(arg)
        elif cmd == "/main":
            self.switch(None, "main chat")
        elif cmd == "/new":
            self.new_chat(arg)
        elif cmd == "/history":
            self.show_history(int(arg) if arg.isdigit() else 10)
        elif cmd == "/login":
            if login():
                self.reconnect()
                print("Signed in.")
        else:
            print("Unknown command. Type /help.")


def login():
    """Re-run `auth export`; True when fresh cookies were saved."""
    try:
        cmd_auth_export(None)
        return True
    except SystemExit:
        return False


def start():
    try:
        return Chat()
    except AuthError as e:
        print(f"Can't sign in to muse.ai: {e}")
        if login():
            return Chat()
        raise


def cmd_chat(_args):
    chat = start()
    print(f"Muse chat, in: {chat.st['title']}. Type /help for commands, /exit to quit.")
    chat.show_history(3)
    try:
        while True:
            try:
                line = input("\nYou: ").strip()
            except EOFError:
                break
            if not line:
                continue
            if line.lower() in ("/exit", "/quit", "exit", "quit"):
                break
            try:
                chat.handle(line) if line.startswith("/") else chat.send(line)
            except AuthError:
                print("Your login expired. Type /login to sign in again.")
            except Exception as e:  # dropped connection: reconnect so the next try works
                print(f"Connection problem ({e}). Reconnected; please try again.")
                try:
                    chat.reconnect()
                except Exception as e2:
                    print(f"Still can't connect: {e2}")
    except KeyboardInterrupt:
        pass
    finally:
        chat.gw.close()
    print("\nBye.")
