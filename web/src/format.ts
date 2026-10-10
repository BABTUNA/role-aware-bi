import type { ChatResponse, Step } from "./types"

export const SUPPRESSED = "suppressed (<3)"

export type Kind =
  // rows came back
  | "answer"
  // the query ran inside the user's scope and matched nothing
  | "empty"
  // the server refused, the reason is the server's, never the model's wording
  | "denied"
  // the query shape couldn't be checked against the disclosure floors
  | "unsupported"
  // the model declined on access grounds before any query ran, the server never saw one
  | "declined_access"
  // the model declined because the data doesn't exist or can't be computed
  | "declined"
  | "clarify"
  | "error"

export type View = { kind: Kind; reason?: string; data?: Step }

function stripPrefix(text: string): string {
  return text.replace(/^(access denied|unsupported):\s*/i, "")
}

// the last query that actually returned data, the one an answer is built on
export function dataStep(steps: Step[]): Step | undefined {
  return [...steps].reverse().find((s) => s.tool === "run_sql" && s.status === "ok")
}

export function classify(r: ChatResponse): View {
  const { outcome } = r
  const steps = r.audit?.steps ?? []
  const data = dataStep(steps)
  if (outcome.status === "error" || !r.audit) {
    return { kind: "error", reason: outcome.error ?? "something went wrong on this question" }
  }

  // a refusal the model wrapped in prose, kept on the outcome by the server
  if (outcome.refusal) {
    const kind = outcome.refusal.startsWith("unsupported") ? "unsupported" : "denied"
    return { kind, reason: stripPrefix(outcome.refusal), data }
  }
  if (outcome.status === "declined") {
    // the model called decline after the server refused a query, show the server's reason
    const refused = [...steps].reverse().find((s) => s.status === "access_denied" || s.status === "unsupported")
    if (refused?.reason) {
      return { kind: refused.status === "unsupported" ? "unsupported" : "denied", reason: refused.reason, data }
    }
    const decline = [...steps].reverse().find((s) => s.tool === "decline")
    const access = decline?.args?.because === "access"
    return { kind: access ? "declined_access" : "declined", reason: outcome.answer }
  }
  if (outcome.status === "clarified") return { kind: "clarify", reason: outcome.answer }
  if (data && (data.row_count ?? 0) === 0) return { kind: "empty", data }
  return { kind: "answer", data }
}

// a result worth a table: more than a single value
export function tableWorthy(step?: Step): boolean {
  if (!step?.rows?.length) return false
  return step.rows.length > 1 || (step.columns?.length ?? 0) > 1
}

export function formatCell(value: unknown, column: string): string {
  if (value === null || value === undefined) return "null"
  if (typeof value === "number") {
    // years and ids read wrong with separators
    if (Number.isInteger(value) && (Math.abs(value) < 10000 || /year|_id$/.test(column))) return String(value)
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  return String(value)
}

export function isNumericColumn(step: Step, index: number): boolean {
  return (step.rows ?? []).every((r) => typeof r[index] === "number" || r[index] === null || r[index] === SUPPRESSED)
}

export const ROLE_STYLE: Record<string, string> = {
  analyst: "bg-sky-50 text-sky-700 ring-sky-200",
  reviewer: "bg-violet-50 text-violet-700 ring-violet-200",
  compliance: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  fair_lending: "bg-amber-50 text-amber-800 ring-amber-200",
  admin: "bg-slate-100 text-slate-700 ring-slate-300",
}

export function roleLabel(role: string): string {
  return role.replace("_", " ")
}
