import { useEffect, useRef } from "react"
import { Sparkles } from "lucide-react"
import type { State } from "../state"
import AnswerCard from "./AnswerCard"
import { RoleBadge, regionLabel } from "./IdentityPicker"

type Props = { state: State; onSelect: (id: string) => void; onAsk: (q: string) => void; busy: boolean }

export default function Thread({ state, onSelect, onAsk, busy }: Props) {
  const end = useRef<HTMLDivElement>(null)
  const last = state.turns[state.turns.length - 1]

  // keep the newest turn in view as it arrives and as it resolves, an empty thread stays at the top
  useEffect(() => {
    if (state.turns.length) end.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [state.turns.length, last?.status])

  const session = state.session
  if (!session) return null

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 2xl:max-w-4xl">
      {state.turns.length === 0 && (
        <div className="pt-8">
          {state.notice && (
            <p className="mb-6 text-center text-xs text-slate-400">{state.notice}</p>
          )}
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">
            Ask the fraud warehouse as {session.identity.full_name.split(" ")[0]}
          </h1>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
            Answers are limited to what a <RoleBadge role={session.identity.role} /> in {regionLabel(session.identity)} may
            see. Every query is checked on the server.
          </p>
          {session.suggestions.length > 0 && (
            <div className="mt-6 grid gap-2 sm:grid-cols-2">
              {session.suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  disabled={busy}
                  onClick={() => onAsk(s)}
                  className="flex items-start gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-3 text-left text-sm text-slate-700 shadow-sm transition hover:border-indigo-200 hover:bg-indigo-50/40 disabled:opacity-60"
                >
                  <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-400" />
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {state.turns.map((t) => (
        <div key={t.id} className="space-y-3">
          <div className="flex justify-end">
            <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-slate-900 px-4 py-2.5 text-[15px] text-white">
              {t.question}
            </div>
          </div>
          <AnswerCard
            turn={t}
            selected={state.selected === t.id}
            scopeRows={session.scope.rows}
            onSelect={() => onSelect(t.id)}
          />
        </div>
      ))}
      <div ref={end} />
    </div>
  )
}
