import { TextAttributes, type InputRenderable } from "@opentui/core"
import { useKeyboard, useTerminalDimensions } from "@opentui/react"
import { useMemo, useRef, useState } from "react"
import type { Controller } from "../controller"
import { useApp, useS, useSyntaxStyle, useTick } from "../context"
import { fuzzyScore, truncate } from "../format"
import { VIEWS, type State } from "../store"
import { gradientAt, theme } from "../theme"
import { GradientText, Kbd, spinner } from "./common"

type Cmd = { id: string; group: string; label: string; hint?: string; run: () => void }

export function paletteCommands(ctl: Controller, s: State): Cmd[] {
  const cmds: Cmd[] = []
  VIEWS.forEach((v, i) => cmds.push({ id: `go-${v.id}`, group: "Go to", label: `${v.icon}  ${v.label}`, hint: `Alt+${i + 1}`, run: () => ctl.go(v.id) }))
  const sid = s.chat.session_id
  cmds.push(
    { id: "new", group: "Actions", label: "New chat", hint: "Ctrl+N", run: () => ctl.setOverlay({ kind: "prompt", title: "New chat", placeholder: "What's it about?", initial: "", action: "new_chat" }) },
    { id: "main", group: "Actions", label: "Back to main chat", run: () => ctl.openChat({ session_id: null, title: "main chat" }) },
  )
  if (sid) {
    const cur = s.sessions.data?.find((x) => x.session_id === sid)
    cmds.push(
      { id: "rename", group: "Actions", label: "Rename this chat", run: () => ctl.setOverlay({ kind: "prompt", title: "Rename chat", placeholder: "New title", initial: s.chat.title, action: "rename" }) },
      { id: "pin", group: "Actions", label: cur?.pinned ? "Unpin this chat" : "Pin this chat", run: () => ctl.sessionOp(cur?.pinned ? "unpin" : "pin", sid) },
      {
        id: "archive",
        group: "Actions",
        label: "Archive this chat",
        run: () => ctl.setOverlay({ kind: "confirm", title: "Archive this chat?", body: `“${s.chat.title}” moves out of your list. You can restore it on muse.ai.`, confirm: "Archive", run: () => ctl.sessionOp("archive", sid) }),
      },
      {
        id: "delete",
        group: "Actions",
        label: "Delete this chat",
        run: () => ctl.setOverlay({ kind: "confirm", title: "Delete this chat?", body: `“${s.chat.title}” and its messages are deleted for good.`, confirm: "Delete", danger: true, run: () => ctl.sessionOp("delete", sid) }),
      },
    )
  }
  cmds.push(
    { id: "older", group: "Actions", label: "Load older messages", run: () => (ctl.go("chat"), ctl.loadOlder()) },
    { id: "sidebar", group: "Actions", label: s.sidebarOpen ? "Hide the chat list" : "Show the chat list", hint: "Ctrl+B", run: () => ctl.store.set({ sidebarOpen: !s.sidebarOpen }) },
    { id: "refresh", group: "Actions", label: "Refresh chats", run: () => ctl.refreshSessions() },
    { id: "login", group: "Actions", label: "Sign in again from the browser", run: () => ctl.login() },
    { id: "help", group: "Actions", label: "Keys and commands", hint: "F1", run: () => ctl.setOverlay({ kind: "help" }) },
    { id: "quit", group: "Actions", label: "Quit", hint: "Ctrl+Q", run: () => ctl.onQuit() },
  )
  for (const x of s.sessions.data ?? []) {
    const main = !x.session_id
    cmds.push({
      id: `chat-${x.session_id ?? "main"}`,
      group: "Chats",
      label: `${main ? "◆" : x.pinned ? "★" : "#"}  ${main ? "Main chat" : x.title || "untitled"}`,
      hint: x.unread ? `${x.unread} new` : undefined,
      run: () => ctl.openChat({ session_id: x.session_id, title: x.title }),
    })
  }
  return cmds
}

function Modal(props: { width: number; title?: string; children: any; borderColor?: string; top?: number }) {
  const dims = useTerminalDimensions()
  const w = Math.min(props.width, dims.width - 4)
  return (
    <box position="absolute" left={0} top={0} width="100%" height="100%" backgroundColor="#000000AA" alignItems="center" zIndex={50}>
      <box height={props.top ?? Math.max(1, Math.floor(dims.height * 0.12))} />
      <box
        width={w}
        border
        borderStyle="rounded"
        borderColor={props.borderColor ?? theme.metaBlue}
        backgroundColor={theme.card}
        flexDirection="column"
        title={props.title ? ` ${props.title} ` : undefined}
        titleAlignment="left"
        paddingX={1}
      >
        {props.children}
      </box>
    </box>
  )
}

export function Palette(props: { query: string }) {
  const { ctl } = useApp()
  const s = useS((x) => x)
  const [q, setQ] = useState(props.query)
  const [idx, setIdx] = useState(0)
  const dims = useTerminalDimensions()
  const all = useMemo(() => paletteCommands(ctl, s), [ctl, s.sessions, s.chat, s.sidebarOpen])
  const list = useMemo(() => {
    if (!q.trim()) return all
    return all
      .map((c) => ({ c, score: fuzzyScore(q, c.label.replace(/^\S+\s+/, "") + " " + c.group) }))
      .filter((x) => x.score >= 0)
      .sort((a, b) => b.score - a.score)
      .map((x) => x.c)
  }, [q, all])
  const max = Math.max(4, Math.min(14, dims.height - 12))
  const sel = Math.min(idx, Math.max(0, list.length - 1))
  const start = Math.max(0, Math.min(sel - Math.floor(max / 2), list.length - max))
  const view = list.slice(start, start + max)

  useKeyboard((key) => {
    if (key.name === "up" || (key.ctrl && key.name === "p")) {
      setIdx((i) => Math.max(0, Math.min(i, list.length - 1) - 1))
      key.preventDefault()
    } else if (key.name === "down" || (key.ctrl && key.name === "n")) {
      setIdx((i) => Math.min(list.length - 1, i + 1))
      key.preventDefault()
    } else if (key.name === "return") {
      const c = list[sel]
      key.preventDefault()
      ctl.setOverlay(null)
      c?.run()
    }
  })

  let lastGroup = ""
  return (
    <Modal width={72} title="Go anywhere">
      <box flexDirection="row" height={1} marginTop={1}>
        <text fg={theme.metaBlue}>{"❯ "}</text>
        <input
          focused
          value={props.query}
          placeholder="Search chats, spaces and actions"
          placeholderColor={theme.textFaint}
          textColor="#FFFFFF"
          focusedTextColor="#FFFFFF"
          backgroundColor={theme.card}
          focusedBackgroundColor={theme.card}
          cursorColor={theme.metaBlue}
          onInput={(v) => {
            setQ(v)
            setIdx(0)
          }}
          flexGrow={1}
        />
      </box>
      <box height={1} />
      {view.map((c, i) => {
        const on = start + i === sel
        const header = !q.trim() && c.group !== lastGroup
        lastGroup = c.group
        return (
          <box key={c.id} flexDirection="column">
            {header ? (
              <text fg={theme.textMuted} attributes={TextAttributes.BOLD}>
                {c.group.toUpperCase()}
              </text>
            ) : null}
            <box
              flexDirection="row"
              height={1}
              backgroundColor={on ? theme.selection : undefined}
              onMouseDown={() => {
                ctl.setOverlay(null)
                c.run()
              }}
            >
              <text fg={on ? theme.metaBlue : theme.card}>{"▎"}</text>
              <text fg={on ? "#FFFFFF" : theme.text}>{truncate(c.label, 52)}</text>
              <box flexGrow={1} />
              <text fg={on ? theme.textSoft : theme.textFaint}>{c.hint ?? (q.trim() ? c.group : "")}</text>
              <text>{" "}</text>
            </box>
          </box>
        )
      })}
      {!list.length ? <text fg={theme.textMuted}>Nothing matches. Try another word.</text> : null}
      <box flexDirection="row" gap={2} marginTop={1}>
        <Kbd k="↑↓" label="move" dim />
        <Kbd k="↵" label="go" dim />
        <Kbd k="esc" label="close" dim />
      </box>
    </Modal>
  )
}

export function Prompt(props: { title: string; placeholder: string; initial: string; action: "new_chat" | "rename" }) {
  const { ctl } = useApp()
  const chat = useS((s) => s.chat)
  const ref = useRef<InputRenderable>(null)
  const submit = (v: string) => {
    ctl.setOverlay(null)
    if (props.action === "new_chat") ctl.newChat(v.trim())
    else if (props.action === "rename" && chat.session_id && v.trim()) ctl.sessionOp("rename", chat.session_id, v.trim())
  }
  return (
    <Modal width={60} title={props.title}>
      <box height={1} />
      <box border borderStyle="rounded" borderColor={theme.metaBlue} backgroundColor={theme.raised} paddingX={1} height={3}>
        <input
          ref={ref}
          focused
          value={props.initial}
          placeholder={props.placeholder}
          placeholderColor={theme.textMuted}
          textColor="#FFFFFF"
          focusedTextColor="#FFFFFF"
          backgroundColor={theme.raised}
          focusedBackgroundColor={theme.raised}
          cursorColor={theme.metaBlue}
          onSubmit={(v) => submit(String(v ?? ref.current?.value ?? ""))}
        />
      </box>
      <box flexDirection="row" gap={2} marginBottom={0}>
        <Kbd k="↵" label={props.action === "new_chat" ? "start chat" : "save"} dim />
        <Kbd k="esc" label="cancel" dim />
        {props.action === "new_chat" ? <text fg={theme.textFaint}>a title is optional</text> : null}
      </box>
    </Modal>
  )
}

export function Confirm(props: { title: string; body: string; confirm: string; danger?: boolean; run: () => void }) {
  const { ctl } = useApp()
  useKeyboard((key) => {
    if (key.name === "return" || key.name === "y") {
      key.preventDefault()
      ctl.setOverlay(null)
      props.run()
    } else if (key.name === "n") {
      ctl.setOverlay(null)
    }
  })
  const color = props.danger ? theme.red : theme.metaBlue
  return (
    <Modal width={58} title={props.title} borderColor={color} top={Math.max(2, 8)}>
      <box height={1} />
      <text fg={theme.text} wrapMode="word">
        {props.body}
      </text>
      <box height={1} />
      <box flexDirection="row" gap={2}>
        <box onMouseDown={() => (ctl.setOverlay(null), props.run())}>
          <text>
            <span fg="#FFFFFF" bg={color}>{` ↵ ${props.confirm} `}</span>
          </text>
        </box>
        <box onMouseDown={() => ctl.setOverlay(null)}>
          <text>
            <span fg={theme.text} bg={theme.raised}>{" esc Cancel "}</span>
          </text>
        </box>
      </box>
    </Modal>
  )
}

function detailHeight(body: string, w: number, max: number, loading: boolean): number {
  if (loading) return 3
  const est = (body || " ").split("\n").reduce((n, l) => n + Math.max(1, Math.ceil(l.length / Math.max(10, w))), 0) + 2
  return Math.max(3, Math.min(max, est))
}

export function Detail(props: { title: string; subtitle?: string; body: string; loading?: boolean }) {
  const style = useSyntaxStyle()
  const dims = useTerminalDimensions()
  const tick = useTick(80, !!props.loading)
  return (
    <Modal width={92} title={truncate(props.title, 70)} top={2}>
      {props.subtitle ? <text fg={theme.textMuted}>{props.subtitle}</text> : null}
      <box height={1} />
      <scrollbox height={detailHeight(props.body, Math.min(92, dims.width - 4) - 4, dims.height - 12, !!props.loading)} focused>
        {props.loading ? (
          <text fg={theme.textMuted}>{`${spinner(tick)} loading…`}</text>
        ) : (
          <markdown content={props.body || "_Nothing more to show._"} syntaxStyle={style} conceal fg={theme.text} />
        )}
      </scrollbox>
      <box flexDirection="row" gap={2} marginTop={1}>
        <Kbd k="↑↓" label="scroll" dim />
        <Kbd k="esc" label="close" dim />
      </box>
    </Modal>
  )
}

const HELP: [string, [string, string][]][] = [
  [
    "Everywhere",
    [
      ["Ctrl+K", "go anywhere: chats, spaces, actions"],
      ["Alt+1…7", "Chat, Feed, Goals, Ideas, Tasks, Mail, Files"],
      ["Tab", "switch between the chat list and the main pane"],
      ["Ctrl+N", "new side chat"],
      ["Ctrl+B", "show or hide the chat list"],
      ["F1", "this help"],
      ["Ctrl+C", "clear the message box, or quit when it's empty"],
    ],
  ],
  [
    "Chat",
    [
      ["↵", "send"],
      ["Shift+↵  Ctrl+J", "new line"],
      ["/", "commands: /new /rename /feed /login …"],
      ["↑ in an empty box", "bring back what you sent"],
      ["PgUp PgDn", "scroll; PgUp at the top loads older messages"],
      ["click a file", "download it to ~/Downloads/muse"],
    ],
  ],
  [
    "Chat list",
    [
      ["↑↓ ↵", "move, open"],
      ["n  r  p", "new, rename, pin or unpin"],
      ["a  Del", "archive, delete"],
    ],
  ],
]

export function Help() {
  const version = useS((s) => s.version)
  return (
    <Modal width={70} title="Keys" top={2}>
      <box height={1} />
      {HELP.map(([group, rows], gi) => (
        <box key={group} flexDirection="column" marginBottom={1}>
          <text fg={gradientAt(gi / 3)} attributes={TextAttributes.BOLD}>
            {group.toUpperCase()}
          </text>
          {rows.map(([k, d]) => (
            <box key={k} flexDirection="row" height={1}>
              <text fg={theme.link}>{k.padEnd(20)}</text>
              <text fg={theme.textSoft}>{d}</text>
            </box>
          ))}
        </box>
      ))}
      <box flexDirection="row">
        <GradientText text="◆ muse-cli" />
        <text fg={theme.textFaint}>{` ${version} · plain mode: muse-cli chat`}</text>
      </box>
    </Modal>
  )
}

export function Toasts() {
  const toasts = useS((s) => s.toasts)
  if (!toasts.length) return null
  return (
    <box position="absolute" right={2} bottom={2} flexDirection="column" alignItems="flex-end" zIndex={60} gap={0}>
      {toasts.map((t) => {
        const color = t.level === "error" ? theme.red : t.level === "success" ? theme.green : theme.metaBlue
        const icon = t.level === "error" ? "✕" : t.level === "success" ? "✓" : "◆"
        return (
          <box key={t.id} border={["left"]} borderColor={color} backgroundColor={theme.raised} paddingX={1} maxWidth={60}>
            <text wrapMode="word">
              <span fg={color}>{`${icon} `}</span>
              <span fg={theme.text}>{t.text}</span>
            </text>
          </box>
        )
      })}
    </box>
  )
}
