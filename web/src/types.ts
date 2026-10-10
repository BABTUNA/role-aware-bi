// mirrors app/server.py and agent/audit.sanitize, the only shapes the browser ever receives

export type Identity = {
  user_id: string
  full_name: string
  role: string
  region: string | null
}

export type Scope = {
  tables: string[]
  schema_only: string[]
  rows: string | null
  customer_columns: string[]
  withheld_columns: string[]
  aggregate_only: boolean
}

export type SessionInfo = {
  identity: Identity
  scope: Scope
  conversation_id: string
  suggestions: string[]
}

export type StepStatus = "ok" | "access_denied" | "unsupported" | "error" | "bad_arguments"

// a Vega-Lite spec built by the server from an authorized result
export type ChartSpec = Record<string, unknown>

export type Step = {
  tool: string
  status: StepStatus
  sql?: string
  reason?: string | null
  columns?: string[]
  rows?: unknown[][]
  row_count?: number
  truncated?: boolean
  redactions?: string[]
  table?: string
  args?: Record<string, unknown> | null
  chart?: ChartSpec | null
}

export type Outcome = {
  status: "answered" | "declined" | "clarified" | "error" | "no_answer"
  answer: string
  refusal: string | null
  error: string | null
  context_reset: string | null
}

export type AuditView = {
  turn_id: string
  ts: string
  conversation_id: string | null
  identity: Identity
  scope: Scope
  question: string
  steps: Step[]
  outcome: Outcome
  latency_ms: number | null
  tokens: { input: number; output: number } | null
}

export type ChatResponse = {
  conversation_id: string
  answer: string
  outcome: Outcome
  audit: AuditView | null
  chart: ChartSpec | null
}

export type Turn = {
  id: string
  question: string
  status: "pending" | "done" | "failed"
  response?: ChatResponse
  error?: string
}
