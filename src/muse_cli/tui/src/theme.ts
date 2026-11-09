// Meta / Facebook dark palette. Surfaces follow Facebook's dark mode; accents
// are Meta blue, Facebook blue and the Meta AI gradient.
export const theme = {
  bg: "#101113",
  surface: "#18191A",
  card: "#242526",
  raised: "#3A3B3C",
  hover: "#4E4F50",
  divider: "#3E4042",
  text: "#E4E6EB",
  textSoft: "#B0B3B8",
  textMuted: "#8A8D91",
  textFaint: "#65676B",
  metaBlue: "#0866FF",
  fbBlue: "#1877F2",
  messenger: "#0084FF",
  link: "#4599FF",
  purple: "#A033FF",
  pink: "#FF5C87",
  green: "#31A24C",
  red: "#F02849",
  yellow: "#F7B928",
  userBubble: "#0866FF",
  userText: "#FFFFFF",
  selection: "#263951",
} as const

// Meta AI ring: blue -> violet -> pink.
export const gradient = ["#0064E0", "#0082FB", "#5B5BFF", "#A033FF", "#D63CC8", "#FF5C87"] as const

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function rgbToHex([r, g, b]: [number, number, number]): string {
  return "#" + [r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("")
}

export function mix(a: string, b: string, t: number): string {
  const x = hexToRgb(a)
  const y = hexToRgb(b)
  return rgbToHex([x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t])
}

// Sample the gradient at t in [0, 1]; values outside wrap around.
export function gradientAt(t: number, stops: readonly string[] = gradient): string {
  const u = ((t % 1) + 1) % 1
  const pos = u * (stops.length - 1)
  const i = Math.min(stops.length - 2, Math.floor(pos))
  return mix(stops[i]!, stops[i + 1]!, pos - i)
}

// A ping-pong sample so looping animations never jump from pink back to blue.
export function gradientWave(t: number, stops: readonly string[] = gradient): string {
  const u = ((t % 1) + 1) % 1
  return gradientAt(u < 0.5 ? u * 2 : 2 - u * 2, stops)
}
