import { TextAttributes } from "@opentui/core"
import { gradientAt, gradientWave, theme } from "../theme"

const SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

export function spinner(tick: number) {
  return SPIN[tick % SPIN.length]!
}

// Text with one gradient color per character. `phase` shifts it for shimmer.
export function GradientText(props: { text: string; phase?: number; spread?: number; bold?: boolean; wave?: boolean }) {
  const chars = [...props.text]
  const spread = props.spread ?? Math.max(chars.length, 1)
  const pick = props.wave ? gradientWave : gradientAt
  return (
    <text attributes={props.bold ? TextAttributes.BOLD : 0} selectable={false}>
      {chars.map((ch, i) => (
        <span key={i} fg={pick((props.phase ?? 0) + i / spread)}>
          {ch}
        </span>
      ))}
    </text>
  )
}

export function Kbd(props: { k: string; label?: string; dim?: boolean }) {
  return (
    <text selectable={false}>
      <span fg={props.dim ? theme.textMuted : theme.text} bg={theme.raised}>
        {` ${props.k} `}
      </span>
      {props.label ? <span fg={theme.textMuted}>{` ${props.label}`}</span> : null}
    </text>
  )
}

export function statusColor(status?: string): string {
  const s = (status ?? "").toLowerCase()
  if (/(done|complete|succe|achiev|ok|active|enabled|on_track)/.test(s)) return theme.green
  if (/(fail|error|blocked|missed|off_track)/.test(s)) return theme.red
  if (/(progress|running|pending|queued|scheduled|started)/.test(s)) return theme.yellow
  return theme.textMuted
}
