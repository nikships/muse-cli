import { TextAttributes, type ScrollBoxRenderable } from "@opentui/core"
import { useEffect, useRef } from "react"
import { useApp, useNow, useS, useTick } from "../context"
import { ago, truncate } from "../format"
import { gradientAt, theme } from "../theme"
import { spinner } from "./common"

export const SIDEBAR_WIDTH = 30

export function Sidebar() {
  const { ctl } = useApp()
  const sessions = useS((s) => s.sessions)
  const chat = useS((s) => s.chat)
  const focus = useS((s) => s.focus)
  const index = useS((s) => s.sidebarIndex)
  const now = useNow()
  const loading = sessions.status === "loading" && !sessions.data
  const tick = useTick(80, loading)
  const scroll = useRef<ScrollBoxRenderable>(null)
  const focused = focus === "sidebar"
  const list = sessions.data ?? []
  const inner = SIDEBAR_WIDTH - 2

  useEffect(() => {
    const sb = scroll.current
    if (sb && list[index]) sb.scrollChildIntoView(`side-${index}`)
  }, [index, list.length])

  return (
    <box
      width={SIDEBAR_WIDTH}
      flexShrink={0}
      flexDirection="column"
      backgroundColor={theme.surface}
      border={["right"]}
      borderColor={focused ? theme.metaBlue : theme.divider}
    >
      <box flexDirection="row" paddingX={1} height={1} flexShrink={0} marginTop={1}>
        <text fg={focused ? theme.link : theme.textMuted} attributes={TextAttributes.BOLD} selectable={false}>
          CHATS
        </text>
        <box flexGrow={1} />
        <box onMouseDown={() => ctl.setOverlay({ kind: "prompt", title: "New chat", placeholder: "What's it about?", initial: "", action: "new_chat" })}>
          <text fg={theme.link} selectable={false}>
            + new
          </text>
        </box>
      </box>
      <box height={1} flexShrink={0} />
      {loading ? (
        <text fg={theme.textMuted} paddingX={1}>
          {`${spinner(tick)} loading chats`}
        </text>
      ) : null}
      {sessions.status === "error" && !sessions.data ? (
        <text fg={theme.red} paddingX={1} wrapMode="word">
          {sessions.error ?? "Couldn't load chats"}
        </text>
      ) : null}
      <scrollbox ref={scroll} flexGrow={1} flexBasis={0} minHeight={0} scrollbarOptions={{ visible: false }}>
        {list.map((s, i) => {
          const active = (s.session_id ?? null) === (chat.session_id ?? null)
          const selected = focused && i === index
          const main = !s.is_thread && !s.session_id
          const icon = main ? "◆" : s.pinned ? "★" : "#"
          const iconColor = main ? gradientAt(0.15) : s.pinned ? theme.yellow : theme.textFaint
          const right = s.unread > 0 ? ` ${s.unread > 9 ? "9+" : s.unread} ` : ago(s.updated_at_ms, now)
          const titleW = inner - 4 - Math.max(3, right.length)
          const title = main ? "Main chat" : s.title || "untitled"
          return (
            <box
              key={s.session_id ?? "main"}
              id={`side-${i}`}
              flexDirection="row"
              height={1}
              backgroundColor={selected ? theme.raised : active ? theme.card : undefined}
              onMouseDown={() => {
                ctl.store.set({ sidebarIndex: i })
                ctl.openChat({ session_id: s.session_id, title: s.title })
              }}
            >
              <text selectable={false}>
                <span fg={active ? theme.metaBlue : theme.surface}>▎</span>
                <span fg={iconColor}>{icon}</span>
                <span>{" "}</span>
                <span fg={active || selected ? "#FFFFFF" : s.unread ? theme.text : theme.textSoft}>
                  {truncate(title, titleW).padEnd(titleW)}
                </span>
              </text>
              <box flexGrow={1} />
              <text selectable={false}>
                {s.unread > 0 ? <span fg="#FFFFFF" bg={theme.red}>{right}</span> : <span fg={theme.textFaint}>{right}</span>}
                <span>{" "}</span>
              </text>
            </box>
          )
        })}
      </scrollbox>
      <box flexShrink={0} paddingX={1} flexDirection="column">
        {focused ? (
          [
            [["↵", "open"], ["n", "new"], ["r", "rename"]],
            [["p", "pin"], ["a", "archive"], ["x", "del"]],
          ].map((row, i) => (
            <text key={i} selectable={false}>
              {row.map(([k, label], j) => (
                <span key={k}>
                  <span fg={theme.textSoft}>{`${j ? "  " : ""}${k} `}</span>
                  <span fg={theme.textFaint}>{label}</span>
                </span>
              ))}
            </text>
          ))
        ) : (
          <text fg={theme.textFaint} selectable={false}>
            Tab to browse chats
          </text>
        )}
      </box>
    </box>
  )
}
