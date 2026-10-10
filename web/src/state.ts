import type { ChatResponse, SessionInfo, Turn } from "./types"

export type State = {
  session: SessionInfo | null
  // bumped on every identity switch or new conversation, a reply from an older epoch is dropped
  epoch: number
  turns: Turn[]
  selected: string | null
  // shown above an empty thread after a switch
  notice: string | null
}

// every action that lands after an await carries the epoch and conversation it was sent under
type Stamp = { epoch: number; conversationId: string }

export type Action =
  | { type: "session_started"; session: SessionInfo; notice: string | null }
  | ({ type: "ask"; id: string; question: string } & Stamp)
  | ({ type: "answered"; id: string; response: ChatResponse } & Stamp)
  | ({ type: "failed"; id: string; error: string } & Stamp)
  | { type: "select"; id: string }
  | { type: "session_ended" }

export const initialState: State = { session: null, epoch: 0, turns: [], selected: null, notice: null }

export function isStale(state: State, stamp: Stamp): boolean {
  return stamp.epoch !== state.epoch || stamp.conversationId !== state.session?.conversation_id
}

function update(state: State, id: string, patch: Partial<Turn>): State {
  if (!state.turns.some((t) => t.id === id)) return state
  return { ...state, turns: state.turns.map((t) => (t.id === id ? { ...t, ...patch } : t)) }
}

export function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "session_started":
      // nothing from the previous identity or conversation stays on screen
      return {
        session: action.session,
        epoch: state.epoch + 1,
        turns: [],
        selected: null,
        notice: action.notice,
      }
    case "ask":
      if (isStale(state, action)) return state
      return {
        ...state,
        notice: null,
        turns: [...state.turns, { id: action.id, question: action.question, status: "pending" }],
        selected: action.id,
      }
    case "answered":
      // the server already drops answers for an ended session, this is the second guard
      if (isStale(state, action) || action.response.conversation_id !== action.conversationId) return state
      return update(state, action.id, { status: "done", response: action.response })
    case "failed":
      if (isStale(state, action)) return state
      return update(state, action.id, { status: "failed", error: action.error })
    case "session_ended":
      // the server no longer knows this session, back to picking an identity
      return { ...initialState, epoch: state.epoch + 1 }
    case "select":
      return state.turns.some((t) => t.id === action.id) ? { ...state, selected: action.id } : state
  }
}
