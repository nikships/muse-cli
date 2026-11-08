import { createCliRenderer } from "@opentui/core"
import { createRoot } from "@opentui/react"

function App() {
  return (
    <box border padding={1} flexDirection="column">
      <ascii-font text="muse" font="tiny" />
      <text fg="#0866FF">hello</text>
    </box>
  )
}

const renderer = await createCliRenderer({ exitOnCtrlC: true })
createRoot(renderer).render(<App />)
setTimeout(() => renderer.destroy(), 1500)
