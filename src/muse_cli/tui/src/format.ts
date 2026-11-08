export function width(s: string): number {
  return Bun.stringWidth(s)
}

// Cut to at most n display cells, ending with an ellipsis when cut.
export function truncate(s: string, n: number): string {
  if (n <= 0) return ""
  if (width(s) <= n) return s
  let out = ""
  for (const ch of s) {
    if (width(out + ch) > n - 1) break
    out += ch
  }
  return out + "…"
}

export function padEnd(s: string, n: number): string {
  const w = width(s)
  return w >= n ? s : s + " ".repeat(n - w)
}

export function oneLine(s: string): string {
  return s
    .replace(/[`*_#>]+/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim()
}

export function clock(ms: number): string {
  if (!ms) return ""
  const d = new Date(ms)
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
}

export function dayLabel(ms: number, now = Date.now()): string {
  const d = new Date(ms)
  const today = new Date(now)
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((start(today) - start(d)) / 86_400_000)
  if (diff === 0) return "Today"
  if (diff === 1) return "Yesterday"
  if (diff < 7) return d.toLocaleDateString([], { weekday: "long" })
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: d.getFullYear() === today.getFullYear() ? undefined : "numeric" })
}

export function ago(ms: number, now = Date.now()): string {
  if (!ms) return ""
  const s = Math.max(0, Math.round((now - ms) / 1000))
  if (s < 45) return "now"
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.round(h / 24)
  if (d < 7) return `${d}d`
  const w = Math.round(d / 7)
  if (w < 5) return `${w}w`
  return new Date(ms).toLocaleDateString([], { month: "short", day: "numeric" })
}

// Server dates arrive as "2026-11-08 12:09" (local) or ISO. Unknown shapes pass through.
export function parseDate(s?: string | null): number | null {
  if (!s) return null
  const m = /^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2})?)(.*))?$/.exec(s.trim())
  if (!m) return null
  const ms = new Date(`${m[1]}T${m[2] ?? "00:00"}${m[3] ?? ""}`).getTime()
  return Number.isNaN(ms) ? null : ms
}

// "9:00 AM" today, "Tomorrow 9:00 AM", "Nov 9, 9:00 AM"; short drops the time off today.
export function when(s?: string | null, now = Date.now(), short = false): string {
  const ms = parseDate(s)
  if (ms === null) return s ?? ""
  const d = new Date(ms)
  const today = new Date(now)
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((start(d) - start(today)) / 86_400_000)
  const time = /\d{2}:\d{2}/.test(s!) ? clock(ms) : ""
  if (diff === 0) return time || "Today"
  const name =
    diff === 1 ? "Tomorrow"
    : diff === -1 ? "Yesterday"
    : d.toLocaleDateString([], { month: "short", day: "numeric", year: d.getFullYear() === today.getFullYear() ? undefined : "numeric" })
  return short || !time ? name : `${name}, ${time}`
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`
}

export function bytes(n?: number): string {
  if (!n && n !== 0) return ""
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function fileName(path: string): string {
  let clean = path.split("?")[0] ?? path
  try {
    clean = decodeURIComponent(clean)
  } catch {
    // A stray % is not an escape; show the path as it is.
  }
  clean = clean.replace(/\/+$/, "")
  return clean.slice(clean.lastIndexOf("/") + 1) || "file"
}

// Subsequence match with bonuses for word starts and adjacency. -1 = no match.
export function fuzzyScore(query: string, target: string): number {
  const q = query.toLowerCase().trim()
  if (!q) return 0
  const t = target.toLowerCase()
  if (t.includes(q)) return 1000 - t.indexOf(q) * 2 - t.length * 0.1
  let score = 0
  let ti = 0
  let prev = -2
  for (const ch of q) {
    if (ch === " ") continue
    const found = t.indexOf(ch, ti)
    if (found < 0) return -1
    score += found === prev + 1 ? 8 : 1
    if (found === 0 || /[\s\-_/]/.test(t[found - 1] ?? "")) score += 6
    prev = found
    ti = found + 1
  }
  return score - t.length * 0.05
}
