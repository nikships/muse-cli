import { TextAttributes } from "@opentui/core"
import { useKeyboard, useTerminalDimensions } from "@opentui/react"
import { useApp, useS, useTick } from "../context"
import { gradient, gradientWave, theme } from "../theme"
import { Kbd, spinner } from "./common"

export function Splash() {
  const { ctl } = useApp()
  const phase = useS((s) => s.phase)
  const detail = useS((s) => s.phaseDetail)
  const busy = useS((s) => s.loginBusy)
  const version = useS((s) => s.version)
  const demo = useS((s) => s.demo)
  const { width, height } = useTerminalDimensions()
  const tick = useTick(70)
  const t = tick / 40

  useKeyboard((key) => {
    if (phase === "auth" && (key.name === "l" || key.name === "return") && !busy) ctl.login()
    if (phase === "fatal" && key.name === "r") ctl.boot()
    if ((phase === "auth" || phase === "fatal") && (key.name === "q" || key.name === "escape")) ctl.onQuit()
  })

  const big = width >= 44 && height >= 16
  const colors = [0, 1, 2, 3].map((i) => gradientWave(t + i * 0.12))
  const working = phase === "starting" || phase === "connecting" || busy

  return (
    <box width="100%" height="100%" backgroundColor={theme.bg} alignItems="center" justifyContent="center" flexDirection="column">
      {big ? (
        <ascii-font text="muse" font="block" color={colors} />
      ) : (
        <text attributes={TextAttributes.BOLD} fg={gradient[1]}>
          ◆ muse
        </text>
      )}
      <box height={1} />
      <text fg={theme.textMuted} selectable={false}>
        your personal AI, in the terminal
      </text>
      <box height={2} />
      {working ? (
        <text selectable={false}>
          <span fg={gradientWave(t)}>{spinner(tick)}</span>
          <span fg={theme.textSoft}>{`  ${detail}`}</span>
        </text>
      ) : null}
      {phase === "auth" && !busy ? (
        <box
          border
          borderStyle="rounded"
          borderColor={theme.metaBlue}
          backgroundColor={theme.card}
          padding={1}
          paddingX={3}
          flexDirection="column"
          alignItems="center"
          maxWidth={Math.min(72, width - 4)}
          gap={1}
        >
          <text fg="#FFFFFF" attributes={TextAttributes.BOLD}>
            Let's get you signed in
          </text>
          <text fg={theme.textSoft} wrapMode="word">
            Log in at muse.ai in Chrome, Brave, Arc or Edge, then press L. muse-cli copies that login to this computer; your
            password never leaves the browser.
          </text>
          {detail ? (
            <text fg={theme.textMuted} wrapMode="word">
              {detail}
            </text>
          ) : null}
          <box flexDirection="row" gap={3}>
            <Kbd k="L" label="sign in from browser" />
            <Kbd k="Q" label="quit" />
          </box>
        </box>
      ) : null}
      {phase === "fatal" ? (
        <box
          border
          borderStyle="rounded"
          borderColor={theme.red}
          backgroundColor={theme.card}
          padding={1}
          paddingX={3}
          flexDirection="column"
          alignItems="center"
          maxWidth={Math.min(76, width - 4)}
          gap={1}
        >
          <text fg="#FFFFFF" attributes={TextAttributes.BOLD}>
            Couldn't reach your Muse
          </text>
          <text fg={theme.textSoft} wrapMode="word">
            {detail}
          </text>
          <box flexDirection="row" gap={3}>
            <Kbd k="R" label="retry" />
            <Kbd k="Q" label="quit" />
          </box>
        </box>
      ) : null}
      <box position="absolute" bottom={0} left={0} width="100%" justifyContent="center" flexDirection="row">
        <text fg={theme.textFaint} selectable={false}>
          {`muse-cli ${version}${demo ? " · demo" : ""}`}
        </text>
      </box>
    </box>
  )
}
