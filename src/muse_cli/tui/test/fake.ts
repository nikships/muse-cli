// In-memory stand-in for `python -m muse_cli.bridge`, for tests and quick UI work
// (MUSE_CLI_TUI_FAKE=1). The Python bridge's --demo mode is the real demo.
import type { Transport } from "../src/bridge"
import type { Message, Session } from "../src/protocol"

export type FakeOptions = { authFails?: boolean; delayMs?: number; streamMs?: number }

const now = Date.now()
const min = 60_000

function msg(seq: number, role: "user" | "assistant", text: string, agoMin: number, extra: Partial<Message> = {}): Message {
  return { seq, id: `${role}-${seq}`, role, text, at_ms: now - agoMin * min, final: true, push: false, files: [], ...extra }
}

export function fakeData() {
  const sessions: Session[] = [
    { session_id: null, title: "main chat", is_thread: false, pinned: false, archived: false, updated_at_ms: now - 2 * min, unread: 0 },
    { session_id: "s-lisbon", title: "Trip to Lisbon", is_thread: true, pinned: true, archived: false, updated_at_ms: now - 50 * min, unread: 2 },
    { session_id: "s-bread", title: "Sourdough lab", is_thread: true, pinned: false, archived: false, updated_at_ms: now - 26 * 60 * min, unread: 0 },
  ]
  const messages: Record<string, Message[]> = {
    main: [
      msg(10, "user", "Morning! What's on today?", 30),
      msg(11, "assistant", "Morning! Three things:\n\n- **10:00** design review\n- **13:30** dentist\n- Pick up the *sourdough starter* from Maya", 29),
      msg(12, "user", "Can you draft a quick note to Maya?", 3),
      msg(13, "assistant", "Sure, here's a draft:\n\n> Hi Maya! Still okay if I swing by around 5 for the starter? 🍞", 2, {
        files: [{ path: "sandbox://workspace/note.png", kind: "image", mime: "image/png", byte_len: 48213 }],
      }),
    ],
    "s-lisbon": [msg(20, "user", "Best day trip from Lisbon?", 70), msg(21, "assistant", "**Sintra**, easily. Go early to beat the crowds.", 69)],
    "s-bread": [],
  }
  return { sessions, messages }
}

export function createFakeTransport(opts: FakeOptions = {}): Transport & { sent: any[] } {
  const data = fakeData()
  let active: string | null = null
  let seq = 100
  const lineCbs: ((l: string) => void)[] = []
  const closeCbs: ((c: number | null) => void)[] = []
  const sent: any[] = []
  const delay = opts.delayMs ?? 5
  const emit = (obj: unknown) => setTimeout(() => lineCbs.forEach((cb) => cb(JSON.stringify(obj))), 0)
  const key = () => active ?? "main"
  let authed = !opts.authFails

  setTimeout(() => emit({ event: "ready", data: { version: "0.0.0-test", demo: true } }), 0)

  function handle(method: string, params: any): any {
    switch (method) {
      case "connect":
        if (!authed) throw { kind: "auth", message: "no cookies at ~/.config/muse-cli/cookies.txt" }
        return { vm_id: "vm-test", chat: { session_id: null, title: "main chat" }, identity: { name: "Test" } }
      case "login":
        authed = true
        return { ok: true, log: "saved 4 muse.ai cookies" }
      case "sessions":
        return { sessions: data.sessions }
      case "open": {
        active = params.session_id ?? null
        const s = data.sessions.find((x) => (x.session_id ?? null) === active)
        if (!s && active) throw { kind: "not_found", message: "session not found", status: 404 }
        return { chat: { session_id: active, title: s?.title ?? "main chat" }, messages: data.messages[key()] ?? [] }
      }
      case "history": {
        const list = data.messages[key()] ?? []
        return { messages: list.filter((m) => params.before_seq == null || m.seq < params.before_seq) }
      }
      case "send": {
        const sid = active
        const user = { ...msg(++seq, "user", params.text, 0), at_ms: Date.now() }
        ;(data.messages[key()] ??= []).push(user)
        const reply = `You said **${params.text}**. Here's a list:\n\n- one\n- two`
        const id = `assistant-${++seq}`
        const replySeq = seq
        setTimeout(() => {
          emit({ event: "message", data: { session_id: sid, message: user } })
          emit({ event: "thinking", data: { session_id: sid, since_ms: Date.now() } })
        }, delay)
        const words = reply.split(/(?<= )/)
        let acc = ""
        const step = opts.streamMs ?? 20
        words.forEach((w, i) => {
          setTimeout(() => {
            acc += w
            emit({ event: "draft", data: { session_id: sid, message: { ...msg(replySeq, "assistant", acc, 0), id, final: false, at_ms: Date.now() } } })
          }, delay * 2 + step * (i + 1))
        })
        setTimeout(() => {
          const final = { ...msg(replySeq, "assistant", reply, 0), id, at_ms: Date.now() }
          ;(data.messages[key()] ??= []).push(final)
          emit({ event: "message", data: { session_id: sid, message: final } })
          emit({ event: "idle", data: { session_id: sid, replied: true } })
        }, delay * 3 + step * (words.length + 1))
        return { sent: true, baseline: replySeq - 2 }
      }
      case "new_chat": {
        const s: Session = { session_id: `s-${++seq}`, title: params.title || "New chat", is_thread: true, pinned: false, archived: false, updated_at_ms: Date.now(), unread: 0 }
        data.sessions.splice(1, 0, s)
        data.messages[s.session_id!] = []
        return { chat: { session_id: s.session_id, title: s.title } }
      }
      case "session_op": {
        const s = data.sessions.find((x) => x.session_id === params.session_id)
        if (!s) throw { kind: "not_found", message: "session not found", status: 404 }
        if (params.op === "rename") s.title = params.title
        if (params.op === "pin") s.pinned = true
        if (params.op === "unpin") s.pinned = false
        if (params.op === "delete" || params.op === "archive") data.sessions.splice(data.sessions.indexOf(s), 1)
        return { ok: true }
      }
      case "feed":
        return { units: [{ id: "u1", title: "Your morning edition", date: "2026-11-08", edition: "morning", summary: "Rain after 3pm. Bring the good umbrella." }] }
      case "feed_react":
        return { ok: true }
      case "goals":
        return { goals: [{ id: "g1", title: "Run a half marathon", status: "in_progress", subtitle: "12 of 16 weeks done" }] }
      case "goal":
        return { title: "Run a half marathon", description: "Training plan", milestones: [{ title: "10k", status: "done" }] }
      case "ideas":
        return { ideas: [{ id: "i1", title: "Plan a picnic", section: "This weekend", summary: "Sunny Saturday" }] }
      case "idea":
        return { title: "Plan a picnic", body: "Find a park and pack food." }
      case "idea_exec":
        return { ok: true }
      case "tasks":
        return { tasks: [{ id: "t1", title: "Water the plants", enabled: true, schedule: "every 3 days", next_run: "2026-11-09 09:00" }] }
      case "task_runs":
        return { runs: [{ run_id: "r1", job_id: "t1", status: "completed", scheduled: "2026-11-06 09:00", summary: "Reminded you" }] }
      case "email":
        return { mailbox: { address: "muse@example.com" }, threads: [{ id: "th1", subject: "Your flight to Lisbon", messages: 2, last_from: "TAP", last_date: "2026-11-07 18:20", preview: "Check-in opens tomorrow" }] }
      case "email_thread":
        return { messages: [{ id: "em1", from: "TAP <no-reply@flytap.example>", subject: "Your flight to Lisbon", date: "2026-11-07 18:20", text: "Check-in opens tomorrow." }] }
      case "files":
        return { files: (data.messages[key()] ?? []).flatMap((m) => m.files.map((f) => ({ ...f, seq: m.seq, message_id: m.id }))) }
      case "download":
        return { rows: [{ path: params.path, file: `/tmp/${params.path.split("/").pop()}`, bytes: 10 }] }
      case "status":
        return { vm_id: "vm-test", sessions: data.sessions.length, unread: { total: 2 }, identity: {} }
      case "ping":
        return { pong: true }
      case "shutdown":
        return {}
    }
    throw { kind: "bad_request", message: `unknown method ${method}` }
  }

  return {
    sent,
    send(line) {
      const req = JSON.parse(line)
      sent.push(req)
      setTimeout(() => {
        try {
          emit({ id: req.id, result: handle(req.method, req.params ?? {}) })
        } catch (e: any) {
          emit({ id: req.id, error: { kind: e.kind ?? "internal", message: e.message ?? String(e), status: e.status } })
        }
      }, delay)
    },
    onLine(cb) {
      lineCbs.push(cb)
    },
    onClose(cb) {
      closeCbs.push(cb)
    },
    close() {
      closeCbs.forEach((cb) => cb(0))
    },
  }
}
