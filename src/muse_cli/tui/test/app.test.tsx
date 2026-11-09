import { afterEach, describe, expect, test } from "bun:test"
import { testRender } from "@opentui/react/test-utils"
import { App } from "../src/app"
import { Bridge } from "../src/bridge"
import { AppContext } from "../src/context"
import { Controller } from "../src/controller"
import { Store } from "../src/store"
import { createFakeTransport } from "./fake"

let setup: Awaited<ReturnType<typeof testRender>> | null = null

afterEach(() => {
  setup?.renderer.destroy()
  setup = null
})

async function mount(width = 120, height = 36, opts = {}) {
  const store = new Store()
  const fake = createFakeTransport({ streamMs: 2, ...opts })
  const ctl = new Controller(new Bridge(fake), store)
  let quit = false
  ctl.onQuit = () => (quit = true)
  setup = await testRender(
    <AppContext.Provider value={{ ctl, store }}>
      <App />
    </AppContext.Provider>,
    { width, height, exitOnCtrlC: false },
  )
  // Store updates arrive from bridge callbacks, outside act(); real frames are what we assert on.
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = false
  await ctl.boot()
  // Markdown and bridge replies settle over several ticks, so poll real frames.
  const frame = async (pred: (f: string) => boolean, ms = 3000) => {
    const start = Date.now()
    let last = ""
    while (Date.now() - start < ms) {
      await setup!.renderOnce()
      last = setup!.captureCharFrame()
      if (pred(last)) return last
      await Bun.sleep(10)
    }
    throw new Error(`frame never matched:\n${last}`)
  }
  return { store, ctl, fake, setup: setup!, frame, quit: () => quit }
}

describe("App", () => {
  test("shows the chat list, transcript and composer", async () => {
    const { frame } = await mount()
    const f = await frame((x) => x.includes("Pick up the sourdough starter") && x.includes("Trip to Lisbon"))
    expect(f).toContain("CHATS")
    expect(f).toContain("Message your Muse")
    expect(f).toContain("online")
  })

  test("typing and Enter sends, and the reply renders", async () => {
    const { setup: s, frame, fake } = await mount()
    await frame((x) => x.includes("Message your Muse"))
    await s.mockInput.typeText("ping")
    s.mockInput.pressEnter()
    await frame((x) => x.includes("You said ping"))
    expect(fake.sent.find((r) => r.method === "send")?.params.text).toBe("ping")
  })

  test("Ctrl+K opens the palette and Esc closes it", async () => {
    const { setup: s, frame, store } = await mount()
    await frame((x) => x.includes("Message your Muse"))
    s.mockInput.pressKey("k", { ctrl: true })
    await frame((x) => x.includes("Go anywhere"))
    expect(store.get().overlay?.kind).toBe("palette")
    s.mockInput.pressEscape()
    await frame(() => store.get().overlay === null)
  })

  test("Tab moves into the chat list and Enter opens a chat", async () => {
    const { setup: s, frame, store } = await mount()
    await frame((x) => x.includes("Trip to Lisbon"))
    s.mockInput.pressTab()
    await s.renderOnce()
    expect(store.get().focus).toBe("sidebar")
    s.mockInput.pressArrow("down")
    s.mockInput.pressEnter()
    await frame((x) => x.includes("Sintra, easily"))
    expect(store.get().chat.session_id).toBe("s-lisbon")
  })

  test("the feed panel lists units and reacts with l", async () => {
    const { setup: s, frame, store, fake } = await mount()
    await frame((x) => x.includes("Message your Muse"))
    await s.mockInput.typeText("/feed")
    s.mockInput.pressEnter()
    await frame((x) => x.includes("Your morning edition"))
    await s.mockInput.typeText("l")
    await frame((x) => x.includes("liked"))
    expect(fake.sent.find((r) => r.method === "feed_react")?.params).toEqual({ unit: "u1", reaction: "like" })
    expect(store.get().view).toBe("feed")
  })

  test("renaming from the chat list stays in the list and keeps the open chat", async () => {
    const { setup: s, frame, store } = await mount()
    await frame((x) => x.includes("Trip to Lisbon"))
    s.mockInput.pressTab()
    await frame(() => store.get().focus === "sidebar")
    s.mockInput.pressArrow("down")
    s.mockInput.pressKey("r")
    await frame((x) => x.includes("Rename chat"))
    for (let i = 0; i < "Trip to Lisbon".length; i++) s.mockInput.pressBackspace()
    await s.mockInput.typeText("Porto instead")
    s.mockInput.pressEnter()
    await frame((x) => x.includes("Porto instead") && !x.includes("Rename chat"))
    expect(store.get().focus).toBe("sidebar")
    expect(store.get().chat.session_id).toBeNull()
  })

  test("a feature the account lacks shows a calm notice, not a retry", async () => {
    const { setup: s, frame } = await mount(120, 36, { mailOff: true })
    await frame((x) => x.includes("Message your Muse"))
    await s.mockInput.typeText("/mail")
    s.mockInput.pressEnter()
    const f = await frame((x) => x.includes("isn't turned on for this account"))
    expect(f).toContain("doesn't have its own inbox yet")
    expect(f).not.toContain("press r to retry")
    expect(f).not.toContain("Select a thread")
  })

  test("Tab completes a slash command and keeps focus in the message box", async () => {
    const { setup: s, frame, store } = await mount()
    await frame((x) => x.includes("Message your Muse"))
    await s.mockInput.typeText("/ren")
    await frame((x) => x.includes("Rename this chat"))
    s.mockInput.pressTab()
    await s.renderOnce()
    expect(store.get().focus).toBe("composer")
    await s.mockInput.typeText("pr")
    const f = await frame((x) => x.includes("/rename pr"))
    expect(f).not.toContain("Rename chat")
    expect(store.get().focus).toBe("composer")
  })

  test("a narrow terminal hides the chat list", async () => {
    const { frame } = await mount(60, 24)
    const f = await frame((x) => x.includes("Message your Muse"))
    expect(f).not.toContain("CHATS")
  })

  test("an 80-column terminal hides the chat list until Tab peeks at it", async () => {
    const { setup: s, frame, store } = await mount(80, 24)
    await frame((x) => x.includes("Message your Muse"))
    expect(s.captureCharFrame()).not.toContain("CHATS")
    s.mockInput.pressTab()
    await frame((x) => x.includes("CHATS"))
    expect(store.get().focus).toBe("sidebar")
    s.mockInput.pressTab()
    await frame((x) => !x.includes("CHATS"))
    s.mockInput.pressKey("b", { ctrl: true })
    await frame((x) => x.includes("CHATS"))
    expect(store.get().sidebarOpen).toBe(true)
  })

  test("the sign-in screen appears without a login", async () => {
    const { frame } = await mount(100, 30, { authFails: true })
    const f = await frame((x) => x.includes("signed in"))
    expect(f).toContain("sign in from browser")
  })

  test("Ctrl+C clears a draft first, then quits", async () => {
    const { setup: s, frame, quit } = await mount()
    await frame((x) => x.includes("Message your Muse"))
    await s.mockInput.typeText("half a thought")
    await frame((x) => x.includes("half a thought"))
    s.mockInput.pressCtrlC()
    await frame((x) => !x.includes("half a thought"))
    expect(quit()).toBe(false)
    s.mockInput.pressCtrlC()
    expect(quit()).toBe(true)
  })
})
