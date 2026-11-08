import type { ScrollBoxRenderable } from "@opentui/core"
import { forwardRef, memo, useEffect, useMemo, useRef, useState } from "react"
import { useApp, useRenderNode, useS, useSyntaxStyle, useTick } from "../context"
import { bytes, clock, dayLabel, fileName, truncate } from "../format"
import type { FileRef, Message } from "../protocol"
import type { Pending } from "../store"
import { gradientAt, gradientWave, theme } from "../theme"
import { GradientText, spinner } from "./common"

const FILE_ICON: Record<string, string> = { image: "▣", video: "▶", audio: "♪", document: "▤", link: "↗" }

function FileChips(props: { files: FileRef[] }) {
  const { ctl } = useApp()
  if (!props.files?.length) return null
  return (
    <box flexDirection="row" flexWrap="wrap" gap={1} paddingLeft={2} marginTop={1}>
      {props.files.map((f) => {
        const kind = (f.kind ?? "file").replace(/s$/, "")
        const name = truncate(f.label || fileName(f.path), 36)
        return (
          <box
            key={f.path}
            border
            borderStyle="rounded"
            borderColor={theme.divider}
            paddingX={1}
            flexDirection="row"
            onMouseDown={() => ctl.download(f.path)}
          >
            <text selectable={false}>
              <span fg={theme.link}>{FILE_ICON[kind] ?? "▤"}</span>
              <span fg={theme.text}>{` ${name}`}</span>
              <span fg={theme.textMuted}>{`  ${[kind, bytes(f.byte_len)].filter(Boolean).join(" · ")}`}</span>
              <span fg={theme.link}>{"  ⤓"}</span>
            </text>
          </box>
        )
      })}
    </box>
  )
}

// Reveals streamed text at a pace that catches up with the backlog, so a
// reply that arrives in bursts still reads like smooth typing.
function useTypewriter(target: string, active: boolean): string {
  const [shown, setShown] = useState(active ? "" : target)
  const ref = useRef(shown)
  useEffect(() => {
    if (!active) {
      ref.current = target
      setShown(target)
      return
    }
    if (!target.startsWith(ref.current)) {
      ref.current = target.slice(0, Math.min(ref.current.length, target.length))
    }
    const id = setInterval(() => {
      const cur = ref.current
      if (cur.length >= target.length) return
      const backlog = target.length - cur.length
      const step = Math.max(2, Math.ceil(backlog / 8))
      ref.current = target.slice(0, cur.length + step)
      setShown(ref.current)
    }, 33)
    return () => clearInterval(id)
  }, [target, active])
  return shown
}

export const AssistantMessage = memo(function AssistantMessage(props: { m: Message; streaming?: boolean }) {
  const style = useSyntaxStyle()
  const renderNode = useRenderNode()
  const { m } = props
  const text = useTypewriter(m.text, !!props.streaming)
  const tick = useTick(80, !!props.streaming)
  return (
    <box flexDirection="column" marginBottom={1} paddingRight={4}>
      <box flexDirection="row" height={1}>
        <GradientText text="◆ Muse" bold phase={props.streaming ? tick / 25 : 0} wave={props.streaming} />
        <text fg={theme.textFaint} selectable={false}>
          {`  ${clock(m.at_ms)}`}
          {m.push ? "  · update" : ""}
        </text>
      </box>
      {text ? (
        <box paddingLeft={2}>
          <markdown content={props.streaming ? text + " ▍" : text} syntaxStyle={style} renderNode={renderNode} internalBlockMode="top-level" conceal streaming={!!props.streaming} fg={theme.text} />
        </box>
      ) : null}
      <FileChips files={m.files} />
    </box>
  )
})

export const UserMessage = memo(function UserMessage(props: { text: string; at_ms: number; state?: "sending" | "failed"; onRetry?: () => void }) {
  const failed = props.state === "failed"
  return (
    <box flexDirection="column" marginBottom={1} alignItems="flex-end" paddingLeft={10}>
      <box backgroundColor={failed ? "#5A1A24" : props.state ? "#2D5BB8" : theme.userBubble} paddingX={2} onMouseDown={props.onRetry}>
        <text fg={theme.userText} wrapMode="word">
          {props.text}
        </text>
      </box>
      <text fg={failed ? theme.red : theme.textFaint} selectable={false}>
        {failed ? "Not sent · click to retry" : props.state === "sending" ? "Sending…" : clock(props.at_ms)}
      </text>
    </box>
  )
})

function Thinking(props: { since: number }) {
  const tick = useTick(70)
  const secs = Math.max(0, Math.floor((Date.now() - props.since) / 1000))
  const t = tick / 28
  const word = "Muse is thinking"
  return (
    <box flexDirection="row" height={1} marginBottom={1}>
      <text selectable={false}>
        <span fg={gradientWave(t)}>{spinner(tick)}</span>
        <span> </span>
        {[...word].map((ch, i) => (
          <span key={i} fg={gradientWave(t - i * 0.035)}>
            {ch}
          </span>
        ))}
        <span fg={theme.textFaint}>{secs >= 3 ? `  ${secs}s` : ""}</span>
      </text>
    </box>
  )
}

function DaySep(props: { label: string }) {
  return (
    <box flexDirection="row" height={1} marginBottom={1} marginTop={0} justifyContent="center">
      <text fg={theme.textFaint} selectable={false}>
        {"──── "}
        <span fg={theme.textMuted}>{props.label}</span>
        {" ────"}
      </text>
    </box>
  )
}

const SUGGESTIONS = [
  "What's on my plate today?",
  "Summarize my unread Muse Mail",
  "Help me plan the week ahead",
  "Give me three ideas for this weekend",
]

function Welcome(props: { title: string; main: boolean }) {
  const { ctl } = useApp()
  return (
    <box flexDirection="column" alignItems="center" paddingTop={2} gap={1}>
      <GradientText text={props.main ? "Hi, I'm your Muse." : `“${props.title}”`} bold />
      <text fg={theme.textMuted}>{props.main ? "Ask me anything, or try one of these:" : "A fresh side chat. Try one of these:"}</text>
      <box flexDirection="column" gap={0} marginTop={1}>
        {SUGGESTIONS.map((s, i) => (
          <box key={s} onMouseDown={() => ctl.send(s)} paddingX={2} border borderStyle="rounded" borderColor={theme.divider}>
            <text selectable={false}>
              <span fg={gradientAt(i / SUGGESTIONS.length)}>{"✦ "}</span>
              <span fg={theme.text}>{s}</span>
            </text>
          </box>
        ))}
      </box>
    </box>
  )
}

function Skeleton() {
  const tick = useTick(60)
  const rows = [46, 70, 58, 0, 30, 64, 52]
  return (
    <box flexDirection="column" paddingTop={1} gap={0}>
      {rows.map((w, i) =>
        w === 0 ? (
          <box key={i} height={1} />
        ) : (
          <text key={i} selectable={false}>
            {[...Array(Math.floor(w / 2))].map((_, j) => (
              <span key={j} fg={gradientWave(tick / 50 - j * 0.02 - i * 0.05, [theme.card, theme.raised, theme.card])}>
                ▀▀
              </span>
            ))}
          </text>
        ),
      )}
    </box>
  )
}

type Row =
  | { kind: "day"; key: string; label: string }
  | { kind: "msg"; key: string; m: Message }
  | { kind: "pending"; key: string; p: Pending }

function buildRows(messages: Message[], pending: Pending[]): Row[] {
  const rows: Row[] = []
  let lastDay = ""
  const push = (at: number) => {
    const label = at ? dayLabel(at) : ""
    if (label && label !== lastDay) {
      rows.push({ kind: "day", key: `day-${label}-${at}`, label })
      lastDay = label
    }
  }
  for (const m of messages) {
    push(m.at_ms)
    rows.push({ kind: "msg", key: `m${m.seq}`, m })
  }
  for (const p of pending) {
    push(p.at_ms)
    rows.push({ kind: "pending", key: p.key, p })
  }
  return rows
}

export const Transcript = forwardRef<ScrollBoxRenderable, {}>(function Transcript(_props, ref) {
  const { ctl } = useApp()
  const messages = useS((s) => s.messages)
  const pending = useS((s) => s.pending)
  const draft = useS((s) => s.draft)
  const thinking = useS((s) => s.thinkingSince)
  const loading = useS((s) => s.historyLoading)
  const chat = useS((s) => s.chat)
  const rows = useMemo(() => buildRows(messages, pending), [messages, pending])
  const empty = !loading && rows.length === 0 && !draft && !thinking

  return (
    <scrollbox
      ref={ref}
      flexGrow={1}
      flexBasis={0}
      minHeight={0}
      stickyScroll
      stickyStart="bottom"
      paddingX={2}
      verticalScrollbarOptions={{ trackOptions: { foregroundColor: theme.raised, backgroundColor: theme.bg } }}
      contentOptions={{ paddingTop: 1, paddingRight: 1 }}
    >
      {loading && rows.length === 0 ? <Skeleton /> : null}
      {messages.length >= 40 ? (
        <box flexDirection="row" justifyContent="center" height={1} marginBottom={1} onMouseDown={() => ctl.loadOlder()}>
          <text fg={theme.textFaint} selectable={false}>
            {loading ? "loading older messages…" : "↑ PgUp at the top for older messages"}
          </text>
        </box>
      ) : null}
      {empty ? <Welcome title={chat.title} main={!chat.session_id} /> : null}
      {rows.map((r) =>
        r.kind === "day" ? (
          <DaySep key={r.key} label={r.label} />
        ) : r.kind === "msg" ? (
          r.m.role === "user" ? (
            <UserMessage key={r.key} text={r.m.text} at_ms={r.m.at_ms} />
          ) : (
            <AssistantMessage key={r.key} m={r.m} />
          )
        ) : (
          <UserMessage
            key={r.key}
            text={r.p.text}
            at_ms={r.p.at_ms}
            state={r.p.failed ? "failed" : "sending"}
            onRetry={r.p.failed ? () => ctl.retry(r.p.key) : undefined}
          />
        ),
      )}
      {draft ? <AssistantMessage key={`draft-${draft.id}`} m={draft} streaming /> : null}
      {thinking && !draft ? <Thinking since={thinking} /> : null}
    </scrollbox>
  )
})

