import { useSyncExternalStore } from "react"
import type {
  Chat,
  ChatFile,
  ConnectionState,
  FeedUnit,
  Goal,
  Idea,
  MailMessage,
  MailThread,
  Message,
  Session,
  Task,
  TaskRun,
} from "./protocol"

export type View = "chat" | "feed" | "goals" | "ideas" | "tasks" | "mail" | "files"

export const VIEWS: { id: View; label: string; icon: string; hint: string }[] = [
  { id: "chat", label: "Chat", icon: "◆", hint: "Talk with your Muse" },
  { id: "feed", label: "Feed", icon: "◈", hint: "Your daily editions" },
  { id: "goals", label: "Goals", icon: "◎", hint: "What you're working toward" },
  { id: "ideas", label: "Ideas", icon: "◇", hint: "Things your Muse can do" },
  { id: "tasks", label: "Tasks", icon: "◷", hint: "Reminders and recurring jobs" },
  { id: "mail", label: "Mail", icon: "@", hint: "Muse Mail inbox" },
  { id: "files", label: "Files", icon: "▤", hint: "Images and files in this chat" },
]

// `off`: the account doesn't have this feature, so retrying won't help.
export type Loadable<T> = { status: "idle" | "loading" | "ready" | "error"; data?: T; error?: string; off?: boolean; at?: number }

export type Toast = { id: number; text: string; level: "info" | "success" | "error"; at: number }

export type Overlay =
  | null
  | { kind: "palette"; query: string }
  | { kind: "help" }
  | { kind: "prompt"; title: string; placeholder: string; initial: string; action: "new_chat" | "rename" }
  | { kind: "confirm"; title: string; body: string; confirm: string; danger?: boolean; run: () => void }
  | { kind: "detail"; title: string; subtitle?: string; body: string; loading?: boolean }

export type BootPhase = "starting" | "connecting" | "auth" | "ready" | "fatal"

export type Pending = { key: string; text: string; at_ms: number; failed?: boolean }

export type State = {
  phase: BootPhase
  phaseDetail: string
  version: string
  demo: boolean
  connection: ConnectionState
  connectionDetail: string
  vmId: string
  identity: any
  chat: Chat
  sessions: Loadable<Session[]>
  messages: Message[]
  historyLoading: boolean
  draft: Message | null
  thinkingSince: number | null
  awaiting: boolean
  pending: Pending[]
  view: View
  focus: "composer" | "sidebar" | "list"
  sidebarOpen: boolean
  sidebarIndex: number
  overlay: Overlay
  toasts: Toast[]
  unread: number
  feed: Loadable<FeedUnit[]>
  goals: Loadable<Goal[]>
  ideas: Loadable<Idea[]>
  tasks: Loadable<{ tasks: Task[]; runs: TaskRun[] }>
  mail: Loadable<{ mailbox: any; threads: MailThread[] }>
  mailThread: Loadable<MailMessage[]> & { id?: string }
  files: Loadable<ChatFile[]>
  selected: Record<View, number>
  loginBusy: boolean
}

export function initialState(): State {
  return {
    phase: "starting",
    phaseDetail: "Starting up",
    version: "",
    demo: false,
    connection: "connecting",
    connectionDetail: "",
    vmId: "",
    identity: null,
    chat: { session_id: null, title: "main chat" },
    sessions: { status: "idle" },
    messages: [],
    historyLoading: false,
    draft: null,
    thinkingSince: null,
    awaiting: false,
    pending: [],
    view: "chat",
    focus: "composer",
    sidebarOpen: true,
    sidebarIndex: 0,
    overlay: null,
    toasts: [],
    unread: 0,
    feed: { status: "idle" },
    goals: { status: "idle" },
    ideas: { status: "idle" },
    tasks: { status: "idle" },
    mail: { status: "idle" },
    mailThread: { status: "idle" },
    files: { status: "idle" },
    selected: { chat: 0, feed: 0, goals: 0, ideas: 0, tasks: 0, mail: 0, files: 0 },
    loginBusy: false,
  }
}

export class Store {
  private state: State
  private listeners = new Set<() => void>()

  constructor(state: State = initialState()) {
    this.state = state
  }

  get = (): State => this.state

  set = (patch: Partial<State> | ((s: State) => Partial<State>)) => {
    const next = typeof patch === "function" ? patch(this.state) : patch
    this.state = { ...this.state, ...next }
    for (const l of this.listeners) l()
  }

  subscribe = (l: () => void) => {
    this.listeners.add(l)
    return () => this.listeners.delete(l)
  }
}

export function useStore<T>(store: Store, select: (s: State) => T): T {
  return useSyncExternalStore(store.subscribe, () => select(store.get()))
}

// Insert or replace by seq, keep seq order.
export function mergeMessages(list: Message[], incoming: Message[]): Message[] {
  if (!incoming.length) return list
  const bySeq = new Map(list.map((m) => [m.seq, m]))
  for (const m of incoming) bySeq.set(m.seq, m)
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq)
}
