import { openSync, mkdirSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"
import type { BridgeErrorShape, ErrorKind, Events, Methods } from "./protocol"

export class BridgeError extends Error {
  kind: ErrorKind
  status?: number
  constructor(shape: BridgeErrorShape) {
    super(shape.message)
    this.kind = shape.kind
    this.status = shape.status
  }
}

// One line of JSON in each direction. The transport hides whether the other
// end is the Python bridge process or an in-memory fake.
export interface Transport {
  send(line: string): void
  onLine(cb: (line: string) => void): void
  onClose(cb: (code: number | null) => void): void
  close(): void
}

type Listener<T> = (data: T) => void

export class Bridge {
  private nextId = 1
  private pending = new Map<number, { resolve: (v: any) => void; reject: (e: unknown) => void; timer?: ReturnType<typeof setTimeout> }>()
  private listeners = new Map<string, Set<Listener<any>>>()
  closed = false

  constructor(private transport: Transport) {
    transport.onLine((line) => this.handleLine(line))
    transport.onClose((code) => {
      this.closed = true
      for (const p of this.pending.values()) {
        if (p.timer) clearTimeout(p.timer)
        p.reject(new BridgeError({ kind: "bridge", message: "the muse-cli bridge stopped" }))
      }
      this.pending.clear()
      this.emit("exit", { code, reason: code === 0 ? "closed" : "crashed" })
    })
  }

  request<M extends keyof Methods>(method: M, params?: Methods[M][0], timeoutMs = 120_000): Promise<Methods[M][1]> {
    if (this.closed) return Promise.reject(new BridgeError({ kind: "bridge", message: "the muse-cli bridge stopped" }))
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      const timer =
        timeoutMs > 0
          ? setTimeout(() => {
              this.pending.delete(id)
              reject(new BridgeError({ kind: "timeout", message: `${method} took longer than ${Math.round(timeoutMs / 1000)} s` }))
            }, timeoutMs)
          : undefined
      this.pending.set(id, { resolve, reject, timer })
      this.transport.send(JSON.stringify({ id, method, params: params ?? {} }))
    })
  }

  on<E extends keyof Events>(event: E, cb: Listener<Events[E]>): () => void {
    let set = this.listeners.get(event)
    if (!set) this.listeners.set(event, (set = new Set()))
    set.add(cb)
    return () => set!.delete(cb)
  }

  private emit(event: string, data: unknown) {
    for (const cb of this.listeners.get(event) ?? []) {
      try {
        cb(data)
      } catch {
        // A broken listener must not stop the others or the read loop.
      }
    }
  }

  private handleLine(line: string) {
    let msg: any
    try {
      msg = JSON.parse(line)
    } catch {
      return
    }
    if (msg && typeof msg.id === "number") {
      const p = this.pending.get(msg.id)
      if (!p) return
      this.pending.delete(msg.id)
      if (p.timer) clearTimeout(p.timer)
      if (msg.error) p.reject(new BridgeError(msg.error))
      else p.resolve(msg.result)
    } else if (msg && typeof msg.event === "string") {
      this.emit(msg.event, msg.data)
    }
  }

  close() {
    if (!this.closed) {
      this.transport.send(JSON.stringify({ id: this.nextId++, method: "shutdown", params: {} }))
      this.transport.close()
    }
  }
}

export function logPath(): string {
  const dir = join(process.env.HOME || homedir(), ".config", "muse-cli")
  mkdirSync(dir, { recursive: true })
  return join(dir, "tui.log")
}

export function spawnPythonBridge(demo: boolean): Transport {
  const python = process.env.MUSE_CLI_PYTHON || "python3"
  const args = [python, "-m", "muse_cli.bridge", ...(demo ? ["--demo"] : [])]
  const log = openSync(logPath(), "a")
  const proc = Bun.spawn(args, {
    stdin: "pipe",
    stdout: "pipe",
    stderr: log,
    env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
  })
  const lineCbs: ((l: string) => void)[] = []
  const closeCbs: ((c: number | null) => void)[] = []
  ;(async () => {
    const decoder = new TextDecoder()
    let buf = ""
    try {
      const reader = (proc.stdout as ReadableStream<Uint8Array>).getReader()
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let nl: number
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim()
          buf = buf.slice(nl + 1)
          if (line) for (const cb of lineCbs) cb(line)
        }
      }
    } catch {
      // stdout closed underneath us; the exit handler below reports it.
    }
    const code = await proc.exited
    for (const cb of closeCbs) cb(code)
  })()
  return {
    send(line) {
      try {
        proc.stdin.write(line + "\n")
        proc.stdin.flush()
      } catch {
        // The process is gone; onClose will fire.
      }
    },
    onLine(cb) {
      lineCbs.push(cb)
    },
    onClose(cb) {
      closeCbs.push(cb)
    },
    close() {
      try {
        proc.stdin.end()
      } catch {}
      setTimeout(() => proc.kill(), 1500).unref?.()
    },
  }
}
