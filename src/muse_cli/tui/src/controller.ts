import { Bridge, BridgeError } from "./bridge"
import type { Chat, Message } from "./protocol"
import { Store, VIEWS, mergeMessages, type Overlay, type State, type Toast, type View } from "./store"

const HISTORY = 60

export class Controller {
  private toastId = 1
  private unsubs: (() => void)[] = []
  onQuit: () => void = () => {}

  constructor(
    public bridge: Bridge,
    public store: Store,
  ) {
    this.wire()
  }

  get s(): State {
    return this.store.get()
  }

  private wire() {
    const b = this.bridge
    this.unsubs.push(
      b.on("ready", (d) => this.store.set({ version: d.version, demo: d.demo })),
      b.on("connection", (d) => {
        const was = this.s.connection
        this.store.set({ connection: d.state, connectionDetail: d.detail ?? "" })
        if (this.s.phase !== "ready") return
        if (d.state === "offline" && was !== "offline") this.toast("Lost the connection. Reconnecting…", "error")
        if (d.state === "online" && was === "offline") this.toast("Back online", "success")
        if (d.state === "auth_needed") this.askLogin()
      }),
      b.on("message", (d) => {
        if (!this.isActive(d.session_id)) return
        this.receive(d.message)
      }),
      b.on("draft", (d) => {
        if (!this.isActive(d.session_id)) return
        this.store.set({ draft: d.message, thinkingSince: null })
      }),
      b.on("thinking", (d) => {
        if (!this.isActive(d.session_id)) return
        this.store.set({ thinkingSince: d.since_ms || Date.now(), awaiting: true })
      }),
      b.on("idle", (d) => {
        if (!this.isActive(d.session_id)) return
        const hadDraft = this.s.draft
        this.store.set({ awaiting: false, thinkingSince: null, draft: null })
        if (!d.replied && !hadDraft) this.toast("No reply yet. Your Muse may answer later; it will show up here.", "info")
      }),
      b.on("unread", (d: any) => {
        const n = countUnread(d)
        if (n !== null) this.store.set({ unread: n })
      }),
      b.on("log", (d) => this.toast(d.text, d.level === "error" ? "error" : "info")),
      b.on("exit", () => {
        this.store.set({ phase: "fatal", phaseDetail: "The muse-cli bridge stopped. See ~/.config/muse-cli/tui.log." })
      }),
    )
  }

  private isActive(sessionId: string | null | undefined) {
    return (sessionId ?? null) === (this.s.chat.session_id ?? null)
  }

  private receive(m: Message) {
    this.store.set((s) => {
      let pending = s.pending
      if (m.role === "user") {
        const i = pending.findIndex((p) => p.text.trim() === m.text.trim())
        if (i >= 0) pending = pending.filter((_, j) => j !== i)
      }
      const replyLanded = m.role === "assistant" && !m.push
      const draft = s.draft && (s.draft.seq === m.seq || s.draft.id === m.id || replyLanded) ? null : s.draft
      return {
        messages: mergeMessages(s.messages, [m]),
        pending,
        draft,
        thinkingSince: replyLanded ? null : s.thinkingSince,
        // The bridge keeps listening a little longer for follow-ups, but the reply is here.
        awaiting: replyLanded ? false : s.awaiting,
      }
    })
  }

  toast(text: string, level: Toast["level"] = "info") {
    const id = this.toastId++
    this.store.set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, level, at: Date.now() }] }))
    setTimeout(() => this.store.set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), level === "error" ? 6000 : 3500)
  }

  async boot() {
    this.store.set({ phase: "connecting", phaseDetail: "Signing in to muse.ai" })
    try {
      const res = await this.bridge.request("connect", {}, 90_000)
      this.store.set({ vmId: res.vm_id ?? "", identity: res.identity ?? null, phaseDetail: "Opening your chat" })
      await this.openChat(res.chat, { quiet: true })
      this.store.set({ phase: "ready", connection: "online" })
      this.refreshSessions()
    } catch (e) {
      if (e instanceof BridgeError && e.kind === "auth") {
        this.store.set({ phase: "auth", phaseDetail: e.message })
      } else {
        this.store.set({ phase: "fatal", phaseDetail: errText(e) })
      }
    }
  }

  async login() {
    if (this.s.loginBusy) return
    this.store.set({ loginBusy: true, phaseDetail: "Reading your muse.ai login from the browser…" })
    try {
      const res = await this.bridge.request("login", {}, 180_000)
      if (res.ok) {
        this.toast("Signed in", "success")
        this.store.set({ loginBusy: false, overlay: null })
        if (this.s.phase !== "ready") await this.boot()
      } else {
        const last = res.log.trim().split("\n").filter(Boolean).slice(0, 3).join(" ")
        this.store.set({ loginBusy: false, phaseDetail: last || "Could not read a muse.ai login." })
        this.toast("Sign-in failed. Log in at muse.ai in your browser, then try again.", "error")
      }
    } catch (e) {
      this.store.set({ loginBusy: false, phaseDetail: errText(e) })
    }
  }

  askLogin() {
    this.setOverlay({
      kind: "confirm",
      title: "Your muse.ai login expired",
      body: "Read a fresh login from your browser now? Log in at muse.ai first if you signed out there.",
      confirm: "Sign in",
      run: () => this.login(),
    })
  }

  async refreshSessions() {
    this.store.set((s) => ({ sessions: { ...s.sessions, status: s.sessions.data ? "ready" : "loading" } }))
    try {
      const res = await this.bridge.request("sessions", { archived: false })
      const idx = res.sessions.findIndex((x) => (x.session_id ?? null) === (this.s.chat.session_id ?? null))
      this.store.set((s) => ({
        sessions: { status: "ready", data: res.sessions, at: Date.now() },
        sidebarIndex: s.focus === "sidebar" ? s.sidebarIndex : Math.max(0, idx),
      }))
    } catch (e) {
      this.store.set((s) => ({ sessions: { ...s.sessions, status: "error", error: errText(e) } }))
    }
  }

  async openChat(chat: Chat, opts: { quiet?: boolean } = {}) {
    if (!chat.session_id) chat = { session_id: null, title: "main chat" }
    const same = (chat.session_id ?? null) === (this.s.chat.session_id ?? null) && this.s.messages.length > 0
    this.store.set({
      chat,
      historyLoading: !same,
      messages: same ? this.s.messages : [],
      draft: null,
      thinkingSince: null,
      awaiting: false,
      pending: [],
      files: { status: "idle" },
      view: "chat",
      focus: "composer",
    })
    try {
      const res = await this.bridge.request("open", { session_id: chat.session_id, title: chat.title, limit: HISTORY })
      if ((this.s.chat.session_id ?? null) !== (res.chat.session_id ?? null)) return
      this.store.set((s) => ({ chat: res.chat, messages: mergeMessages(s.messages, res.messages), historyLoading: false }))
      const idx = (this.s.sessions.data ?? []).findIndex((x) => (x.session_id ?? null) === (res.chat.session_id ?? null))
      if (idx >= 0) this.store.set({ sidebarIndex: idx })
      if (!opts.quiet) this.markSeen(res.chat.session_id)
    } catch (e) {
      this.store.set({ historyLoading: false })
      if (e instanceof BridgeError && e.kind === "not_found" && chat.session_id) {
        this.toast(`"${chat.title}" was deleted. Back to your main chat.`, "error")
        await this.openChat({ session_id: null, title: "main chat" })
        this.refreshSessions()
        return
      }
      if (opts.quiet) throw e
      this.toast(errText(e), "error")
    }
  }

  private markSeen(sessionId: string | null) {
    this.store.set((s) => ({
      sessions: s.sessions.data
        ? { ...s.sessions, data: s.sessions.data.map((x) => ((x.session_id ?? null) === (sessionId ?? null) ? { ...x, unread: 0 } : x)) }
        : s.sessions,
    }))
  }

  async loadOlder() {
    const first = this.s.messages[0]
    if (!first || this.s.historyLoading) return
    this.store.set({ historyLoading: true })
    try {
      const res = await this.bridge.request("history", { limit: HISTORY, before_seq: first.seq })
      this.store.set((s) => ({ messages: mergeMessages(s.messages, res.messages), historyLoading: false }))
      if (!res.messages.length) this.toast("That's the beginning of this chat.")
    } catch (e) {
      this.store.set({ historyLoading: false })
      this.toast(errText(e), "error")
    }
  }

  async send(raw: string) {
    const text = raw.replace(/\s+$/, "")
    if (!text.trim()) return
    if (text.startsWith("/") && this.runSlash(text)) return
    const key = `p${Date.now()}${Math.random()}`
    this.store.set((s) => ({
      pending: [...s.pending, { key, text, at_ms: Date.now() }],
      thinkingSince: Date.now(),
      awaiting: true,
    }))
    try {
      await this.bridge.request("send", { text })
    } catch (e) {
      this.store.set((s) => ({
        pending: s.pending.map((p) => (p.key === key ? { ...p, failed: true } : p)),
        thinkingSince: null,
        awaiting: false,
      }))
      if (e instanceof BridgeError && e.kind === "auth") this.askLogin()
      else if (e instanceof BridgeError && e.kind === "not_found") {
        this.toast("This chat was deleted. Back to your main chat.", "error")
        await this.openChat({ session_id: null, title: "main chat" })
      } else this.toast(`Not sent: ${errText(e)}`, "error")
    }
  }

  retry(key: string) {
    const p = this.s.pending.find((x) => x.key === key)
    if (!p) return
    this.store.set((s) => ({ pending: s.pending.filter((x) => x.key !== key) }))
    this.send(p.text)
  }

  // Slash commands typed in the composer. Returns true when handled.
  runSlash(line: string): boolean {
    const [cmd, ...rest] = line.slice(1).split(/\s+/)
    const arg = rest.join(" ").trim()
    const c = (cmd ?? "").toLowerCase()
    const view = VIEWS.find((v) => v.id === c || v.label.toLowerCase() === c || (c === "email" && v.id === "mail"))
    if (view) {
      this.go(view.id)
      return true
    }
    switch (c) {
      case "new":
        if (arg) this.newChat(arg)
        else this.setOverlay({ kind: "prompt", title: "New chat", placeholder: "What's it about?", initial: "", action: "new_chat" })
        return true
      case "main":
        this.openChat({ session_id: null, title: "main chat" })
        return true
      case "chats":
        this.store.set({ sidebarOpen: true, focus: "sidebar" })
        return true
      case "rename":
        if (!this.s.chat.session_id) {
          this.toast("The main chat can't be renamed.")
          return true
        }
        if (arg) this.sessionOp("rename", this.s.chat.session_id, arg)
        else this.setOverlay({ kind: "prompt", title: "Rename chat", placeholder: "New title", initial: this.s.chat.title, action: "rename" })
        return true
      case "login":
        this.login()
        return true
      case "help":
      case "?":
        this.setOverlay({ kind: "help" })
        return true
      case "quit":
      case "exit":
        this.onQuit()
        return true
      case "history":
        this.loadOlder()
        return true
    }
    return false
  }

  async newChat(title?: string) {
    try {
      const res = await this.bridge.request("new_chat", { title: title || undefined })
      this.toast(`Started "${res.chat.title}"`, "success")
      await this.openChat(res.chat)
      this.refreshSessions()
    } catch (e) {
      this.toast(errText(e), "error")
    }
  }

  async sessionOp(op: "rename" | "pin" | "unpin" | "archive" | "unarchive" | "delete", sessionId: string, title?: string) {
    try {
      await this.bridge.request("session_op", { op, session_id: sessionId, title })
      const verb = { rename: "Renamed", pin: "Pinned", unpin: "Unpinned", archive: "Archived", unarchive: "Restored", delete: "Deleted" }[op]
      this.toast(verb, "success")
      if ((op === "delete" || op === "archive") && sessionId === this.s.chat.session_id) {
        await this.openChat({ session_id: null, title: "main chat" })
      } else if (op === "rename" && sessionId === this.s.chat.session_id && title) {
        this.store.set((s) => ({ chat: { ...s.chat, title } }))
      }
      this.refreshSessions()
    } catch (e) {
      this.toast(errText(e), "error")
    }
  }

  setOverlay(overlay: Overlay) {
    this.store.set({ overlay })
  }

  go(view: View) {
    this.store.set({ view, focus: view === "chat" ? "composer" : "list", overlay: null })
    if (view !== "chat") this.loadView(view)
  }

  async loadView(view: View, force = false) {
    const key = view as Exclude<View, "chat">
    if (view === "chat") return
    const cur = this.s[key] as any
    if (!force && cur.status === "ready" && cur.at && Date.now() - cur.at < 60_000) return
    this.store.set({ [key]: { ...cur, status: "loading" } } as any)
    try {
      let data: any
      if (view === "feed") data = (await this.bridge.request("feed", { limit: 50 })).units
      else if (view === "goals") data = (await this.bridge.request("goals", {})).goals
      else if (view === "ideas") data = (await this.bridge.request("ideas", {})).ideas
      else if (view === "tasks") {
        const [t, r] = await Promise.all([this.bridge.request("tasks", {}), this.bridge.request("task_runs", { limit: 10 })])
        data = { tasks: t.tasks, runs: r.runs }
      } else if (view === "mail") {
        const m = await this.bridge.request("email", {})
        data = { mailbox: m.mailbox, threads: m.threads }
      } else if (view === "files") data = (await this.bridge.request("files", { limit: 80 })).files
      this.store.set({ [key]: { status: "ready", data, at: Date.now() } } as any)
    } catch (e) {
      const off = e instanceof BridgeError && !!e.code?.endsWith("_not_enabled")
      this.store.set({ [key]: { ...cur, status: "error", error: errText(e), off } } as any)
      if (e instanceof BridgeError && e.kind === "auth") this.askLogin()
    }
  }

  async showDetail(title: string, subtitle: string | undefined, load: () => Promise<string>) {
    this.setOverlay({ kind: "detail", title, subtitle, body: "", loading: true })
    // The overlay object itself is the ticket: a newer detail or a close replaces it.
    const mine = this.s.overlay
    try {
      const body = await load()
      if (this.s.overlay === mine) this.setOverlay({ kind: "detail", title, subtitle, body, loading: false })
    } catch (e) {
      if (this.s.overlay === mine) this.setOverlay({ kind: "detail", title, subtitle, body: `**Couldn't load this.** ${errText(e)}` })
    }
  }

  async react(unit: string, reaction: "like" | "love" | "dislike") {
    const prev = this.s.feed.data?.find((u) => u.id === unit)?.reaction ?? null
    const mark = (r: string | null) =>
      this.store.set((s) => ({
        feed: s.feed.data ? { ...s.feed, data: s.feed.data.map((u) => (u.id === unit ? { ...u, reaction: r } : u)) } : s.feed,
      }))
    mark(reaction)
    try {
      await this.bridge.request("feed_react", { unit, reaction })
      this.toast(reaction === "love" ? "Loved it ♥" : reaction === "like" ? "Liked" : "Got it, less like this", "success")
    } catch (e) {
      mark(prev)
      this.toast(errText(e), "error")
    }
  }

  async runIdea(id: string, title: string) {
    try {
      await this.bridge.request("idea_exec", { id })
      this.toast(`Your Muse is on it: ${title}`, "success")
      this.go("chat")
    } catch (e) {
      this.toast(errText(e), "error")
    }
  }

  async download(path: string) {
    this.toast("Downloading…")
    try {
      const res = await this.bridge.request("download", { path }, 300_000)
      const row = res.rows[0]
      if (!row) return
      if (row.error) this.toast(`Download failed: ${row.error}`, "error")
      else if (row.skipped) this.toast(`Already saved: ${row.file}`)
      else this.toast(`Saved ${row.file}`, "success")
    } catch (e) {
      this.toast(errText(e), "error")
    }
  }

  async openMailThread(id: string) {
    this.store.set({ mailThread: { status: "loading", id } })
    try {
      const res = await this.bridge.request("email_thread", { id })
      this.store.set({ mailThread: { status: "ready", id, data: res.messages, at: Date.now() } })
    } catch (e) {
      this.store.set({ mailThread: { status: "error", id, error: errText(e) } })
    }
  }

  dispose() {
    for (const u of this.unsubs) u()
  }
}

export function errText(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}

export function countUnread(d: any): number | null {
  if (typeof d === "number") return d
  if (!d || typeof d !== "object") return null
  for (const k of ["total", "unread", "count", "unread_count"]) if (typeof d[k] === "number") return d[k]
  if (typeof d.counts === "object" && d.counts) {
    return Object.values(d.counts).reduce((a: number, v) => a + (typeof v === "number" ? v : 0), 0)
  }
  return null
}
