import type { ScrollBoxRenderable } from "@opentui/core"
import { useKeyboard, useTerminalDimensions } from "@opentui/react"
import { useEffect, useRef } from "react"
import { useApp, useS } from "./context"
import { VIEWS, type View } from "./store"
import { theme } from "./theme"
import { Kbd } from "./components/common"
import { Composer, type ComposerHandle } from "./components/Composer"
import { Header } from "./components/Header"
import { Confirm, Detail, Help, Palette, Prompt, Toasts } from "./components/Overlays"
import { MAIL_SPLIT, Panel, panelItems, toMarkdown } from "./components/Panels"
import { SIDEBAR_WIDTH, Sidebar } from "./components/Sidebar"
import { Splash } from "./components/Splash"
import { Transcript } from "./components/Transcript"

function StatusBar(props: { width: number }) {
  const focus = useS((s) => s.focus)
  const view = useS((s) => s.view)
  const awaiting = useS((s) => s.awaiting)
  const narrow = props.width < 90
  return (
    <box height={1} flexDirection="row" backgroundColor={theme.surface} paddingX={1} flexShrink={0} gap={2}>
      <Kbd k="^K" label={narrow ? "" : "go anywhere"} dim />
      <Kbd k="Tab" label={narrow ? "" : focus === "sidebar" ? "back" : "chats"} dim />
      {view === "chat" && !narrow ? <Kbd k="/" label="commands" dim /> : null}
      {!narrow ? <Kbd k="^N" label="new chat" dim /> : null}
      <box flexGrow={1} />
      {awaiting ? <text fg={theme.textMuted}>{narrow ? "replying…" : "your Muse is replying…"}</text> : null}
      <Kbd k="F1" label={narrow ? "" : "help"} dim />
    </box>
  )
}

function Overlay() {
  const overlay = useS((s) => s.overlay)
  if (!overlay) return null
  switch (overlay.kind) {
    case "palette":
      return <Palette query={overlay.query} />
    case "help":
      return <Help />
    case "prompt":
      return <Prompt {...overlay} />
    case "confirm":
      return <Confirm {...overlay} />
    case "detail":
      return <Detail {...overlay} />
  }
}

export function App() {
  const { ctl, store } = useApp()
  const phase = useS((s) => s.phase)
  const view = useS((s) => s.view)
  const focus = useS((s) => s.focus)
  const overlay = useS((s) => s.overlay)
  const sidebarOpen = useS((s) => s.sidebarOpen)
  const dims = useTerminalDimensions()
  const transcript = useRef<ScrollBoxRenderable>(null)
  const composer = useRef<ComposerHandle>(null)
  const showSidebar = sidebarOpen && dims.width >= 70
  const mainWidth = dims.width - (showSidebar ? SIDEBAR_WIDTH : 0)

  useEffect(() => {
    if (!showSidebar && focus === "sidebar") store.set({ focus: view === "chat" ? "composer" : "list" })
  }, [showSidebar, focus, view])

  async function pageUp() {
    const sb = transcript.current
    if (!sb) return
    if (sb.scrollTop <= 0) {
      const before = sb.scrollHeight
      await ctl.loadOlder()
      sb.afterLayout(() => sb.scrollTo(Math.max(0, sb.scrollHeight - before)))
    } else sb.scrollBy(-Math.max(3, Math.floor(sb.viewport.height * 0.8)))
  }

  function panelAction(name: string): boolean {
    const s = store.get()
    const v = s.view as Exclude<View, "chat">
    const items = panelItems(s, v)
    const it = items[Math.min(s.selected[v], items.length - 1)]
    if (name === "r") {
      ctl.loadView(v, true)
      return true
    }
    if (!it) return false
    if (name === "return" || name === "space") {
      switch (it.kind) {
        case "feed":
          ctl.showDetail(it.v.title, [it.v.date, it.v.edition].filter(Boolean).join(" · "), async () => it.v.summary || "_No summary._")
          return true
        case "goal":
          ctl.showDetail(it.v.title, it.v.status, async () => toMarkdown(await ctl.bridge.request("goal", { id: it.v.id })) || it.v.subtitle || "")
          return true
        case "idea":
          ctl.showDetail(it.v.title, `${it.section}  ·  press x in the list to have your Muse do it`, async () => toMarkdown(await ctl.bridge.request("idea", { id: it.v.id })) || it.v.summary || "")
          return true
        case "task":
          ctl.showDetail(it.v.title, it.v.schedule, async () => toMarkdown(it.v))
          return true
        case "run":
          ctl.showDetail(`Run ${it.v.run_id}`, it.v.status, async () => toMarkdown(it.v))
          return true
        case "thread":
          if (mainWidth - 4 >= MAIL_SPLIT) ctl.openMailThread(it.v.id)
          else
            ctl.showDetail(it.v.subject || "(no subject)", it.v.last_from, async () => {
              const res = await ctl.bridge.request("email_thread", { id: it.v.id })
              return (res.messages ?? []).map((m) => `**${m.from ?? ""}** · ${m.date ?? ""}\n\n${m.text ?? ""}`).join("\n\n---\n\n")
            })
          return true
        case "file":
          ctl.download(it.v.path)
          return true
      }
    }
    if (it.kind === "feed" && (name === "l" || name === "h" || name === "d")) {
      ctl.react(it.v.id, name === "l" ? "like" : name === "h" ? "love" : "dislike")
      return true
    }
    if (it.kind === "idea" && name === "x") {
      ctl.setOverlay({
        kind: "confirm",
        title: "Ask your Muse to do this?",
        body: `“${it.v.title}” runs in your main chat. Your Muse will act on it right away.`,
        confirm: "Do it",
        run: () => ctl.runIdea(it.v.id, it.v.title),
      })
      return true
    }
    return false
  }

  function sidebarKey(name: string, shift: boolean): boolean {
    const s = store.get()
    const list = s.sessions.data ?? []
    const cur = list[s.sidebarIndex]
    const move = (d: number) => store.set({ sidebarIndex: Math.max(0, Math.min(list.length - 1, s.sidebarIndex + d)) })
    if (name === "up" || name === "k") return move(-1), true
    if (name === "down" || name === "j") return move(1), true
    if (name === "home") return store.set({ sidebarIndex: 0 }), true
    if (name === "end") return store.set({ sidebarIndex: list.length - 1 }), true
    if (name === "pageup") return move(-10), true
    if (name === "pagedown") return move(10), true
    if (name === "n") return ctl.setOverlay({ kind: "prompt", title: "New chat", placeholder: "What's it about?", initial: "", action: "new_chat" }), true
    if (!cur) return false
    if (name === "return" || name === "space" || name === "right" || name === "l") {
      ctl.openChat({ session_id: cur.session_id, title: cur.title })
      return true
    }
    const sid = cur.session_id
    if (!sid) {
      if (["r", "p", "a", "delete", "backspace"].includes(name)) ctl.toast("Your main chat stays put: it can't be renamed, pinned or removed.")
      return ["r", "p", "a", "delete", "backspace"].includes(name)
    }
    if (name === "r") {
      ctl.openChat({ session_id: sid, title: cur.title }).then(() =>
        ctl.setOverlay({ kind: "prompt", title: "Rename chat", placeholder: "New title", initial: cur.title, action: "rename" }),
      )
      return true
    }
    if (name === "p") return ctl.sessionOp(cur.pinned ? "unpin" : "pin", sid), true
    if (name === "a")
      return (
        ctl.setOverlay({ kind: "confirm", title: "Archive this chat?", body: `“${cur.title}” moves out of your list. You can restore it on muse.ai.`, confirm: "Archive", run: () => ctl.sessionOp("archive", sid) }),
        true
      )
    if (name === "delete" || (name === "backspace" && shift) || name === "x")
      return (
        ctl.setOverlay({ kind: "confirm", title: "Delete this chat?", body: `“${cur.title}” and its messages are deleted for good.`, confirm: "Delete", danger: true, run: () => ctl.sessionOp("delete", sid) }),
        true
      )
    return false
  }

  function listKey(name: string): boolean {
    const s = store.get()
    const v = s.view as Exclude<View, "chat">
    const n = panelItems(s, v).length
    // Data can shrink under a stored index (a refresh, a delete).
    const cur = Math.min(s.selected[v], Math.max(0, n - 1))
    const set = (i: number) => store.set({ selected: { ...s.selected, [v]: Math.max(0, Math.min(n - 1, i)) } })
    if (name === "up" || name === "k") return set(cur - 1), true
    if (name === "down" || name === "j") return set(cur + 1), true
    if (name === "home" || name === "g") return set(0), true
    if (name === "end") return set(n - 1), true
    if (name === "pageup") return set(cur - 5), true
    if (name === "pagedown") return set(cur + 5), true
    return panelAction(name)
  }

  useKeyboard((key) => {
    if (key.defaultPrevented || key.eventType === "release") return
    const s = store.get()
    const name = key.name
    const done = () => key.preventDefault()
    if (key.ctrl && name === "q") return done(), ctl.onQuit()
    if (s.phase !== "ready") {
      if (key.ctrl && name === "c") return done(), ctl.onQuit()
      return
    }
    if (key.ctrl && name === "c") {
      done()
      if (s.overlay) return ctl.setOverlay(null)
      if (composer.current?.clear()) return
      return ctl.onQuit()
    }
    if (s.overlay) {
      if (name === "escape") {
        done()
        ctl.setOverlay(null)
      } else if (s.overlay.kind === "help" && (name === "q" || name === "f1" || name === "?")) {
        done()
        ctl.setOverlay(null)
      }
      return
    }
    if (key.ctrl && (name === "k" || name === "p")) return done(), ctl.setOverlay({ kind: "palette", query: "" })
    if (key.ctrl && name === "n") return done(), ctl.setOverlay({ kind: "prompt", title: "New chat", placeholder: "What's it about?", initial: "", action: "new_chat" })
    if (key.ctrl && name === "b") return done(), store.set({ sidebarOpen: !s.sidebarOpen })
    if (name === "f1") return done(), ctl.setOverlay({ kind: "help" })
    const digit = /^[1-7]$/.test(name) ? Number(name) : 0
    if (digit && (key.meta || key.option || s.focus !== "composer")) return done(), ctl.go(VIEWS[digit - 1]!.id)
    // Tab completes a slash command; the composer handles that itself.
    if (name === "tab" && s.focus === "composer" && composer.current?.menuOpen()) return
    if (name === "tab" && !key.ctrl) {
      done()
      if (s.focus === "sidebar") return store.set({ focus: s.view === "chat" ? "composer" : "list" })
      if (showSidebar) return store.set({ focus: "sidebar" })
      return
    }
    if (s.focus === "sidebar") {
      if (name === "escape") return done(), store.set({ focus: s.view === "chat" ? "composer" : "list" })
      if (sidebarKey(name, key.shift)) return done()
      return
    }
    if (s.view === "chat") {
      if (name === "pageup") return done(), void pageUp()
      if (name === "pagedown") {
        done()
        const sb = transcript.current
        if (sb) sb.scrollBy(Math.max(3, Math.floor(sb.viewport.height * 0.8)))
        return
      }
      if (key.ctrl && name === "end") return done(), transcript.current?.scrollTo(Infinity)
      return
    }
    if (s.focus === "list") {
      if (name === "escape") {
        done()
        if (s.view === "mail" && s.mailThread.status !== "idle") return store.set({ mailThread: { status: "idle" } })
        return ctl.go("chat")
      }
      if (name === "?" || (key.shift && name === "/")) return done(), ctl.setOverlay({ kind: "help" })
      if (listKey(name)) return done()
    }
  })

  if (phase !== "ready") return <Splash />

  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor={theme.bg}>
      <Header width={dims.width} />
      <box flexDirection="row" flexGrow={1} minHeight={0}>
        {showSidebar ? <Sidebar /> : null}
        <box flexDirection="column" flexGrow={1} minWidth={0}>
          {view === "chat" ? (
            <>
              <Transcript ref={transcript} />
              <Composer ref={composer} focused={focus === "composer" && !overlay} />
              <box height={1} flexShrink={0} />
            </>
          ) : (
            <Panel view={view} width={mainWidth - 4} />
          )}
        </box>
      </box>
      <StatusBar width={dims.width} />
      <Toasts />
      <Overlay />
    </box>
  )
}
