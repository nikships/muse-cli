import { createCliRenderer } from "@opentui/core"
import { createRoot } from "@opentui/react"
import { App } from "./app"
import { Bridge, spawnPythonBridge, type Transport } from "./bridge"
import { AppContext } from "./context"
import { Controller } from "./controller"
import { Store } from "./store"
import { theme } from "./theme"

const demo = process.env.MUSE_CLI_DEMO === "1"

let transport: Transport
if (process.env.MUSE_CLI_TUI_FAKE === "1") {
  const { createFakeTransport } = await import("../test/fake")
  transport = createFakeTransport()
} else {
  transport = spawnPythonBridge(demo)
}

const bridge = new Bridge(transport)
const store = new Store()
const ctl = new Controller(bridge, store)

let exitCode = 0
const renderer = await createCliRenderer({
  exitOnCtrlC: false,
  backgroundColor: theme.bg,
  useMouse: true,
  targetFps: 60,
  onDestroy: () => {
    bridge.close()
    setTimeout(() => process.exit(exitCode), 30)
  },
})
renderer.setTerminalTitle("muse")

ctl.onQuit = () => {
  if (!renderer.isDestroyed) renderer.destroy()
}

createRoot(renderer).render(
  <AppContext.Provider value={{ ctl, store }}>
    <App />
  </AppContext.Provider>,
)

ctl.boot()
