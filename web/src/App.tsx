import { useCallback, useEffect, useReducer, useRef, useState } from "react"
import { PanelRight, PanelRightOpen, RotateCcw, ShieldCheck } from "lucide-react"
import { ApiError, api } from "./api"
import { initialState, reducer } from "./state"
import type { Identity, SessionInfo, Turn } from "./types"
import IdentityPicker, { Avatar, RoleLine } from "./components/IdentityPicker"
import ScopeChip from "./components/ScopeChip"
import Thread from "./components/Thread"
import Composer from "./components/Composer"
import ActivityPanel from "./components/ActivityPanel"

// a reload keeps the identity but starts a fresh conversation, so the screen and the server agree
// shared so StrictMode's double effect makes one request, not two racing ones
let restoring: Promise<SessionInfo | null> | null = null
function restore(): Promise<SessionInfo | null> {
  restoring ??= api
    .session()
    .then((s) => (s ? api.newConversation() : null))
    .catch(() => null)
  return restoring
}

// below lg the panel is a slide-over, at lg and up it sits on the right and can collapse to a rail
const narrow = () => window.matchMedia("(max-width: 1023px)").matches

// the collapsed choice is a per-browser convenience, storage can be missing or blocked
const COLLAPSED_KEY = "fraud-bi.panel-collapsed"
function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1"
  } catch {
    return false
  }
}

function Drawer({ turn, onClose }: { turn: Turn | null; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)

  // focus moves into the dialog, Escape closes it, focus goes back where it was
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null
    ref.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose()
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("keydown", onKey)
      before?.focus()
    }
  }, [onClose])

  return (
    <div className="fixed inset-0 z-40 lg:hidden">
      <div className="absolute inset-0 bg-slate-900/20" onClick={onClose} />
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="What the agent did"
        className="absolute inset-y-0 right-0 w-full max-w-md bg-white shadow-xl outline-none"
      >
        <ActivityPanel key={turn?.id ?? "none"} turn={turn} onClose={onClose} />
      </div>
    </div>
  )
}

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const [users, setUsers] = useState<Identity[]>([])
  const [switching, setSwitching] = useState(false)
  const [booted, setBooted] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [problem, setProblem] = useState<string | null>(null)
  // async callbacks read the latest state through this, never a stale closure
  const latest = useRef(state)
  latest.current = state
  const inflight = useRef<AbortController | null>(null)
  // stable, the drawer's focus handling runs once per opening
  const closePanel = useCallback(() => setPanelOpen(false), [])

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0")
    } catch {
      // nothing to do, the panel just won't remember next time
    }
  }, [collapsed])

  useEffect(() => {
    api.users().then(setUsers).catch(() => setProblem("Can't reach the server. Is uvicorn running?"))
    restore().then((s) => {
      if (s) dispatch({ type: "session_started", session: s, notice: null })
      setBooted(true)
    })
  }, [])

  // any answer still on its way belongs to the old identity or conversation
  const dropInflight = () => {
    inflight.current?.abort()
    inflight.current = null
  }

  const started = (s: SessionInfo, notice: string | null) => {
    setPanelOpen(false)
    dispatch({ type: "session_started", session: s, notice })
  }

  const endSession = () => {
    dropInflight()
    setPanelOpen(false)
    dispatch({ type: "session_ended" })
    setProblem("Your session ended, for example because the server restarted. Pick an identity to continue.")
  }

  const switchTo = async (userId: string) => {
    dropInflight()
    setSwitching(true)
    setProblem(null)
    try {
      const s = await api.startSession(userId)
      started(s, `New conversation as ${s.identity.full_name}`)
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Couldn't switch identity")
    } finally {
      setSwitching(false)
    }
  }

  const newConversation = async () => {
    dropInflight()
    setSwitching(true)
    try {
      const s = await api.newConversation()
      started(s, "New conversation")
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) endSession()
      else setProblem(e instanceof Error ? e.message : "Couldn't start a new conversation")
    } finally {
      setSwitching(false)
    }
  }

  const ask = async (question: string) => {
    const s = latest.current
    if (!s.session || s.turns.some((t) => t.status === "pending")) return
    const stamp = { epoch: s.epoch, conversationId: s.session.conversation_id }
    const id = crypto.randomUUID()
    dispatch({ type: "ask", id, question, ...stamp })
    const controller = new AbortController()
    inflight.current = controller
    try {
      const response = await api.chat(stamp.conversationId, question, controller.signal)
      dispatch({ type: "answered", id, response, ...stamp })
    } catch (e) {
      if (controller.signal.aborted) return
      if (e instanceof ApiError && e.status === 401) {
        endSession()
        return
      }
      const error =
        e instanceof ApiError && e.status === 409
          ? "This conversation ended before the answer arrived."
          : e instanceof Error
            ? e.message
            : "Request failed"
      dispatch({ type: "failed", id, error, ...stamp })
    } finally {
      if (inflight.current === controller) inflight.current = null
    }
  }

  const select = (id: string) => {
    dispatch({ type: "select", id })
    // narrow screens open the slide-over, wide screens bring a collapsed panel back
    if (narrow()) setPanelOpen(true)
    else setCollapsed(false)
  }

  const session = state.session
  const busy = state.turns.some((t) => t.status === "pending")
  const selectedTurn = state.turns.find((t) => t.id === state.selected) ?? null
  const iconButton = "rounded-lg p-2 text-slate-600 transition hover:bg-slate-100 disabled:opacity-50"

  return (
    <div className="flex h-full flex-col">
      <header className="z-20 flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3 sm:gap-3 sm:px-4">
        <div className="flex shrink-0 items-center gap-1.5 whitespace-nowrap pr-1 text-sm font-semibold tracking-tight">
          <ShieldCheck className="h-5 w-5 text-indigo-600" />
          <span className="hidden sm:inline">Fraud BI</span>
        </div>
        <IdentityPicker users={users} current={session?.identity ?? null} disabled={switching} onPick={switchTo} />
        {session && <ScopeChip scope={session.scope} />}
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          {session && (
            <button
              type="button"
              onClick={newConversation}
              disabled={switching}
              aria-label="New conversation"
              className={`flex items-center gap-1.5 text-sm ${iconButton} lg:px-2.5`}
            >
              <RotateCcw className="h-4 w-4" />
              <span className="hidden whitespace-nowrap lg:inline">New conversation</span>
            </button>
          )}
          {session && (
            <button
              type="button"
              onClick={() => setPanelOpen((o) => !o)}
              aria-label="What the agent did"
              aria-expanded={panelOpen}
              className={`${iconButton} lg:hidden`}
            >
              <PanelRight className="h-5 w-5" />
            </button>
          )}
        </div>
      </header>

      {problem && (
        <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-800">{problem}</div>
      )}

      <main className="flex min-h-0 flex-1">
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto">
            {session ? (
              <Thread state={state} onSelect={select} onAsk={ask} busy={busy} />
            ) : (
              booted && (
                <div className="mx-auto max-w-md px-4 pt-20">
                  <h1 className="text-xl font-semibold tracking-tight">Who are you acting as?</h1>
                  <p className="mt-1.5 text-sm text-slate-500">
                    Pick an identity. It stands in for signing in, and decides what data the assistant can reach.
                  </p>
                  <div className="mt-6 space-y-2">
                    {users.map((u) => (
                      <button
                        key={u.user_id}
                        type="button"
                        disabled={switching}
                        onClick={() => switchTo(u.user_id)}
                        className="flex w-full items-center gap-3 rounded-xl border border-slate-200 bg-white px-3.5 py-3 text-left shadow-sm transition hover:border-indigo-200 hover:bg-indigo-50/30 disabled:opacity-60"
                      >
                        <Avatar identity={u} />
                        <span className="min-w-0">
                          <span className="block text-sm font-medium">{u.full_name}</span>
                          <RoleLine identity={u} />
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )
            )}
          </div>
          {session && (
            // keyed by conversation, so a half-typed draft never carries over to another identity
            <Composer
              key={session.conversation_id}
              disabled={busy || switching}
              placeholder={`Ask a question as ${session.identity.full_name.split(" ")[0]}`}
              onSend={ask}
            />
          )}
        </section>

        {session && (
          <aside
            className={`hidden shrink-0 overflow-hidden border-l border-slate-200 bg-white transition-[width] duration-200 lg:block ${
              collapsed ? "w-12" : "w-[400px] xl:w-[440px]"
            }`}
          >
            {collapsed ? (
              <button
                type="button"
                onClick={() => setCollapsed(false)}
                aria-label="Show what the agent did"
                aria-expanded={false}
                title="Show what the agent did"
                className="flex h-full w-full flex-col items-center gap-3 pt-4 text-slate-500 transition hover:bg-slate-50 hover:text-slate-700"
              >
                <PanelRightOpen className="h-4 w-4" />
                <span className="whitespace-nowrap text-xs font-medium [writing-mode:vertical-rl]">What the agent did</span>
              </button>
            ) : (
              // keyed by turn, so scroll position and open details reset for each answer
              <ActivityPanel key={selectedTurn?.id ?? "none"} turn={selectedTurn} onCollapse={() => setCollapsed(true)} />
            )}
          </aside>
        )}
      </main>

      {session && panelOpen && <Drawer turn={selectedTurn} onClose={closePanel} />}
    </div>
  )
}
