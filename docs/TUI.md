# The full-screen app (`muse-cli tui`)

`muse-cli tui` (and bare `muse-cli` on an interactive terminal) opens a
full-screen app built on [OpenTUI](https://github.com/anomalyco/opentui).
`muse-cli chat` stays the plain, line-by-line chat for screen readers and
dumb terminals.

## Architecture

```
muse-cli tui  (Python launcher, muse_cli/tui.py)
   │  prepares the app in ~/.cache/muse-cli/tui/<hash>, then runs
   ▼
bun src/main.tsx  (OpenTUI + React, muse_cli/tui/)  ── owns the terminal
   │  spawns, talks JSON lines over pipes
   ▼
python -m muse_cli.bridge  (muse_cli/bridge.py)  ── owns the Gateway
```

- The TypeScript app owns the terminal. It never talks to muse.ai itself.
- The bridge is the only process with a `Gateway`. One worker thread makes
  every gateway call, so the WebSocket has exactly one consumer.
- The bridge keeps its protocol on the original stdout file descriptor and
  points `sys.stdout` and fd 1 at stderr, so a stray `print()` from a CLI
  helper can never corrupt the protocol. The app writes the bridge's stderr
  to `~/.config/muse-cli/tui.log`.

### Launcher

- Finds Bun (`bun` on PATH, else `~/.bun/bin/bun`). Bun 1.3.14 or later.
- Copies `muse_cli/tui` (without `node_modules`) to
  `~/.cache/muse-cli/tui/<hash>` where `<hash>` covers every shipped file,
  then runs `bun install --frozen-lockfile` there once. Later launches reuse
  it. `MUSE_CLI_TUI_DIR=<dir>` runs a checkout in place instead (development).
- Runs `bun <dir>/src/main.tsx` with the terminal inherited, and sets
  `MUSE_CLI_PYTHON=<sys.executable>` so the app can start the bridge with
  `[$MUSE_CLI_PYTHON, -m, muse_cli.bridge]` (plus `--demo` in demo mode).
- Exit code: the app's.
- Bare `muse-cli` opens the app when stdin and stdout are terminals, Bun is
  available and `MUSE_CLI_UI` is not `plain`; otherwise the plain chat.
  `muse-cli tui` without Bun offers to install it on a terminal and falls
  back to the plain chat when declined.
- `muse-cli tui --demo` (or `MUSE_CLI_DEMO=1`) runs the bridge with made-up
  data and never touches muse.ai. Screenshots and tests use it. Its fake
  gateway (`muse_cli/demo.py`) answers with the real server's shapes, and a
  reply streams in word by word. `MUSE_CLI_DEMO_SPEED=N` plays every demo
  delay N times faster; in demo mode `idle` comes 3 s after the last reply.

## Bridge protocol

Newline-delimited JSON, UTF-8, one object per line.

App to bridge (request):

```json
{"id": 7, "method": "history", "params": {"session_id": null, "limit": 40}}
```

Bridge to app (response, exactly one per request id):

```json
{"id": 7, "result": {...}}
{"id": 7, "error": {"kind": "gateway", "message": "...", "status": 404}}
```

Error `kind`: `auth` (no or expired login), `not_found` (deleted chat),
`gateway`, `timeout`, `bad_request` (unknown method or bad params),
`internal`. A gateway error whose body carries the server's reason uses its
`message`, and adds its `code` (for example `email_not_enabled`). The app
shows a code ending in `_not_enabled` as a feature the account lacks rather
than a failure to retry.

Bridge to app (event, no id):

```json
{"event": "message", "data": {...}}
```

### Shapes

`Chat`: `{"session_id": str|null, "title": str}`. `session_id: null` is the
main chat.

`Session`: `{"session_id", "title", "is_thread", "pinned", "archived",
"updated_at_ms", "unread"}`. The main chat has `session_id: null` here too,
so its `Session` opens with `open` as is.

`Message`:

```json
{"seq": 26693, "id": "assistant-msg-…", "role": "user"|"assistant",
 "text": "markdown text", "at_ms": 1794117896436,
 "final": true, "push": false,
 "files": [{"path": "sandbox://…", "kind": "image", "mime": "image/png",
            "label": "…", "byte_len": 1234}],
 "choices": [{"id": "widget-…", "options": ["Yes", "Not now"], "selected": null}],
 "card": null, "widget": false}
```

- `at_ms` is `occurred_at_ms` (fallback `display_text_updated_at_ms`).
- `final` is false while the assistant is still writing (no `status`).
- `push` is true for proactive assistant messages (non-empty
  `reply_to_message_id`, same rule as `cli.is_reply`).
- Only `message.user` and `message.assistant` events with text, files or
  choices become messages, plus `delta.presentation` events (below).
- A `delta.presentation` event is something the agent shows after its text:
  an image or file (`files`, empty `text`), or a link, connector, finished
  space, browser task or note (`card`: `{"id", "kind", "title", "subtitle",
  "url", "status"}`). These messages have `widget: true`; they never count as
  the reply, and the app draws them as part of the assistant message before
  them. A widget that changes (a browser task finishing) comes back with a new
  `seq` but the same `card.id`; only the latest is kept. Kinds with nothing
  to show (`voice_options`) are skipped.
- `choices` come from `payload.widgets` of kind `option` (quick replies);
  `selected` is `state.data.selectedText`. Their `[hatch_widget:…]` or
  `[[hatch_widget:…]]` placeholder is removed from `text`. The app sends a
  picked option as a normal message.
- A user's own uploads come from `payload.metadata.attachments` (a bare
  `workspace/…` path, given a `sandbox://` prefix), and their
  `[image:<mime> <path>]` placeholder is removed from `text`.

### Events

| event        | data | when |
| ------------ | ---- | ---- |
| `ready`      | `{"version", "demo"}` | first line, before any connection |
| `connection` | `{"state": "connecting"\|"online"\|"offline"\|"auth_needed", "detail"}` | connection state changes |
| `message`    | `{"session_id", "message": Message}` | a new final message in the active chat (user or assistant), ordered by seq |
| `draft`      | `{"session_id", "message": Message}` | the assistant's in-progress reply changed (`final: false`) |
| `thinking`   | `{"session_id", "since_ms"}` | after `send`, until the first reply |
| `idle`       | `{"session_id", "replied": bool}` | the agent went quiet after a send (10 s after the last reply, or 300 s with no reply) |
| `unread`     | unread-count payload | every 30 s while online |
| `log`        | `{"level", "text"}` | notices worth a toast |

The bridge tracks one active chat (`open`). It polls that chat's history:
every 1 s from `send` until `idle`, otherwise every 8 s, and emits
`message` for every final message newer than the last one it reported.
That covers proactive pushes too. A poll failure never kills the loop; three
failures in a row emit `connection` `offline` and the bridge reconnects with
backoff.

### Methods

| method | params | result |
| ------ | ------ | ------ |
| `connect` | `{}` | `{"vm_id", "chat": Chat, "identity"}`; uses `chat.json` for the last chat |
| `login` | `{}` | `{"ok": bool, "log": str}`; runs `auth export` with its output captured, reconnects on success |
| `sessions` | `{"archived": false}` | `{"sessions": [Session]}`; main chat first, then pinned, then by `updated_at_ms` desc. `archived: true` also lists archived chats |
| `open` | `{"session_id": str\|null, "title": str, "limit": 40}` | `{"chat": Chat, "messages": [Message]}`; sets the active chat and saves `chat.json`. `not_found` for a deleted chat |
| `history` | `{"limit": 40, "before_seq": int?}` | `{"messages": [Message]}` for the active chat |
| `send` | `{"text": str}` | `{"sent": true, "baseline": seq}`; then `thinking`, `draft`, `message`, `idle` events |
| `new_chat` | `{"title": str?}` | `{"chat": Chat}`; also makes it active |
| `session_op` | `{"op": "rename"\|"pin"\|"unpin"\|"archive"\|"unarchive"\|"delete", "session_id", "title"?}` | server result |
| `status` | `{}` | `{"vm_id", "sessions", "unread", "identity"}` |
| `feed` | `{"limit": 50}` | `{"units": [{"id", "title", "date", "edition", "summary", "reaction", "emoji", "kicker", "category", "source", "why"}]}` |
| `feed_react` | `{"unit", "reaction": "like"\|"love"\|"dislike"}` | server result |
| `goals` | `{}` | `{"goals": [{"id", "title", "status", "subtitle"}]}` |
| `goal` | `{"id"}` | server result |
| `ideas` | `{}` | `{"ideas": [{"id", "title", "section", "summary"}]}` |
| `idea` | `{"id"}` | server result |
| `idea_exec` | `{"id"}` | server result (runs in the active chat) |
| `tasks` | `{}` | `{"tasks": [...same rows as cmd_tasks]}` |
| `task_runs` | `{"job": str?, "limit": 10}` | `{"runs": [...same rows as cmd_task_runs]}` |
| `email` | `{}` | `{"mailbox", "threads": [...same rows as cmd_email]}` |
| `email_thread` | `{"id"}` | `{"messages": [...same rows as _email_message]}` |
| `files` | `{"limit": 200}` | `{"files": [{"seq", "message_id", "path", "kind", "mime", "label", "byte_len"}]}` for the active chat, newest first, uploads and presented files included |
| `download` | `{"path", "dir"?}` | `{"rows": [...save_resources rows]}`; default dir `~/Downloads/muse` |
| `ping` | `{}` | `{"pong": true}` |
| `shutdown` | `{}` | `{}`, then the bridge closes the gateway and exits 0 |

The bridge also exits when its stdin closes.
