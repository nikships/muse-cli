import { TextAttributes } from "@opentui/core"
import { useApp, useS, useTick } from "../context"
import { truncate } from "../format"
import { VIEWS } from "../store"
import { theme } from "../theme"
import { GradientText } from "./common"

export function Header(props: { width: number }) {
  const { ctl } = useApp()
  const view = useS((s) => s.view)
  const chat = useS((s) => s.chat)
  const conn = useS((s) => s.connection)
  const unread = useS((s) => s.unread)
  const demo = useS((s) => s.demo)
  const busy = useS((s) => s.awaiting)
  const tick = useTick(90, busy)
  const compact = props.width < 100

  const connLabel = { online: "online", connecting: "connecting", offline: "offline", auth_needed: "sign in" }[conn]
  const connColor = { online: theme.green, connecting: theme.yellow, offline: theme.red, auth_needed: theme.yellow }[conn]

  return (
    <box height={1} width="100%" flexDirection="row" backgroundColor={theme.surface} paddingX={1} flexShrink={0}>
      <box flexDirection="row" flexShrink={0}>
        <GradientText text="◆ muse" bold phase={busy ? tick / 30 : 0} wave={busy} />
        <text fg={theme.textFaint}>{"  "}</text>
      </box>
      <box flexDirection="row" flexGrow={1} gap={0} overflow="hidden">
        {VIEWS.map((v) => {
          const on = v.id === view
          const label = compact ? v.icon : ` ${v.icon} ${v.label} `
          return (
            <box key={v.id} onMouseDown={() => ctl.go(v.id)} flexShrink={0}>
              <text selectable={false}>
                <span fg={on ? "#FFFFFF" : theme.textMuted} bg={on ? theme.metaBlue : undefined}>
                  {compact ? ` ${label} ` : label}
                </span>
                <span>{" "}</span>
              </text>
            </box>
          )
        })}
      </box>
      <box flexDirection="row" flexShrink={0} gap={1}>
        {view === "chat" && !compact ? (
          <text fg={theme.textSoft} attributes={TextAttributes.BOLD}>
            {truncate(chat.title, 28)}
          </text>
        ) : null}
        {demo ? <text fg={theme.yellow}>demo</text> : null}
        {unread > 0 ? (
          <text>
            <span fg="#FFFFFF" bg={theme.red}>{` ${unread > 99 ? "99+" : unread} `}</span>
          </text>
        ) : null}
        <text selectable={false}>
          <span fg={connColor}>●</span>
          <span fg={theme.textMuted}>{` ${connLabel}`}</span>
        </text>
      </box>
    </box>
  )
}
