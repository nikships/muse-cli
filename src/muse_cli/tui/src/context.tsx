import { SyntaxStyle, RGBA } from "@opentui/core"
import { useRenderer } from "@opentui/react"
import { createContext, useContext, useEffect, useMemo, useState } from "react"
import type { Controller } from "./controller"
import { useStore, type State, type Store } from "./store"
import { theme } from "./theme"

export const AppContext = createContext<{ ctl: Controller; store: Store } | null>(null)

export function useApp() {
  const v = useContext(AppContext)
  if (!v) throw new Error("AppContext missing")
  return v
}

export function useS<T>(select: (s: State) => T): T {
  const { store } = useApp()
  return useStore(store, select)
}

// A frame counter that only ticks while `active`, so idle screens cost nothing.
export function useTick(ms: number, active = true): number {
  const [n, setN] = useState(0)
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setN((x) => x + 1), ms)
    return () => clearInterval(id)
  }, [ms, active])
  return n
}

export function useNow(ms = 30_000): number {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

// A SyntaxStyle lives in one renderer's native scene, so cache one per renderer.
const styles = new WeakMap<object, SyntaxStyle>()

export function useSyntaxStyle(): SyntaxStyle {
  const renderer = useRenderer()
  return useMemo(() => {
    const hit = styles.get(renderer)
    if (hit) return hit
    const c = (hex: string) => RGBA.fromHex(hex)
    const style = SyntaxStyle.fromStyles(
      {
        default: { fg: c(theme.text) },
        "markup.heading": { fg: c("#FFFFFF"), bold: true },
        "markup.heading.1": { fg: c(theme.link), bold: true },
        "markup.heading.2": { fg: c("#8AB4FF"), bold: true },
        "markup.heading.3": { fg: c("#B9A6FF"), bold: true },
        "markup.strong": { fg: c("#FFFFFF"), bold: true },
        "markup.italic": { fg: c(theme.text), italic: true },
        "markup.strikethrough": { fg: c(theme.textMuted), dim: true },
        "markup.list": { fg: c(theme.metaBlue), bold: true },
        "markup.quote": { fg: c(theme.textSoft), italic: true },
        "markup.raw": { fg: c("#FFB4D2"), bg: c("#2A1F2B") },
        "markup.raw.block": { fg: c(theme.text) },
        "markup.link": { fg: c(theme.link), underline: true },
        "markup.link.label": { fg: c(theme.link), underline: true },
        "markup.link.url": { fg: c(theme.textMuted), underline: true },
        "punctuation.special": { fg: c(theme.textFaint) },
        conceal: { fg: c(theme.textFaint) },
        keyword: { fg: c("#C792EA"), bold: true },
        string: { fg: c("#A5E075") },
        number: { fg: c("#F78C6C") },
        comment: { fg: c(theme.textMuted), italic: true },
        function: { fg: c("#82AAFF") },
        "function.call": { fg: c("#82AAFF") },
        type: { fg: c("#FFCB6B") },
        variable: { fg: c(theme.text) },
        property: { fg: c("#89DDFF") },
        operator: { fg: c("#89DDFF") },
        "punctuation.bracket": { fg: c(theme.textSoft) },
        constant: { fg: c("#F78C6C") },
        boolean: { fg: c("#F78C6C") },
      },
      renderer.nativeScene!,
    )
    styles.set(renderer, style)
    return style
  }, [renderer])
}
