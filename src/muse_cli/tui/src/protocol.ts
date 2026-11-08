export type Chat = { session_id: string | null; title: string }

export type Session = {
  session_id: string | null
  title: string
  is_thread: boolean
  pinned: boolean
  archived: boolean
  updated_at_ms: number
  unread: number
}

export type FileRef = {
  path: string
  kind?: string
  mime?: string
  label?: string
  byte_len?: number
}

export type Message = {
  seq: number
  id: string
  role: "user" | "assistant"
  text: string
  at_ms: number
  final: boolean
  push: boolean
  files: FileRef[]
}

export type ConnectionState = "connecting" | "online" | "offline" | "auth_needed"

export type ErrorKind = "auth" | "not_found" | "gateway" | "timeout" | "bad_request" | "internal" | "bridge"

export type BridgeErrorShape = { kind: ErrorKind; message: string; status?: number }

export type FeedUnit = {
  id: string
  title: string
  date?: string
  edition?: string
  summary?: string
  reaction?: string | null
}

export type Goal = { id: string; title: string; status?: string; subtitle?: string }
export type Idea = { id: string; title: string; section?: string; summary?: string }
export type Task = {
  id: string
  title: string
  mode?: string
  enabled?: boolean
  schedule?: string
  next_run?: string | null
  timezone?: string
}
export type TaskRun = {
  run_id: string
  job_id: string
  status?: string
  trigger?: string
  scheduled?: string | null
  summary?: string | null
  error?: string | null
}
export type MailThread = {
  id: string
  subject?: string
  messages?: number
  participants?: unknown
  last_from?: string
  last_date?: string | null
  preview?: string
}
export type MailMessage = {
  id: string
  thread_id?: string
  direction?: string
  from?: string
  to?: unknown
  subject?: string
  date?: string | null
  text?: string
  attachments?: { index: number; filename?: string; mime?: string; size?: number }[]
}
export type ChatFile = FileRef & { seq?: number; message_id?: string }

export type Events = {
  ready: { version: string; demo: boolean }
  connection: { state: ConnectionState; detail?: string }
  message: { session_id: string | null; message: Message }
  draft: { session_id: string | null; message: Message }
  thinking: { session_id: string | null; since_ms: number }
  idle: { session_id: string | null; replied: boolean }
  unread: unknown
  log: { level: string; text: string }
  exit: { code: number | null; reason: string }
}

export type Methods = {
  connect: [{}, { vm_id?: string; chat: Chat; identity?: any }]
  login: [{}, { ok: boolean; log: string }]
  sessions: [{ archived?: boolean }, { sessions: Session[] }]
  open: [{ session_id: string | null; title: string; limit?: number }, { chat: Chat; messages: Message[] }]
  history: [{ limit?: number; before_seq?: number }, { messages: Message[] }]
  send: [{ text: string }, { sent: boolean; baseline: number }]
  new_chat: [{ title?: string }, { chat: Chat }]
  session_op: [{ op: string; session_id: string; title?: string }, any]
  status: [{}, { vm_id?: string; sessions?: number; unread?: any; identity?: any }]
  feed: [{ limit?: number }, { units: FeedUnit[] }]
  feed_react: [{ unit: string; reaction: string }, any]
  goals: [{}, { goals: Goal[] }]
  goal: [{ id: string }, any]
  ideas: [{}, { ideas: Idea[] }]
  idea: [{ id: string }, any]
  idea_exec: [{ id: string }, any]
  tasks: [{}, { tasks: Task[] }]
  task_runs: [{ job?: string; limit?: number }, { runs: TaskRun[] }]
  email: [{}, { mailbox?: any; threads: MailThread[] }]
  email_thread: [{ id: string }, { messages: MailMessage[] }]
  files: [{ limit?: number }, { files: ChatFile[] }]
  download: [{ path: string; dir?: string }, { rows: { path: string; file?: string; bytes?: number; error?: string; skipped?: string }[] }]
  ping: [{}, { pong: boolean }]
  shutdown: [{}, {}]
}
