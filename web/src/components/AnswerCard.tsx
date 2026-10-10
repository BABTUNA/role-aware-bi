import { Component, Suspense, lazy, type ReactNode } from "react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  AlertTriangle,
  Ban,
  ChevronRight,
  Loader2,
  Lock,
  MessageCircleQuestion,
  SearchX,
  ShieldQuestion,
} from "lucide-react"
import type { Turn } from "../types"
import { classify, tableWorthy } from "../format"
import ResultTable from "./ResultTable"

// vega is most of the bundle, so it loads the first time a chart is shown
const Chart = lazy(() => import("./Chart"))

// a chart that fails to load or render costs that chart, never the whole app
class ChartBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    if (this.state.failed) {
      return (
        <p className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
          The chart couldn't be drawn. The table above has the same numbers.
        </p>
      )
    }
    return this.props.children
  }
}

function Answer({ text }: { text: string }) {
  return (
    <div className="answer text-[15px] text-slate-800">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  )
}

// a banner for outcomes that aren't data, each with its own colour and icon
function Banner({
  tone,
  icon,
  title,
  children,
}: {
  tone: "amber" | "slate" | "indigo" | "rose"
  icon: ReactNode
  title: string
  children?: ReactNode
}) {
  const tones = {
    amber: "bg-amber-50 ring-amber-200 text-amber-900",
    slate: "bg-slate-50 ring-slate-200 text-slate-800",
    indigo: "bg-indigo-50 ring-indigo-200 text-indigo-950",
    rose: "bg-rose-50 ring-rose-200 text-rose-900",
  }
  return (
    <div className={`rounded-lg px-3.5 py-3 ring-1 ring-inset ${tones[tone]}`}>
      <div className="flex items-start gap-2 text-sm font-semibold">
        <span className="mt-0.5 shrink-0">{icon}</span>
        {title}
      </div>
      {children && <div className="mt-1.5 text-sm leading-relaxed opacity-90">{children}</div>}
    </div>
  )
}

// a disclosure floor protects people in small groups, the other refusals are about the role
function deniedTitle(reason?: string): string {
  return /fewer than|population|floor|cells under/.test(reason ?? "")
    ? "Too few people to report safely"
    : "Not available to your role"
}

type Props = { turn: Turn; selected: boolean; scopeRows: string | null; onSelect: () => void }

export default function AnswerCard({ turn, selected, scopeRows, onSelect }: Props) {
  const frame = `group w-full cursor-pointer rounded-xl border px-4 py-3.5 text-left shadow-sm transition ${
    selected ? "border-indigo-300 bg-indigo-50/20 ring-2 ring-indigo-500/25" : "border-slate-200 bg-white hover:border-slate-300"
  }`

  if (turn.status === "pending") {
    return (
      <div className={frame} onClick={onSelect}>
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />
          Working on it. Every query runs under your permissions.
        </div>
      </div>
    )
  }
  if (turn.status === "failed" || !turn.response) {
    return (
      <div className={frame} onClick={onSelect}>
        <Banner tone="rose" icon={<AlertTriangle className="h-4 w-4" />} title="No answer">
          {turn.error}
        </Banner>
      </div>
    )
  }

  const r = turn.response
  const view = classify(r)
  const steps = r.audit?.steps.length ?? 0
  const seconds = r.audit?.latency_ms ? (r.audit.latency_ms / 1000).toFixed(1) : null

  let body: ReactNode
  switch (view.kind) {
    case "denied":
      body = (
        <Banner tone="amber" icon={<Lock className="h-4 w-4" />} title={deniedTitle(view.reason)}>
          <p className="first-letter:uppercase">{view.reason}</p>
          <p className="mt-1 text-xs opacity-75">The server refused this, so none of that data reached the assistant.</p>
        </Banner>
      )
      break
    case "unsupported":
      body = (
        <Banner tone="slate" icon={<ShieldQuestion className="h-4 w-4" />} title="Couldn't check this query">
          <p className="first-letter:uppercase">{view.reason}</p>
          <p className="mt-1 text-xs opacity-75">Try asking for one breakdown at a time.</p>
        </Banner>
      )
      break
    case "declined_access":
      body = (
        <Banner tone="amber" icon={<Lock className="h-4 w-4" />} title="Not available to your role">
          <Answer text={view.reason ?? ""} />
          <p className="mt-1 text-xs opacity-75">The assistant declined before running any query.</p>
        </Banner>
      )
      break
    case "declined":
      body = (
        <Banner tone="slate" icon={<Ban className="h-4 w-4" />} title="Can't answer this">
          <Answer text={view.reason ?? ""} />
        </Banner>
      )
      break
    case "clarify":
      body = (
        <Banner tone="indigo" icon={<MessageCircleQuestion className="h-4 w-4" />} title="Needs a detail from you">
          <Answer text={view.reason ?? ""} />
        </Banner>
      )
      break
    case "error":
      body = (
        <Banner tone="rose" icon={<AlertTriangle className="h-4 w-4" />} title="Something went wrong">
          {view.reason}
        </Banner>
      )
      break
    case "empty":
      body = (
        <>
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-600">
            <SearchX className="h-4 w-4 text-slate-400" />
            No matching rows
            {scopeRows && <span className="font-normal text-slate-400">in {scopeRows}</span>}
          </div>
          {r.answer && <Answer text={r.answer} />}
        </>
      )
      break
    default:
      body = (
        <>
          <Answer text={r.answer} />
          {tableWorthy(view.data) && <ResultTable step={view.data!} />}
          {r.chart && (
            <ChartBoundary>
              <Suspense fallback={<div className="mt-3 h-[260px] animate-pulse rounded-lg bg-slate-100" />}>
                <Chart spec={r.chart} />
              </Suspense>
            </ChartBoundary>
          )}
        </>
      )
  }

  return (
    <div className={frame} onClick={onSelect}>
      {body}
      <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
        <span>
          {steps} step{steps === 1 ? "" : "s"}
          {seconds && ` · ${seconds}s`}
        </span>
        {/* the keyboard way to open this turn in the panel, the card itself is a mouse target */}
        <button
          type="button"
          aria-pressed={selected}
          onClick={(e) => {
            e.stopPropagation()
            onSelect()
          }}
          className={`-my-1 ml-auto inline-flex items-center gap-0.5 rounded px-1 py-1 transition ${selected ? "text-indigo-600" : "group-hover:text-slate-600"}`}
        >
          What the agent did
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}
