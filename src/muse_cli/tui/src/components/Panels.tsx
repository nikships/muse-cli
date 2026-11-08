import { TextAttributes, type ScrollBoxRenderable } from "@opentui/core"
import { useEffect, useMemo, useRef, type ReactNode } from "react"
import { useApp, useS, useSyntaxStyle, useTick } from "../context"
import { bytes, fileName, oneLine, truncate } from "../format"
import type { ChatFile, FeedUnit, Goal, Idea, MailThread, Task, TaskRun } from "../protocol"
import { VIEWS, type State, type View } from "../store"
import { gradientAt, theme } from "../theme"
import { GradientText, spinner, statusColor } from "./common"

export type PanelItem =
  | { kind: "feed"; v: FeedUnit }
  | { kind: "goal"; v: Goal }
  | { kind: "idea"; v: Idea; section: string; first: boolean }
  | { kind: "task"; v: Task }
  | { kind: "run"; v: TaskRun; first: boolean }
  | { kind: "thread"; v: MailThread }
  | { kind: "file"; v: ChatFile }

export function panelItems(s: State, view: View): PanelItem[] {
  switch (view) {
    case "feed":
      return (s.feed.data ?? []).map((v) => ({ kind: "feed", v }))
    case "goals":
      return (s.goals.data ?? []).map((v) => ({ kind: "goal", v }))
    case "ideas": {
      const out: PanelItem[] = []
      let last = ""
      for (const v of s.ideas.data ?? []) {
        const section = v.section || "Ideas"
        out.push({ kind: "idea", v, section, first: section !== last })
        last = section
      }
      return out
    }
    case "tasks":
      return [
        ...(s.tasks.data?.tasks ?? []).map((v) => ({ kind: "task" as const, v })),
        ...(s.tasks.data?.runs ?? []).map((v, i) => ({ kind: "run" as const, v, first: i === 0 })),
      ]
    case "mail":
      return (s.mail.data?.threads ?? []).map((v) => ({ kind: "thread", v }))
    case "files":
      return (s.files.data ?? []).map((v) => ({ kind: "file", v }))
    default:
      return []
  }
}

// Panel width from which Mail shows the open thread beside the list.
export const MAIL_SPLIT = 80

export const PANEL_HINTS: Record<Exclude<View, "chat">, string> = {
  feed: "↑↓ move  ↵ read  l like  h love  d less like this  r refresh",
  goals: "↑↓ move  ↵ details  r refresh",
  ideas: "↑↓ move  ↵ details  x ask Muse to do it  r refresh",
  tasks: "↑↓ move  ↵ details  r refresh",
  mail: "↑↓ move  ↵ open thread  esc close  r refresh",
  files: "↑↓ move  ↵ download to ~/Downloads/muse  r refresh",
}

const EMPTY: Record<Exclude<View, "chat">, string> = {
  feed: "Your feed is empty. Your Muse writes new editions through the day.",
  goals: "No goals yet. Tell your Muse what you're working toward.",
  ideas: "No idea cards right now.",
  tasks: "No scheduled tasks. Ask your Muse to remind you of something.",
  mail: "No Muse Mail yet.",
  files: "No files in this chat yet. Ask your Muse to make an image.",
}

function Card(props: { selected: boolean; id: string; children: ReactNode; onClick?: () => void; accent?: string }) {
  return (
    <box
      id={props.id}
      border
      borderStyle="rounded"
      borderColor={props.selected ? (props.accent ?? theme.metaBlue) : theme.divider}
      paddingX={1}
      flexDirection="column"
      marginBottom={0}
      onMouseDown={props.onClick}
      flexShrink={0}
    >
      {props.children}
    </box>
  )
}

function SectionTitle(props: { text: string }) {
  return (
    <box height={1} marginTop={1} flexShrink={0}>
      <text fg={theme.textMuted} attributes={TextAttributes.BOLD} selectable={false}>
        {props.text.toUpperCase()}
      </text>
    </box>
  )
}

function Row(props: { item: PanelItem; i: number; selected: boolean; width: number }) {
  const { ctl } = useApp()
  const { item, i, selected } = props
  const id = `row-${i}`
  const w = Math.max(20, props.width - 6)
  const select = () => ctl.store.set((s) => ({ selected: { ...s.selected, [s.view]: i } }))
  switch (item.kind) {
    case "feed": {
      const u = item.v
      const r = u.reaction === "love" ? "♥ loved" : u.reaction === "like" ? "▲ liked" : u.reaction === "dislike" ? "▼ less" : ""
      return (
        <Card id={id} selected={selected} onClick={select}>
          <text fg="#FFFFFF" attributes={TextAttributes.BOLD} wrapMode="word">
            {u.title || "Untitled"}
          </text>
          {u.summary ? (
            <text fg={theme.textSoft} wrapMode="word">
              {selected ? oneLine(u.summary) : truncate(oneLine(u.summary), w * 2 - 4)}
            </text>
          ) : null}
          <box flexDirection="row">
            <text fg={theme.textFaint}>{[u.date, u.edition].filter(Boolean).join(" · ")}</text>
            <box flexGrow={1} />
            <text fg={u.reaction === "love" ? theme.pink : theme.link}>{r}</text>
          </box>
        </Card>
      )
    }
    case "goal": {
      const g = item.v
      return (
        <Card id={id} selected={selected} onClick={select}>
          <box flexDirection="row">
            <text fg={statusColor(g.status)}>{"● "}</text>
            <text fg="#FFFFFF" attributes={TextAttributes.BOLD} wrapMode="word" flexShrink={1}>
              {g.title}
            </text>
            <box flexGrow={1} />
            <text fg={statusColor(g.status)}>{(g.status ?? "").replace(/_/g, " ")}</text>
          </box>
          {g.subtitle ? (
            <text fg={theme.textSoft} wrapMode="word">
              {g.subtitle}
            </text>
          ) : null}
        </Card>
      )
    }
    case "idea": {
      const v = item.v
      return (
        <box flexDirection="column" flexShrink={0}>
          {item.first ? <SectionTitle text={item.section} /> : null}
          <Card id={id} selected={selected} onClick={select} accent={theme.purple}>
            <text wrapMode="word">
              <span fg={gradientAt((i % 6) / 6)}>{"✦ "}</span>
              <span fg="#FFFFFF">{v.title}</span>
            </text>
            {v.summary ? (
              <text fg={theme.textSoft} wrapMode="word">
                {selected ? oneLine(v.summary) : truncate(oneLine(v.summary), w * 2 - 4)}
              </text>
            ) : null}
          </Card>
        </box>
      )
    }
    case "task": {
      const t = item.v
      return (
        <box flexDirection="column" flexShrink={0}>
          {i === 0 ? <SectionTitle text="Scheduled" /> : null}
          <Card id={id} selected={selected} onClick={select}>
            <box flexDirection="row">
              <text fg={t.enabled === false ? theme.textFaint : theme.green}>{t.enabled === false ? "○ " : "● "}</text>
              <text fg="#FFFFFF" attributes={TextAttributes.BOLD} flexShrink={1}>
                {t.title}
              </text>
              <box flexGrow={1} />
              <text fg={theme.textMuted}>{t.next_run ? `next ${t.next_run}` : "paused"}</text>
            </box>
            <text fg={theme.textFaint}>{[t.schedule, t.mode, t.timezone].filter(Boolean).join(" · ")}</text>
          </Card>
        </box>
      )
    }
    case "run": {
      const r = item.v
      return (
        <box flexDirection="column" flexShrink={0}>
          {item.first ? <SectionTitle text="Recent runs" /> : null}
          <box id={id} flexDirection="row" height={1} backgroundColor={selected ? theme.card : undefined} onMouseDown={select} paddingX={1}>
            <text fg={statusColor(r.status)}>{`● ${(r.status ?? "?").padEnd(10)}`}</text>
            <text fg={theme.textMuted}>{`${(r.scheduled ?? "").padEnd(17)}`}</text>
            <text fg={r.error ? theme.red : theme.textSoft}>{truncate(oneLine(r.error || r.summary || r.trigger || ""), w - 30)}</text>
          </box>
        </box>
      )
    }
    case "thread": {
      const t = item.v
      return (
        <Card id={id} selected={selected} onClick={() => (select(), ctl.openMailThread(t.id))}>
          <box flexDirection="row">
            <text fg="#FFFFFF" attributes={TextAttributes.BOLD} flexShrink={1}>
              {truncate(t.subject || "(no subject)", w - 14)}
            </text>
            <box flexGrow={1} />
            <text fg={theme.textFaint}>{t.last_date ?? ""}</text>
          </box>
          <text fg={theme.textMuted}>{truncate(`${t.last_from ?? ""}${t.messages ? `  ·  ${t.messages} messages` : ""}`, w)}</text>
          {t.preview ? <text fg={theme.textSoft}>{truncate(oneLine(t.preview), w)}</text> : null}
        </Card>
      )
    }
    case "file": {
      const f = item.v
      const kind = (f.kind ?? "file").replace(/s$/, "")
      return (
        <box id={id} flexDirection="row" height={1} backgroundColor={selected ? theme.card : undefined} onMouseDown={() => (select(), ctl.download(f.path))} paddingX={1}>
          <text fg={theme.link}>{kind === "image" ? "▣ " : kind === "video" ? "▶ " : "▤ "}</text>
          <text fg={selected ? "#FFFFFF" : theme.text}>{truncate(f.label || fileName(f.path), w - 30).padEnd(Math.max(10, w - 30))}</text>
          <text fg={theme.textMuted}>{`${kind.padEnd(8)} ${bytes(f.byte_len).padStart(8)}`}</text>
          <box flexGrow={1} />
          <text fg={theme.link}>{selected ? "↵ download" : ""}</text>
        </box>
      )
    }
  }
}

function MailThreadPane() {
  const t = useS((s) => s.mailThread)
  const tick = useTick(80, t.status === "loading")
  const style = useSyntaxStyle()
  if (t.status === "idle") {
    return (
      <box flexGrow={1} alignItems="center" justifyContent="center">
        <text fg={theme.textFaint}>Select a thread and press ↵</text>
      </box>
    )
  }
  if (t.status === "loading") return <text fg={theme.textMuted}>{`${spinner(tick)} opening thread`}</text>
  if (t.status === "error") return <text fg={theme.red}>{t.error}</text>
  return (
    <scrollbox flexGrow={1} flexBasis={0} minHeight={0}>
      {(t.data ?? []).map((m) => (
        <box key={m.id} flexDirection="column" marginBottom={1} border={["left"]} borderColor={m.direction === "outbound" ? theme.metaBlue : theme.divider} paddingLeft={1}>
          <text fg="#FFFFFF" attributes={TextAttributes.BOLD}>
            {m.subject || "(no subject)"}
          </text>
          <text fg={theme.textMuted}>{`${m.from ?? ""}  ·  ${m.date ?? ""}`}</text>
          <markdown content={(m.text || "").slice(0, 6000)} syntaxStyle={style} conceal fg={theme.textSoft} />
          {m.attachments?.length ? (
            <text fg={theme.link}>{m.attachments.map((a) => `⎘ ${a.filename ?? `attachment ${a.index}`}`).join("   ")}</text>
          ) : null}
        </box>
      ))}
    </scrollbox>
  )
}

export function Panel(props: { view: Exclude<View, "chat">; width: number }) {
  const { view } = props
  const { store } = useApp()
  const state = useS((s) => s[view])
  const items = useMemo(() => panelItems(store.get(), view), [state, view])
  const index = useS((s) => s.selected[view])
  const tick = useTick(80, state.status === "loading")
  const scroll = useRef<ScrollBoxRenderable>(null)
  const meta = VIEWS.find((v) => v.id === view)!
  const mailbox = useS((s) => s.mail.data?.mailbox)
  const split = view === "mail" && props.width >= MAIL_SPLIT

  useEffect(() => {
    scroll.current?.scrollChildIntoView(`row-${index}`)
  }, [index, items.length])

  const count = items.length
  const listWidth = split ? Math.floor(props.width * 0.45) : props.width
  const sub =
    view === "mail" && mailbox
      ? String(mailbox.address ?? mailbox.email ?? mailbox.email_address ?? "")
      : meta.hint

  return (
    <box flexDirection="column" flexGrow={1} paddingX={2} paddingTop={1} backgroundColor={theme.bg}>
      <box flexDirection="row" height={1} flexShrink={0}>
        <GradientText text={`${meta.icon} ${meta.label}`} bold />
        <text fg={theme.textMuted}>{`   ${sub}`}</text>
        <box flexGrow={1} />
        <text fg={theme.textFaint}>
          {state.status === "loading" ? `${spinner(tick)} refreshing` : count ? `${Math.min(index + 1, count)} of ${count}` : ""}
        </text>
      </box>
      <box height={1} flexShrink={0} />
      {state.status === "error" && state.off ? (
        <box flexGrow={1} alignItems="center" justifyContent="center" flexDirection="column" gap={1}>
          <text fg={theme.textSoft}>{`${meta.icon}  ${meta.label} isn't turned on for this account`}</text>
          <text fg={theme.textMuted} wrapMode="word">{state.error}</text>
        </box>
      ) : state.status === "error" ? (
        <box border borderStyle="rounded" borderColor={theme.red} padding={1} flexShrink={0}>
          <text fg={theme.text} wrapMode="word">
            {`Couldn't load ${meta.label.toLowerCase()}: ${state.error}  ·  press r to retry`}
          </text>
        </box>
      ) : null}
      {state.status === "loading" && !count ? (
        <text fg={theme.textMuted}>{`${spinner(tick)} loading ${meta.label.toLowerCase()}…`}</text>
      ) : null}
      {state.status === "ready" && !count ? (
        <box flexGrow={1} alignItems="center" justifyContent="center">
          <text fg={theme.textMuted}>{EMPTY[view]}</text>
        </box>
      ) : null}
      <box flexDirection="row" flexGrow={1} gap={2} minHeight={0}>
        <scrollbox ref={scroll} width={split ? listWidth : undefined} flexGrow={split ? 0 : 1} flexBasis={split ? undefined : 0} minHeight={0} contentOptions={{ gap: 0 }}>
          {items.map((it, i) => (
            <Row key={`${it.kind}-${(it.v as any).id ?? (it.v as any).run_id ?? (it.v as any).path ?? i}`} item={it} i={i} selected={i === index} width={listWidth} />
          ))}
        </scrollbox>
        {split ? (
          <box flexGrow={1} flexDirection="column" minHeight={0}>
            <MailThreadPane />
          </box>
        ) : null}
      </box>
      <box height={1} flexShrink={0}>
        <text fg={theme.textFaint} selectable={false}>
          {PANEL_HINTS[view]}
        </text>
      </box>
    </box>
  )
}

// A readable markdown rendering of an arbitrary server object.
export function toMarkdown(o: any, depth = 0): string {
  if (o == null) return ""
  if (typeof o !== "object") return String(o)
  if (Array.isArray(o)) {
    return o
      .map((x) => {
        if (x && typeof x === "object") {
          const label = x.title || x.name || x.text || x.label || x.description
          const rest = toMarkdown(omit(x, ["title", "name", "text", "label"]), depth + 1)
          return `- ${label ? `**${oneLine(String(label))}**` : ""}${rest ? `\n${indent(rest)}` : ""}`
        }
        return `- ${x}`
      })
      .join("\n")
  }
  const lines: string[] = []
  for (const [k, v] of Object.entries(o)) {
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) continue
    if (/(^id$|_id$|Id$|_ms$|_utc$|^seq$|^etag$|^version$)/.test(k) && depth > 0) continue
    if (/(^id$|_id$|Id$)/.test(k)) continue
    const label = k.replace(/[_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2")
    const name = label.charAt(0).toUpperCase() + label.slice(1)
    if (typeof v === "object") {
      const inner = toMarkdown(v, depth + 1)
      if (inner) lines.push(depth === 0 ? `### ${name}\n${inner}` : `**${name}:**\n${inner}`)
    } else if (typeof v === "string" && v.length > 80) {
      lines.push(depth === 0 ? `### ${name}\n${v}` : `**${name}:** ${v}`)
    } else {
      lines.push(`**${name}:** ${v}`)
    }
  }
  return lines.join(depth === 0 ? "\n\n" : "\n")
}

function omit(o: any, keys: string[]) {
  const c = { ...o }
  for (const k of keys) delete c[k]
  return c
}

function indent(s: string) {
  return s
    .split("\n")
    .map((l) => "  " + l)
    .join("\n")
}
