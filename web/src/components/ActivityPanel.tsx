import type { ComponentType, ReactNode } from "react"
import {
  Ban,
  BarChart3,
  Database,
  List,
  Loader2,
  Lock,
  MessageCircleQuestion,
  PanelRightClose,
  ShieldCheck,
  TableProperties,
  X,
} from "lucide-react"
import type { Step, StepStatus, Turn } from "../types"
import { Avatar, RoleBadge, regionLabel } from "./IdentityPicker"
import { ScopeDetails, scopeSummary } from "./ScopeChip"

const TOOLS: Record<string, { icon: ComponentType<{ className?: string }>; label: (s: Step) => string }> = {
  run_sql: { icon: Database, label: () => "Ran a query" },
  describe_table: { icon: TableProperties, label: (s) => `Read the ${s.table ?? ""} schema` },
  list_tables: { icon: List, label: () => "Listed the tables" },
  make_chart: { icon: BarChart3, label: (s) => `Built a ${String(s.args?.mark ?? "")} chart` },
  ask_clarifying_question: { icon: MessageCircleQuestion, label: () => "Asked you to clarify" },
  decline: { icon: Ban, label: () => "Declined" },
}

const STATUS: Record<StepStatus, { text: string; style: string }> = {
  ok: { text: "ok", style: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  access_denied: { text: "access denied", style: "bg-amber-50 text-amber-800 ring-amber-200" },
  unsupported: { text: "not checked", style: "bg-slate-100 text-slate-600 ring-slate-300" },
  error: { text: "error", style: "bg-rose-50 text-rose-700 ring-rose-200" },
  bad_arguments: { text: "error", style: "bg-rose-50 text-rose-700 ring-rose-200" },
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-slate-100 px-5 py-4">
      <h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
      {children}
    </section>
  )
}

// declining or asking ends a turn, a green "ok" there reads like approval
const ENDINGS: Record<string, { text: string; style: string }> = {
  decline: { text: "declined", style: "bg-slate-100 text-slate-600 ring-slate-300" },
  ask_clarifying_question: { text: "asked", style: "bg-indigo-50 text-indigo-700 ring-indigo-200" },
}

function StepItem({ step, last, previous }: { step: Step; last: boolean; previous?: Step }) {
  const tool = TOOLS[step.tool] ?? { icon: List, label: () => step.tool }
  const Icon = tool.icon
  const status = ENDINGS[step.tool] ?? STATUS[step.status] ?? STATUS.error
  const meta: string[] = []
  if (step.tool === "run_sql" && step.status === "ok") {
    meta.push(`${step.row_count ?? 0} row${step.row_count === 1 ? "" : "s"} returned`)
    if (step.truncated) meta.push("truncated")
  }
  if (step.tool === "make_chart" && step.status === "ok") {
    meta.push(`${String(step.args?.y_field)} by ${String(step.args?.x_field)}, from the query above`)
  }
  let text = step.tool === "decline" ? step.args?.reason : step.tool === "ask_clarifying_question" ? step.args?.question : null
  // a decline that only repeats the refusal right above it adds nothing
  if (typeof text === "string" && previous?.reason && text.toLowerCase().includes(previous.reason.toLowerCase().slice(0, 40))) {
    text = null
  }

  return (
    <li className="relative pb-5 pl-9 last:pb-0">
      {!last && <span className="absolute left-[13px] top-7 h-[calc(100%-1.5rem)] w-px bg-slate-200" />}
      <span className="absolute left-0 top-0 flex h-7 w-7 items-center justify-center rounded-full bg-white ring-1 ring-slate-200">
        <Icon className="h-3.5 w-3.5 text-slate-500" />
      </span>
      <div className="flex min-h-7 flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-800">{tool.label(step)}</span>
        <span className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10.5px] font-medium ring-1 ring-inset ${status.style}`}>
          {step.status === "access_denied" && <Lock className="h-2.5 w-2.5" />}
          {status.text}
        </span>
      </div>
      {step.sql && (
        <pre className="mt-1.5 max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-900 px-3 py-2 font-mono text-[11.5px] leading-relaxed text-slate-100">
          {step.sql}
        </pre>
      )}
      {meta.length > 0 && <p className="mt-1.5 text-xs text-slate-500">{meta.join(" · ")}</p>}
      {(step.redactions ?? []).map((r) => (
        <p key={r} className="mt-1 text-xs text-slate-500">
          Redacted: {r}
        </p>
      ))}
      {step.reason && step.status !== "ok" && (
        <p className="mt-1.5 rounded-md bg-amber-50 px-2.5 py-1.5 text-xs leading-relaxed text-amber-900 ring-1 ring-inset ring-amber-200 first-letter:uppercase">
          {step.reason}
        </p>
      )}
      {typeof text === "string" && <p className="mt-1 text-xs leading-relaxed text-slate-500">{text}</p>}
    </li>
  )
}

type Props = {
  turn: Turn | null
  // the slide-over on narrow screens closes
  onClose?: () => void
  // the side panel on wide screens collapses to a rail
  onCollapse?: () => void
}

export default function ActivityPanel({ turn, onClose, onCollapse }: Props) {
  const audit = turn?.response?.audit

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-slate-200 px-5 py-3.5">
        <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-600" />
        <h2 className="whitespace-nowrap text-sm font-semibold">What the agent did</h2>
        {audit && (
          <span title="Id of this turn's audit record" className="ml-auto whitespace-nowrap font-mono text-[11px] text-slate-400">
            turn {audit.turn_id.slice(0, 8)}
          </span>
        )}
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className={`${audit ? "ml-1" : "ml-auto"} rounded-md p-2 text-slate-500 hover:bg-slate-100 lg:hidden`}
          >
            <X className="h-4 w-4" />
          </button>
        )}
        {onCollapse && (
          <button
            type="button"
            onClick={onCollapse}
            aria-label="Collapse panel"
            title="Collapse"
            className={`${audit ? "ml-1" : "ml-auto"} -my-1 hidden rounded-md p-1.5 text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 lg:inline-flex`}
          >
            <PanelRightClose className="h-4 w-4" />
          </button>
        )}
      </header>

      <div className="flex-1 overflow-y-auto">
        {!turn && (
          <p className="px-5 py-6 text-sm leading-relaxed text-slate-500">
            Pick an answer to see who it ran as, the permissions it ran under, every query the assistant ran on your
            behalf, and anything that was refused or redacted.
          </p>
        )}
        {turn?.status === "pending" && (
          <p className="flex items-center gap-2 px-5 py-6 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Running. The record appears when the answer does.
          </p>
        )}
        {turn && turn.status !== "pending" && !audit && (
          <p className="px-5 py-6 text-sm text-slate-500">No audit record for this turn. {turn.error}</p>
        )}

        {audit && (
          <>
            <Section title="Acting as">
              <div className="flex items-center gap-2.5">
                <Avatar identity={audit.identity} />
                <div className="min-w-0">
                  <div className="text-sm font-medium">{audit.identity.full_name}</div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                    <RoleBadge role={audit.identity.role} />
                    {regionLabel(audit.identity)}
                  </div>
                </div>
              </div>
            </Section>

            <Section title="Permissions used">
              <p className="text-sm text-slate-700">{scopeSummary(audit.scope)}</p>
              <details className="group mt-2">
                <summary className="cursor-pointer select-none text-xs text-indigo-600 hover:text-indigo-700">
                  {audit.scope.customer_columns.length} customer columns visible, {audit.scope.withheld_columns.length} withheld
                </summary>
                <div className="mt-3">
                  <ScopeDetails scope={audit.scope} showRows={false} />
                </div>
              </details>
            </Section>

            <Section title={`Steps (${audit.steps.length})`}>
              {audit.steps.length === 0 ? (
                <p className="text-sm text-slate-500">Answered without running anything.</p>
              ) : (
                <ol>
                  {audit.steps.map((s, i) => (
                    <StepItem key={i} step={s} previous={audit.steps[i - 1]} last={i === audit.steps.length - 1} />
                  ))}
                </ol>
              )}
            </Section>

            <Section title="Outcome">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
                <dt className="text-slate-500">Result</dt>
                <dd className="capitalize">{audit.outcome.status.replace("_", " ")}</dd>
                {audit.outcome.refusal && (
                  <>
                    <dt className="text-slate-500">Refused by</dt>
                    <dd>the server</dd>
                  </>
                )}
                {audit.latency_ms != null && (
                  <>
                    <dt className="text-slate-500">Time</dt>
                    <dd>{(audit.latency_ms / 1000).toFixed(1)}s</dd>
                  </>
                )}
                {audit.tokens && (
                  <>
                    <dt className="text-slate-500">Tokens</dt>
                    <dd className="tabular-nums">
                      {audit.tokens.input.toLocaleString()} in · {audit.tokens.output.toLocaleString()} out
                    </dd>
                  </>
                )}
              </dl>
              {audit.outcome.context_reset && (
                <p className="mt-3 rounded-md bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600 ring-1 ring-inset ring-slate-200">
                  {audit.outcome.context_reset}
                </p>
              )}
            </Section>

            <p className="px-5 py-4 text-[11px] leading-relaxed text-slate-400">
              From this turn's audit record. Internal checks, like the queries behind the disclosure floors, stay on
              the server.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
