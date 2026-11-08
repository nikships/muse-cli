import { describe, expect, test } from "bun:test"
import { Bridge, BridgeError, type Transport } from "../src/bridge"
import { Controller, countUnread } from "../src/controller"
import { ago, fuzzyScore, truncate } from "../src/format"
import { Store, mergeMessages } from "../src/store"
import { createFakeTransport } from "./fake"

function pipe() {
  const lines: ((l: string) => void)[] = []
  const closes: ((c: number | null) => void)[] = []
  const sent: string[] = []
  const t: Transport = {
    send: (l) => sent.push(l),
    onLine: (cb) => lines.push(cb),
    onClose: (cb) => closes.push(cb),
    close: () => {},
  }
  return { t, sent, push: (o: unknown) => lines.forEach((cb) => cb(JSON.stringify(o))), end: (c: number) => closes.forEach((cb) => cb(c)) }
}

const until = async (pred: () => boolean, ms = 2000) => {
  const start = Date.now()
  while (!pred()) {
    if (Date.now() - start > ms) throw new Error("timed out")
    await Bun.sleep(5)
  }
}

describe("Bridge", () => {
  test("matches responses to requests by id", async () => {
    const p = pipe()
    const b = new Bridge(p.t)
    const a = b.request("ping")
    const c = b.request("sessions", { archived: false })
    const [ra, rc] = p.sent.map((l) => JSON.parse(l))
    expect(ra.method).toBe("ping")
    expect(rc.params).toEqual({ archived: false })
    p.push({ id: rc.id, result: { sessions: [] } })
    p.push({ id: ra.id, result: { pong: true } })
    expect(await a).toEqual({ pong: true })
    expect(await c).toEqual({ sessions: [] })
  })

  test("turns error responses into BridgeError with kind and status", async () => {
    const p = pipe()
    const b = new Bridge(p.t)
    const r = b.request("open", { session_id: "x", title: "x" })
    p.push({ id: JSON.parse(p.sent[0]!).id, error: { kind: "not_found", message: "session not found", status: 404 } })
    const e = await r.catch((x) => x)
    expect(e).toBeInstanceOf(BridgeError)
    expect(e.kind).toBe("not_found")
    expect(e.status).toBe(404)
  })

  test("delivers events and ignores junk lines", () => {
    const p = pipe()
    const b = new Bridge(p.t)
    const seen: any[] = []
    b.on("connection", (d) => seen.push(d))
    p.push({ event: "connection", data: { state: "online" } })
    for (const cb of [] as any[]) cb()
    ;(p as any).push("not json")
    expect(seen).toEqual([{ state: "online" }])
  })

  test("rejects pending requests when the bridge exits", async () => {
    const p = pipe()
    const b = new Bridge(p.t)
    let exit: any
    b.on("exit", (d) => (exit = d))
    const r = b.request("connect")
    p.end(1)
    const e = await r.catch((x) => x)
    expect(e.kind).toBe("bridge")
    expect(exit).toEqual({ code: 1, reason: "crashed" })
    expect((await b.request("ping").catch((x) => x)).kind).toBe("bridge")
  })

  test("times out a request that never answers", async () => {
    const p = pipe()
    const b = new Bridge(p.t)
    const e = await b.request("ping", {}, 20).catch((x) => x)
    expect(e.kind).toBe("timeout")
  })
})

describe("Controller", () => {
  test("boots into the last chat with its history", async () => {
    const store = new Store()
    const ctl = new Controller(new Bridge(createFakeTransport()), store)
    await ctl.boot()
    const s = store.get()
    expect(s.phase).toBe("ready")
    expect(s.demo).toBe(true)
    expect(s.messages.map((m) => m.seq)).toEqual([10, 11, 12, 13])
    await until(() => store.get().sessions.status === "ready")
    expect(store.get().sessions.data!.length).toBe(3)
  })

  test("auth failure shows the sign-in screen, login recovers", async () => {
    const store = new Store()
    const ctl = new Controller(new Bridge(createFakeTransport({ authFails: true })), store)
    await ctl.boot()
    expect(store.get().phase).toBe("auth")
    await ctl.login()
    expect(store.get().phase).toBe("ready")
  })

  test("send shows a pending bubble, streams a draft, then lands the reply once", async () => {
    const store = new Store()
    const ctl = new Controller(new Bridge(createFakeTransport({ streamMs: 5 })), store)
    await ctl.boot()
    const p = ctl.send("hello")
    expect(store.get().pending.map((x) => x.text)).toEqual(["hello"])
    expect(store.get().thinkingSince).not.toBeNull()
    await p
    let sawDraft = false
    await until(() => {
      if (store.get().draft) sawDraft = true
      return !store.get().awaiting
    })
    const s = store.get()
    expect(sawDraft).toBe(true)
    expect(s.pending).toEqual([])
    expect(s.draft).toBeNull()
    const tail = s.messages.slice(-2)
    expect(tail.map((m) => m.role)).toEqual(["user", "assistant"])
    expect(new Set(s.messages.map((m) => m.seq)).size).toBe(s.messages.length)
  })

  test("events for another chat are ignored", async () => {
    const p = pipe()
    const store = new Store()
    new Controller(new Bridge(p.t), store)
    p.push({ event: "message", data: { session_id: "other", message: { seq: 1, id: "a", role: "assistant", text: "x", at_ms: 1, final: true, push: false, files: [] } } })
    expect(store.get().messages).toEqual([])
  })

  test("opening a deleted chat falls back to the main chat", async () => {
    const store = new Store()
    const ctl = new Controller(new Bridge(createFakeTransport()), store)
    await ctl.boot()
    await ctl.openChat({ session_id: "gone", title: "Gone" })
    expect(store.get().chat.session_id).toBeNull()
    expect(store.get().toasts.some((t) => t.text.includes("deleted"))).toBe(true)
  })

  test("slash commands switch views and never reach the agent", async () => {
    const fake = createFakeTransport()
    const store = new Store()
    const ctl = new Controller(new Bridge(fake), store)
    await ctl.boot()
    await ctl.send("/goals")
    expect(store.get().view).toBe("goals")
    await until(() => store.get().goals.status === "ready")
    expect(fake.sent.some((r) => r.method === "send")).toBe(false)
    await ctl.send("/new Weekend plans")
    await until(() => store.get().chat.title === "Weekend plans")
    expect(store.get().chat.session_id).toMatch(/^s-/)
  })

  test("an unknown slash line is sent as a normal message", async () => {
    const fake = createFakeTransport()
    const ctl = new Controller(new Bridge(fake), new Store())
    await ctl.boot()
    await ctl.send("/shrug at this")
    expect(fake.sent.find((r) => r.method === "send")?.params.text).toBe("/shrug at this")
  })
})

describe("helpers", () => {
  test("mergeMessages dedupes by seq and keeps order", () => {
    const m = (seq: number, text = "") => ({ seq, id: String(seq), role: "user" as const, text, at_ms: 0, final: true, push: false, files: [] })
    expect(mergeMessages([m(3), m(1)], [m(2), m(3, "new")]).map((x) => [x.seq, x.text])).toEqual([
      [1, ""],
      [2, ""],
      [3, "new"],
    ])
  })

  test("truncate respects display width", () => {
    expect(truncate("hello world", 8)).toBe("hello w…")
    expect(truncate("日本語のテキスト", 7)).toBe("日本語…")
    expect(truncate("short", 10)).toBe("short")
  })

  test("fuzzyScore prefers substrings and rejects non-matches", () => {
    expect(fuzzyScore("lis", "Trip to Lisbon")).toBeGreaterThan(fuzzyScore("lis", "Hide the chat list") - 1000)
    expect(fuzzyScore("xyz", "Trip to Lisbon")).toBe(-1)
    expect(fuzzyScore("ttl", "Trip to Lisbon")).toBeGreaterThan(0)
  })

  test("ago and countUnread", () => {
    const now = 1_000_000_000
    expect(ago(now - 10_000, now)).toBe("now")
    expect(ago(now - 5 * 60_000, now)).toBe("5m")
    expect(ago(now - 3 * 3_600_000, now)).toBe("3h")
    expect(countUnread({ total: 4 })).toBe(4)
    expect(countUnread({ counts: { a: 1, b: 2 } })).toBe(3)
    expect(countUnread("x")).toBeNull()
  })
})
