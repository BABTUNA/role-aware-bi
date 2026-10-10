import { useEffect, useRef, useState } from "react"
import { Lock, ShieldCheck } from "lucide-react"
import type { Scope } from "../types"

export function scopeSummary(scope: Scope): string {
  if (scope.rows) return scope.rows
  if (scope.schema_only.length) return "users and schema only, no customer data"
  return "no customer rows"
}

function Chips({ items, tone }: { items: string[]; tone: "on" | "off" }) {
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {items.map((c) => (
        <span
          key={c}
          className={
            tone === "on"
              ? "rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700"
              : "inline-flex items-center gap-0.5 rounded bg-white px-1.5 py-0.5 font-mono text-[11px] text-slate-400 ring-1 ring-inset ring-slate-200"
          }
        >
          {tone === "off" && <Lock className="h-2.5 w-2.5" />}
          {c}
        </span>
      ))}
    </div>
  )
}

// showRows is off where the row summary is already printed just above
export function ScopeDetails({ scope, showRows = true }: { scope: Scope; showRows?: boolean }) {
  return (
    <div className="space-y-3 text-xs">
      {showRows && (
        <div>
          <div className="font-medium text-slate-500">Rows</div>
          <div className="mt-0.5 text-slate-800">{scopeSummary(scope)}</div>
        </div>
      )}
      <div>
        <div className="font-medium text-slate-500">Tables</div>
        <Chips items={scope.tables} tone="on" />
        {scope.schema_only.length > 0 && <Chips items={scope.schema_only} tone="off" />}
      </div>
      {scope.customer_columns.length > 0 && (
        <div>
          <div className="font-medium text-slate-500">Customer columns</div>
          <Chips items={scope.customer_columns} tone="on" />
        </div>
      )}
      {scope.withheld_columns.length > 0 && (
        <div>
          <div className="font-medium text-slate-500">Withheld</div>
          <Chips items={scope.withheld_columns} tone="off" />
        </div>
      )}
      {scope.aggregate_only && (
        <div className="rounded-md bg-amber-50 px-2 py-1.5 text-amber-900 ring-1 ring-amber-200">
          Aggregates only. Small groups are suppressed or refused.
        </div>
      )}
    </div>
  )
}

export default function ScopeChip({ scope }: { scope: Scope }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", close)
    document.addEventListener("keydown", close)
    return () => {
      document.removeEventListener("mousedown", close)
      document.removeEventListener("keydown", close)
    }
  }, [open])

  // narrower screens show the scope in the empty state and in the panel instead
  return (
    <div ref={ref} className="relative hidden lg:block">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 whitespace-nowrap rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600 transition hover:bg-slate-200"
      >
        <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
        {scopeSummary(scope)}
      </button>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-1.5 w-80 rounded-xl border border-slate-200 bg-white p-3.5 shadow-lg">
          <ScopeDetails scope={scope} />
          <p className="mt-3 border-t border-slate-100 pt-2 text-[11px] text-slate-400">
            Enforced by the server on every query, whatever the assistant writes.
          </p>
        </div>
      )}
    </div>
  )
}
