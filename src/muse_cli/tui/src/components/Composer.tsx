import type { TextareaRenderable } from "@opentui/core"
import { useKeyboard, useTerminalDimensions } from "@opentui/react"
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react"
import { useApp, useS } from "../context"
import { fuzzyScore } from "../format"
import { theme } from "../theme"

export const SLASH = [
  { cmd: "/new", args: "[title]", desc: "Start a new side chat" },
  { cmd: "/main", args: "", desc: "Back to your main chat" },
  { cmd: "/chats", args: "", desc: "Browse your chats" },
  { cmd: "/rename", args: "[title]", desc: "Rename this chat" },
  { cmd: "/feed", args: "", desc: "Your daily feed" },
  { cmd: "/goals", args: "", desc: "Your goals" },
  { cmd: "/ideas", args: "", desc: "Idea cards" },
  { cmd: "/tasks", args: "", desc: "Scheduled tasks" },
  { cmd: "/mail", args: "", desc: "Muse Mail inbox" },
  { cmd: "/files", args: "", desc: "Files in this chat" },
  { cmd: "/history", args: "", desc: "Load older messages" },
  { cmd: "/login", args: "", desc: "Sign in again from your browser" },
  { cmd: "/help", args: "", desc: "Keys and commands" },
  { cmd: "/quit", args: "", desc: "Leave muse-cli" },
]

export function recallList(inChat: string[], sent: string[]): string[] {
  const out: string[] = []
  for (const s of [...inChat, ...sent]) {
    if (!s.trim()) continue
    const i = out.indexOf(s)
    if (i >= 0) out.splice(i, 1)
    out.push(s)
  }
  return out.slice(-100)
}

export type ComposerHandle = { clear(): boolean; insert(text: string): void; isEmpty(): boolean; menuOpen(): boolean }

const KEYS = [
  { name: "return", action: "submit" as const },
  { name: "kpenter", action: "submit" as const },
  { name: "return", shift: true, action: "newline" as const },
  { name: "return", meta: true, action: "newline" as const },
  { name: "j", ctrl: true, action: "newline" as const },
]

export const Composer = forwardRef<ComposerHandle, { focused: boolean }>(function Composer(props, ref) {
  const { ctl } = useApp()
  const chat = useS((s) => s.chat)
  const awaiting = useS((s) => s.awaiting)
  const messages = useS((s) => s.messages)
  const ta = useRef<TextareaRenderable>(null)
  const [text, setText] = useState("")
  const [lines, setLines] = useState(1)
  const [pick, setPick] = useState(0)
  const sent = useRef<string[]>([])
  const recall = useRef(-1)
  const { width } = useTerminalDimensions()

  const slashQuery = /^\/\S*$/.test(text) ? text : null
  const matches = useMemo(() => {
    if (slashQuery === null) return []
    const q = slashQuery.slice(1)
    return SLASH.map((c) => ({ c, s: q ? fuzzyScore(q, c.cmd.slice(1)) : 0 }))
      .filter((x) => x.s >= 0)
      .sort((a, b) => b.s - a.s)
      .map((x) => x.c)
  }, [slashQuery])
  const menuOpen = props.focused && matches.length > 0 && !(matches.length === 1 && matches[0]!.cmd === text)

  useImperativeHandle(ref, () => ({
    clear() {
      const t = ta.current
      if (!t || !t.plainText) return false
      t.setText("")
      sync()
      return true
    },
    insert(s: string) {
      ta.current?.insertText(s)
      sync()
    },
    isEmpty() {
      return !ta.current?.plainText
    },
    menuOpen() {
      return menuOpen
    },
  }))

  function sync() {
    const t = ta.current
    if (!t) return
    setText(t.plainText)
    // virtualLineCount stops at the visible height; the total counts wrapped lines too.
    setLines(Math.max(1, Math.min(8, t.editorView.getTotalVirtualLineCount() || t.lineCount || 1)))
    setPick(0)
  }

  // Rewrap after a resize (or the chat list opening), once the new width is laid out.
  useEffect(() => {
    const id = setTimeout(() => {
      const t = ta.current
      if (t) setLines(Math.max(1, Math.min(8, t.editorView.getTotalVirtualLineCount() || t.lineCount || 1)))
    }, 16)
    return () => clearTimeout(id)
  }, [width])

  function setValue(v: string) {
    const t = ta.current
    if (!t) return
    t.setText(v)
    t.gotoBufferEnd()
    sync()
    // Wrapped line counts are only right after the next layout pass.
    setTimeout(sync, 16)
  }

  function submit() {
    const t = ta.current
    if (!t) return
    let value = t.plainText
    if (menuOpen) {
      const c = matches[Math.min(pick, matches.length - 1)]!
      if (c.args) {
        setValue(c.cmd + " ")
        return
      }
      value = c.cmd
    }
    if (!value.trim()) return
    t.setText("")
    sync()
    sent.current = [...sent.current.slice(-99), value]
    recall.current = -1
    ctl.send(value)
  }

  useKeyboard((key) => {
    if (!props.focused) return
    if (menuOpen) {
      if (key.name === "up" || (key.ctrl && key.name === "p")) {
        setPick((p) => (p - 1 + matches.length) % matches.length)
        key.preventDefault()
      } else if (key.name === "down" || (key.ctrl && key.name === "n")) {
        setPick((p) => (p + 1) % matches.length)
        key.preventDefault()
      } else if (key.name === "tab") {
        const c = matches[Math.min(pick, matches.length - 1)]!
        setValue(c.cmd + (c.args ? " " : ""))
        key.preventDefault()
      }
      return
    }
    // Shell-style recall of what you sent, only from an empty or recalled box.
    // Your messages already in this chat count too, so a fresh start can recall them.
    const t = ta.current
    if (!t) return
    const hist = recallList(messages.filter((m) => m.role === "user").map((m) => m.text), sent.current)
    if (key.name === "up" && hist.length && (!t.plainText || recall.current >= 0) && t.logicalCursor.row === 0) {
      recall.current = recall.current < 0 ? hist.length - 1 : Math.max(0, recall.current - 1)
      setValue(hist[recall.current]!)
      key.preventDefault()
    } else if (key.name === "down" && recall.current >= 0 && t.logicalCursor.row === t.lineCount - 1) {
      recall.current += 1
      if (recall.current >= hist.length) {
        recall.current = -1
        setValue("")
      } else setValue(hist[recall.current]!)
      key.preventDefault()
    }
  })

  const border = props.focused ? theme.metaBlue : theme.divider
  const placeholder = chat.session_id ? `Message “${chat.title}”` : "Message your Muse"

  return (
    <box flexDirection="column" flexShrink={0}>
      {menuOpen ? (
        <box
          flexDirection="column"
          marginX={2}
          border
          borderStyle="rounded"
          borderColor={theme.divider}
          backgroundColor={theme.bg}
          paddingX={1}
        >
          {matches.slice(0, 8).map((c, i) => {
            const on = i === Math.min(pick, matches.length - 1)
            return (
              <box key={c.cmd} flexDirection="row" backgroundColor={on ? theme.selection : undefined} onMouseDown={() => setValue(c.cmd + (c.args ? " " : ""))}>
                <text selectable={false}>
                  <span fg={on ? "#FFFFFF" : theme.link}>{c.cmd}</span>
                  <span fg={theme.textFaint}>{c.args ? ` ${c.args}` : ""}</span>
                </text>
                <box flexGrow={1} />
                <text fg={on ? theme.text : theme.textMuted} selectable={false}>
                  {c.desc}
                </text>
              </box>
            )
          })}
        </box>
      ) : null}
      <box
        marginX={2}
        border
        borderStyle="rounded"
        borderColor={border}
        paddingX={1}
        height={lines + 2}
        bottomTitle={props.focused ? (awaiting ? " Muse is replying · you can keep typing " : " ↵ send · ⇧↵ newline · / commands ") : undefined}
        bottomTitleAlignment="right"
      >
        <textarea
          ref={ta}
          focused={props.focused}
          placeholder={placeholder}
          placeholderColor={theme.textFaint}
          textColor={theme.text}
          focusedTextColor="#FFFFFF"
          backgroundColor={theme.bg}
          focusedBackgroundColor={theme.bg}
          cursorColor={theme.metaBlue}
          selectionBg={theme.selection}
          wrapMode="word"
          keyBindings={KEYS}
          onSubmit={submit}
          onContentChange={sync}
          flexGrow={1}
        />
      </box>
    </box>
  )
})
