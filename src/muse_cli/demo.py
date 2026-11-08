"""Made-up data for `muse-cli tui --demo`: a fake gateway, no network.

DemoGateway answers the same methods with the same shapes as the real
server, so the bridge runs its normal code path. Replies stream in like a
real one: the assistant event appears without a status, its text grows,
then it completes. MUSE_CLI_DEMO_SPEED=N plays every delay N times faster.
"""
import copy
import datetime
import os
import random
import re
import struct
import time
import zlib

from .bridge import Backend
from .gateway import GatewayError

MAIN = "demo-main"
MINUTE = 60 * 1000
HOUR = 60 * MINUTE
DAY = 24 * HOUR


def _png(w=96, h=64):
    """A small gradient PNG, so a demo download is a real image."""
    rows = b""
    for y in range(h):
        rows += b"\x00" + b"".join(bytes((40 + x * 2, 90 + y * 2, 230 - x)) for x in range(w))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


POSTER = _png()

MAIN_CHAT = [
    ("user", "Good morning! What's on my plate today?"),
    ("assistant", "## Good morning\n\nHere's your Saturday at a glance:\n\n"
     "- **9:30** Farmers market run (the stone-fruit stall closes early)\n"
     "- **12:00** Lunch with Sam at *Pequeno*\n"
     "- **15:00** Q4 launch review, the deck is in your drafts\n"
     "- **Evening** free, unless the sourdough starter needs feeding\n\n"
     "It's 21°C and sunny, so the market is a great call."),
    ("user", "Can you find me a good ramen place near the office for Thursday?"),
    ("assistant", "### Three ramen picks near the office\n\n"
     "1. **Menya Kaze**: rich tonkotsu, a 6 minute walk. It books out by noon, so I'd reserve.\n"
     "2. **Shio & Co.**: lighter shio broth and a great vegetarian bowl.\n"
     "3. **Noodle Theory**: counter seats only, the fastest lunch of the three.\n\n"
     "Want me to book Menya Kaze for 12:30 on Thursday?"),
    ("user", "Yes please, table for two."),
    ("assistant", "Done. **Menya Kaze**, Thursday 12:30, table for two.\n\n"
     "I added it to your calendar with a reminder 20 minutes before. "
     "Confirmation code: `MK-4821`."),
    ("user", "Write me a tiny script that renames my vacation photos by date"),
    ("assistant", "Here you go. It renames every `.jpg` in the folder to the time it was taken:\n\n"
     "```python\nfrom datetime import datetime\nfrom pathlib import Path\n\n"
     "folder = Path(\"~/Pictures/Lisbon\").expanduser()\n"
     "for photo in sorted(folder.glob(\"*.jpg\")):\n"
     "    taken = datetime.fromtimestamp(photo.stat().st_mtime)\n"
     "    photo.rename(photo.with_name(taken.strftime(\"%Y-%m-%d_%H%M%S\") + photo.suffix))\n"
     "```\n\n"
     "Try it on a copy of the folder first. It uses each file's modified time; "
     "say the word if you'd rather read the EXIF date."),
    ("user", "Make me a poster for the neighborhood book swap"),
    ("assistant", "Here's a first draft of the poster:\n\n"
     "- **Saturday, 10am to 1pm**\n"
     "- Corner of Elm & 3rd, by the little free library\n"
     "- Bring a book, take a book\n\n"
     "I can also post it to [the community board](https://example.com/book-swap) "
     "once you're happy with it.", {"images": [{
         "path": "sandbox://workspace/posters/book-swap.png", "mime": "image/png",
         "byte_len": len(POSTER), "label": "Book swap poster"}]}),
    ("push", "Heads up: the stone-fruit stall just posted that they close at 11 today, "
     "an hour earlier than usual."),
]

SIDE_CHATS = [
    {"id": "demo-lisbon", "title": "Trip to Lisbon", "pinned": True, "unread": 0, "ago": 2 * HOUR,
     "messages": [
         ("user", "Plan three relaxed days in Lisbon for early October"),
         ("assistant", "## Lisbon, three slow days\n\n"
          "**Day 1: Alfama.** Wander up to the Miradouro de Santa Luzia, lunch on grilled "
          "sardines, sunset at the castle.\n\n"
          "**Day 2: Belém.** Pastéis de nata at the source, the monastery, then the riverside "
          "bike path.\n\n"
          "**Day 3: Sintra.** Early train, Pena Palace before the crowds, back for dinner in "
          "Príncipe Real.\n\n"
          "October is ideal: warm days, cool evenings, far fewer queues."),
         ("user", "Where should we stay?"),
         ("assistant", "Stay in **Chiado**: central, flat by Lisbon standards, and a short "
          "walk to both Alfama and the river. I shortlisted three guesthouses in your "
          "price range; want the links?"),
     ]},
    {"id": "demo-sourdough", "title": "Sourdough lab", "pinned": False, "unread": 2, "ago": 25 * MINUTE,
     "messages": [
         ("user", "My loaf came out dense again"),
         ("assistant", "Dense crumb usually means under-proofing. Three things to try:\n\n"
          "- Let the bulk ferment run until the dough grows about **50%**\n"
          "- Keep it somewhere warm, 24 to 26°C\n"
          "- Do the poke test: the dent should spring back *slowly*"),
         ("push", "Your starter peaked about an hour ago. Now is a good time to mix tomorrow's dough."),
     ]},
    {"id": "demo-q4", "title": "Q4 launch plan", "pinned": False, "unread": 0, "ago": DAY + 3 * HOUR,
     "messages": [
         ("user", "Summarize where the Q4 launch stands"),
         ("assistant", "### Q4 launch, status\n\n"
          "| Track | Status |\n|---|---|\n| Landing page | done |\n"
          "| Pricing | in review |\n| Launch email | drafting |\n\n"
          "The only open risk is pricing sign-off, due **Wednesday**."),
     ]},
    {"id": "demo-run", "title": "Half marathon training", "pinned": False, "unread": 0, "ago": 3 * DAY,
     "messages": [
         ("user", "How far should I run this week?"),
         ("assistant", "Week 6 of 12: **32 km** total. Two easy 6 km runs, one 5 km tempo, "
          "and a 15 km long run on Sunday."),
     ]},
    {"id": "demo-books", "title": "Reading list", "pinned": False, "unread": 0, "ago": 6 * DAY,
     "messages": [
         ("user", "Something like Project Hail Mary, but shorter?"),
         ("assistant", "Try *The Martian* (same author, same humor) or *All Systems Red*, "
          "a 150-page novella about a security robot who just wants to watch TV."),
     ]},
]

REPLIES = [
    (r"lisbon|trip|travel|flight|vacation|holiday", "## A quick getaway plan\n\n"
     "Here's what I'd suggest:\n\n"
     "1. **Book the Friday 7:05 flight**, it's the cheapest this month\n"
     "2. **Stay two nights in the old town** so everything is walkable\n"
     "3. **Keep Sunday morning free** for the market and a long brunch\n\n"
     "I found a guesthouse with a rooftop terrace and great reviews. "
     "Want me to hold a room? It's free to cancel until Wednesday."),
    (r"code|script|python|function|bug|program", "Sure, here's a small, readable version:\n\n"
     "```python\nimport json\nfrom pathlib import Path\n\n\n"
     "def load_settings(path=\"settings.json\"):\n"
     "    file = Path(path)\n"
     "    if not file.exists():\n"
     "        return {}\n"
     "    return json.loads(file.read_text())\n```\n\n"
     "It returns an empty dict when the file is missing, so callers never have to "
     "check first. Want a test for it too?"),
    (r"recipe|cook|dinner|lunch|bread|sourdough|eat", "### Tonight: lemony one-pan orzo\n\n"
     "- 1 cup **orzo**, toasted in olive oil\n"
     "- 2 cups stock, a handful of spinach, one lemon\n"
     "- Parmesan and black pepper to finish\n\n"
     "Twenty minutes, one pan, and it uses the spinach that's about to turn. "
     "I added the missing lemon to your shopping list."),
    (r"plan|schedule|week|today|tomorrow|calendar|busy", "## Your week, at a glance\n\n"
     "- **Monday:** deep-work morning, no meetings before 11\n"
     "- **Tuesday:** dentist at 9:00, then the pricing review\n"
     "- **Wednesday:** pricing sign-off is due\n"
     "- **Thursday:** ramen at Menya Kaze, 12:30\n"
     "- **Friday:** weekly review, then you're free\n\n"
     "Tuesday is the busiest day, so I kept Monday light on purpose."),
    (r"\b(hi|hello|hey|morning|evening)\b", "Hey! Good to hear from you. "
     "I'm all caught up on your inbox and calendar.\n\n"
     "Anything you'd like to tackle first? I can **plan your week**, "
     "**draft an email**, or **find a place for dinner**."),
]

DEFAULT_REPLY = ("Good question. Here's how I'd think about it:\n\n"
                 "- **Start small.** Pick the one part you can finish today.\n"
                 "- **Write it down.** I saved a note so we can pick this up later.\n"
                 "- **Check in Friday.** I'll remind you and we'll see what changed.\n\n"
                 "Want me to turn this into a task with a reminder?")


def pick_reply(text):
    for pattern, reply in REPLIES:
        if re.search(pattern, text, re.I):
            return reply
    return DEFAULT_REPLY


def chunks(text, rng):
    """Split text into the word groups a streaming reply grows by."""
    words = re.findall(r"\S+\s*|\s+", text)
    out, i = [], 0
    while i < len(words):
        n = rng.randint(1, 3)
        out.append("".join(words[i:i + n]))
        i += n
    return out


def not_found():
    return GatewayError(404, '{"ok":false,"error":{"code":"not_found","message":"session not found"}}')


class World:
    """The fake account: sessions, chat events, feed, goals and so on."""

    def __init__(self, clock=time.monotonic, speed=1.0, wall=time.time):
        self.clock = clock
        self.speed = speed
        self.wall = wall
        self.rng = random.Random(7)
        self.seq = 4100
        self.streams = []
        self.events = {}
        now = int(wall() * 1000)
        self.sessions = [{"session_id": MAIN, "title": "Main chat", "is_primary": True,
                          "is_thread": False, "pinned": False, "archived": False,
                          "created_at_ms": now - 90 * DAY, "updated_at_ms": now - 4 * MINUTE,
                          "unread_count": 0, "snippet": "", "status": "active"}]
        self.events[MAIN] = self._script(MAIN, MAIN_CHAT, now - 26 * HOUR, now - 4 * MINUTE)
        for c in SIDE_CHATS:
            end = now - c["ago"]
            self.sessions.append({"session_id": c["id"], "title": c["title"], "is_primary": False,
                                  "is_thread": True, "pinned": c["pinned"], "archived": False,
                                  "created_at_ms": end - 2 * DAY, "updated_at_ms": end,
                                  "unread_count": c["unread"], "snippet": "", "status": "active"})
            self.events[c["id"]] = self._script(c["id"], c["messages"], end - 40 * MINUTE, end)
        self.feed = self._feed(now)
        self.next_session = 1

    # -- events ------------------------------------------------------------
    def _event(self, sid, role, text, at_ms, status="completed", push=False, data=None):
        self.seq += 1
        mid = f"{role}-msg-demo-{self.seq}"
        payload = {"role": role, "display_text": text, "content": text, "message_id": mid,
                   "session_id": sid, "is_thread": sid != MAIN, "seq": self.seq,
                   "reply_to_message_id": mid if push else "",
                   "display_text_updated_at_ms": at_ms, "display_text_ready": True}
        if status:
            payload["status"] = status
        if data:
            payload["data"] = data
        return {"event_name": f"message.{role}", "seq": self.seq, "message_id": mid,
                "role": role, "occurred_at_ms": at_ms, "display_text_updated_at_ms": at_ms,
                "reply_to_message_id": payload["reply_to_message_id"], "resources": [],
                "display_text": text, "payload": payload}

    def _script(self, sid, messages, start, end):
        evs, step = [], (end - start) // max(1, len(messages) - 1)
        for i, m in enumerate(messages):
            role, text = m[0], m[1]
            push = role == "push"
            evs.append(self._event(sid, "assistant" if push else role, text, start + i * step,
                                   push=push, data=m[2] if len(m) > 2 else None))
        return evs

    def _session(self, sid):
        for s in self.sessions:
            if s["session_id"] == sid:
                return s
        return None

    def _touch(self, sid, text):
        s = self._session(sid)
        if s:
            s["updated_at_ms"] = int(self.wall() * 1000)
            s["snippet"] = text[:80]

    def advance(self):
        now = self.clock()
        for st in list(self.streams):
            if now < st["start"]:
                continue
            if st["event"] is None:
                st["event"] = self._event(st["sid"], "assistant", "", int(self.wall() * 1000),
                                          status=None)
                self.events[st["sid"]].append(st["event"])
            n = sum(1 for t in st["times"] if t <= now)
            text = "".join(st["chunks"][:n])
            ev, p = st["event"], st["event"]["payload"]
            if text != p["display_text"]:
                ev["display_text"] = p["display_text"] = p["content"] = text
                ev["display_text_updated_at_ms"] = p["display_text_updated_at_ms"] = int(self.wall() * 1000)
            if n == len(st["chunks"]):
                p["status"] = "completed"
                self._touch(st["sid"], text)
                self.streams.remove(st)

    def send(self, sid, text):
        now = self.clock()
        ev = self._event(sid, "user", text, int(self.wall() * 1000))
        self.events[sid].append(ev)
        self._touch(sid, text)
        start = now + 1.2 / self.speed
        if self.streams:
            start = max(start, self.streams[-1]["times"][-1] + 0.3 / self.speed)
        parts = chunks(pick_reply(text), self.rng)
        times, t = [], start
        for _ in parts:
            times.append(t)
            t += self.rng.uniform(0.06, 0.09) / self.speed
        self.streams.append({"sid": sid, "start": start, "chunks": parts, "times": times,
                             "event": None})

    # -- feed and the rest ---------------------------------------------------
    def _feed(self, now):
        today = time.strftime("%Y-%m-%d", time.localtime(now / 1000))
        yday = time.strftime("%Y-%m-%d", time.localtime(now / 1000 - 86400))
        items = [
            (today, "morning", "Weather", "Sunny and 21°C, perfect for the market",
             "Clear skies all day with a light breeze off the river. Sunset is at 19:42."),
            (today, "morning", "Calendar", "Three things today, one needs prep",
             "The Q4 launch review at 15:00 is the one to prepare for: skim the pricing slide."),
            (today, "morning", "Running", "Week 6 long run: 15 km on Sunday",
             "You're ahead of plan. Keep the pace easy, around 6:10 per km."),
            (today, "morning", "Reading", "A new novella from an author you love",
             "Martha Wells has a new Murderbot story out this week. It's 160 pages."),
            (yday, "evening", "Kitchen", "Your starter is thriving",
             "It doubled in five hours, the fastest yet. Warmer kitchen, happier yeast."),
            (yday, "evening", "Travel", "Lisbon flights dropped 18%",
             "The Friday morning departure is now the cheapest in two months."),
            (yday, "evening", "Neighborhood", "The book swap is on for Saturday",
             "Twelve neighbors signed up so far. The poster draft is in your main chat."),
            (yday, "morning", "Money", "You're under budget on dining out",
             "€64 left for the month, enough for the ramen lunch and one more dinner."),
        ]
        days = {}
        for i, (date, kind, kicker, title, body) in enumerate(items):
            day = days.setdefault(date, {"local_date": date, "editions": {}})
            ed = day["editions"].setdefault(kind, {"kind": kind, "title": kind.title(), "units": []})
            ed["units"].append({"unit_id": f"demo-unit-{i + 1}", "kicker": kicker, "title": title,
                                "body_md": body, "edition_kind": kind, "position": len(ed["units"]),
                                "reaction": "love" if i == 1 else None})
        return {"days": [{"local_date": d["local_date"], "editions": list(d["editions"].values())}
                         for d in days.values()]}

    def call(self, method, path_params, body):
        fn = getattr(self, "api_" + re.sub(r"[.-]", "_", method), None)
        if fn is None:
            raise GatewayError(404, f'{{"error":"demo has no {method}"}}')
        return fn(path_params or {}, body or {})

    def api_identity(self, pp, b):
        return {"name": "Muse", "tagline": "Your personal agent", "vibe": "warm, curious, organized"}

    def api_sessions_list(self, pp, b):
        return {"sessions": copy.deepcopy(self.sessions)}

    def api_chat_unread_count(self, pp, b):
        return {"unread_count": sum(s["unread_count"] for s in self.sessions),
                "thread_id": MAIN, "seen_at_ms": int(self.wall() * 1000) - HOUR}

    def api_chat_history(self, pp, b):
        self.advance()
        sid = b.get("session_id") or MAIN
        s = self._session(sid)
        if s is None:
            raise not_found()
        s["unread_count"] = 0
        evs = self.events[sid]
        if b.get("before_seq"):
            evs = [e for e in evs if e["seq"] < b["before_seq"]]
        limit = b.get("limit") or 20
        return {"chat_events": copy.deepcopy(evs[-limit:]), "has_more": len(evs) > limit}

    def api_session_start(self, pp, b):
        sid = f"demo-new-{self.next_session}"
        self.next_session += 1
        now = int(self.wall() * 1000)
        self.sessions.append({"session_id": sid, "title": "", "is_primary": False,
                              "is_thread": True, "pinned": False, "archived": False,
                              "created_at_ms": now, "updated_at_ms": now, "unread_count": 0,
                              "snippet": "", "status": "active"})
        self.events[sid] = []
        return {"session_id": sid}

    def _op(self, b, **change):
        s = self._session(b.get("session_id"))
        if s is None or s.get("is_primary"):
            raise not_found()
        s.update(change)
        return {"ok": True, "session_id": s["session_id"]}

    def api_session_rename(self, pp, b):
        return self._op(b, title=b.get("title") or "")

    def api_session_pin(self, pp, b):
        return self._op(b, pinned=True)

    def api_session_unpin(self, pp, b):
        return self._op(b, pinned=False)

    def api_session_archive(self, pp, b):
        return self._op(b, archived=True)

    def api_session_unarchive(self, pp, b):
        return self._op(b, archived=False)

    def api_session_delete(self, pp, b):
        res = self._op(b)
        self.sessions = [s for s in self.sessions if s["session_id"] != b["session_id"]]
        return res

    def api_feed_list(self, pp, b):
        return copy.deepcopy(self.feed)

    def api_feed_unit_reaction(self, pp, b):
        for day in self.feed["days"]:
            for ed in day["editions"]:
                for u in ed["units"]:
                    if u["unit_id"] == pp.get("unit_id"):
                        u["reaction"] = b.get("reaction")
                        return {"unit_id": u["unit_id"], "reaction": u["reaction"]}
        raise GatewayError(404, '{"error":"unit not found"}')

    GOALS = [
        {"goal_id": "demo-goal-1", "title": "Run a half marathon", "status": "active",
         "summary": "Week 6 of 12, ahead of plan", "emoji": "🏃", "momentum": "rising"},
        {"goal_id": "demo-goal-2", "title": "Read 24 books this year", "status": "active",
         "summary": "17 read, 2 ahead of pace", "emoji": "📚", "momentum": "steady"},
        {"goal_id": "demo-goal-3", "title": "Learn conversational Portuguese", "status": "paused",
         "summary": "Paused until after the Q4 launch", "emoji": "🗣", "momentum": "paused"},
        {"goal_id": "demo-goal-4", "title": "Bake a perfect sourdough loaf", "status": "completed",
         "summary": "Nailed it on loaf #9", "emoji": "🍞", "momentum": "done"},
    ]

    def api_goals_list(self, pp, b):
        return {"goals": copy.deepcopy(self.GOALS)}

    def api_goals_get(self, pp, b):
        for g in self.GOALS:
            if g["goal_id"] == pp.get("id"):
                return {**g, "description": f"{g['title']}. {g['summary']}.",
                        "milestones": ["Set the target", "Build the habit", "Finish strong"]}
        raise GatewayError(404, '{"error":"goal not found"}')

    IDEAS = [
        ("For you today", "demo-idea-1", "Plan a picnic for Sunday",
         "Pick a park, check the weather, and pack a list that fits in one bag."),
        ("For you today", "demo-idea-2", "Clear your inbox in 15 minutes",
         "I sort it into reply, read later and archive; you just approve."),
        ("For you today", "demo-idea-3", "Prep for the launch review",
         "A one-page brief with the three questions you'll most likely get."),
        ("Projects", "demo-idea-4", "Turn your recipes into a cookbook",
         "Collect the recipes you've saved and lay them out as a printable PDF."),
        ("Projects", "demo-idea-5", "Build a running dashboard",
         "Weekly distance, pace trends and how close you are to race day."),
        ("Projects", "demo-idea-6", "Make a Lisbon photo book",
         "Pick the best 40 shots after the trip and arrange them by day."),
    ]

    def api_api_idea_cards_list(self, pp, b):
        sections = {}
        for section, iid, title, summary in self.IDEAS:
            s = sections.setdefault(section, {"id": section.lower().replace(" ", "-"),
                                              "title": section, "cards": []})
            s["cards"].append({"id": iid, "ideaCardId": iid, "title": title, "summary": summary,
                               "actionLabel": "Do it"})
        return {"sections": list(sections.values())}

    def _idea(self, iid):
        for section, i, title, summary in self.IDEAS:
            if i == iid:
                return {"id": i, "title": title, "summary": summary, "section": section}
        raise GatewayError(404, '{"error":"idea not found"}')

    def api_api_idea_cards_detail(self, pp, b):
        return self._idea(pp.get("ideaCardId"))

    def api_api_idea_cards_execute(self, pp, b):
        idea = self._idea(pp.get("ideaCardId"))
        # Like the real server, the run lands in the main chat.
        self.send(MAIN, f"Let's do this: {idea['title']}")
        return {"ok": True, "ideaCardId": idea["id"], "session_id": MAIN}

    def _at(self, hour, minute, days=0, weekday=None, after=True):
        """Epoch seconds of the next (or last) local hour:minute, so times match schedules."""
        now = datetime.datetime.fromtimestamp(self.wall())
        t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        step = datetime.timedelta(days=1 if weekday is None else 7)
        if weekday is not None:
            t += datetime.timedelta(days=(weekday - t.weekday()) % 7)
        if after and t <= now:
            t += step
        while not after and t > now:
            t -= step
        return int((t + datetime.timedelta(days=days)).timestamp())

    def api_tasks_list(self, pp, b):
        return {"schedules": [
            {"id": "demo-task-1", "title": "Morning briefing", "mode": "recurring", "enabled": True,
             "schedule_key": "daily 07:30", "next_run_at_utc": self._at(7, 30)},
            {"id": "demo-task-2", "title": "Water the plants", "mode": "recurring", "enabled": True,
             "schedule_key": "weekly sun 10:00", "next_run_at_utc": self._at(10, 0, weekday=6)},
            {"id": "demo-task-3", "title": "Remind me to book the Lisbon flights", "mode": "once",
             "enabled": False, "schedule_key": "once", "next_run_at_utc": self._at(18, 0, days=2)},
        ], "invalid": []}

    def api_tasks_runs(self, pp, b):
        brief = self._at(7, 30, after=False)
        runs = [
            {"run_id": "demo-run-4", "job_id": "demo-task-1", "status": "succeeded",
             "trigger_reason": "schedule", "scheduled_for_utc": brief,
             "result_summary": "Sent your briefing: 3 events, sunny, 2 emails worth reading."},
            {"run_id": "demo-run-3", "job_id": "demo-task-2", "status": "succeeded",
             "trigger_reason": "schedule", "scheduled_for_utc": self._at(10, 0, weekday=6, after=False),
             "result_summary": "Reminded you to water the plants."},
            {"run_id": "demo-run-2", "job_id": "demo-task-1", "status": "succeeded",
             "trigger_reason": "schedule", "scheduled_for_utc": brief - 86400,
             "result_summary": "Sent your briefing: a quiet day ahead."},
            {"run_id": "demo-run-1", "job_id": "demo-task-1", "status": "failed",
             "trigger_reason": "schedule", "scheduled_for_utc": brief - 2 * 86400,
             "error_text": "Calendar was briefly unavailable; retried at 07:35."},
        ]
        if b.get("job_id"):
            runs = [r for r in runs if r["job_id"] == b["job_id"]]
        return {"runs": runs[:b.get("limit") or 10]}

    def api_email_mailbox_get(self, pp, b):
        return {"address": "muse@demo.example", "display_name": "Muse", "enabled": True}

    EMAIL = [
        ("demo-thread-1", "Your Lisbon guesthouse shortlist", "Casa Chiado", "stay@casachiado.example",
         "Thanks for your interest! We have a terrace room free on 3 to 5 October.", 3),
        ("demo-thread-2", "Book swap: 12 neighbors signed up", "Elm Street Community", "hello@elmstreet.example",
         "Great news, the book swap is on. Could your agent print ten posters?", 2),
        ("demo-thread-3", "Your ramen reservation", "Menya Kaze", "book@menyakaze.example",
         "See you Thursday at 12:30. Table for two, confirmation MK-4821.", 1),
    ]

    def api_email_threads_list(self, pp, b):
        now = int(self.wall())
        return {"data": [
            {"id": tid, "subject": subject, "message_count": count,
             "participants": [addr, "muse@demo.example"],
             "last_message": {"header_from": addr, "created_at": now - (i + 1) * 5400,
                              "preview": preview}}
            for i, (tid, subject, name, addr, preview, count) in enumerate(self.EMAIL)],
            "paging": {"cursors": {"after": None}}}

    def api_email_threads_get(self, pp, b):
        now = int(self.wall())
        for i, (tid, subject, name, addr, preview, count) in enumerate(self.EMAIL):
            if tid == pp.get("thread_id"):
                msgs = [{"id": f"{tid}-m{n}", "thread_id": tid,
                         "direction": "inbound" if n % 2 == 0 else "outbound",
                         "header_from": addr if n % 2 == 0 else "muse@demo.example",
                         "header_from_name": name if n % 2 == 0 else "Muse",
                         "header_to": "muse@demo.example" if n % 2 == 0 else addr,
                         "subject": subject if n == 0 else "Re: " + subject,
                         "created_at": now - (count - n) * 3600 - i * 5400,
                         "text_body": preview if n == count - 1 else
                         ("Hello! Following up on this." if n % 2 == 0 else
                          "Thanks, that works. I'll confirm with my person and get back to you."),
                         "sender_authentication": {"verdict": "pass"}, "attachments": []}
                        for n in range(count)]
                return {"messages": msgs}
        raise GatewayError(404, '{"error":"thread not found"}')


class DemoGateway:
    vm_id = "demo-vm"

    def __init__(self, world):
        self.world = world

    def call_json(self, method, path_params=None, body=None, query=None, timeout=30):
        return self.world.call(method, path_params, body if body is not None else query)

    def _open(self, method, path_params=None, body=None, query=None, route=None):
        if method != "chat.stream":
            raise GatewayError(404, f'{{"error":"demo has no stream {method}"}}')
        sid = (body or {}).get("session_id") or MAIN
        if self.world._session(sid) is None:
            raise not_found()
        text = " ".join(i.get("text", "") for i in (body or {}).get("items", []))
        self.world.send(sid, text)
        return 1

    def download_file(self, ref, timeout=300):
        return POSTER

    def close(self):
        pass


class DemoBackend(Backend):
    demo = True

    def __init__(self, emit, clock=time.monotonic, speed=None):
        if speed is None:
            try:
                speed = float(os.environ.get("MUSE_CLI_DEMO_SPEED") or 1)
            except ValueError:
                speed = 1.0
        speed = max(0.1, speed)
        # Poll fast so every word group of a streaming reply shows up.
        self.send_poll = 0.04 / speed
        self.idle_poll = 2 / speed
        self.quiet = 3 / speed
        self.wait = 60 / speed
        self.world = World(clock, speed)
        self._state = {"session_id": None, "title": "main chat"}
        # About as long as a real sign-in takes, so the demo starts like the real app.
        self.connect_delay = 1.2 / speed
        super().__init__(emit, clock=clock, connect=self._connect,
                         cfg={"node_id": "demo-node", "cookies_file": ""})

    def _connect(self, cfg):
        time.sleep(self.connect_delay)
        return DemoGateway(self.world)

    def load_state(self):
        return dict(self._state)

    def save_state(self, st):
        self._state = dict(st)

    def run_login(self):
        print("Reading muse.ai cookies from your browser...")
        print("saved 4 muse.ai cookies (demo mode, nothing was written)")
