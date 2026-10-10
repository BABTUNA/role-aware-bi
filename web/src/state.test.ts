import { describe, expect, it } from "vitest"
import { initialState, reducer, type State } from "./state"
import { classify } from "./format"
import type { ChatResponse, SessionInfo, Step } from "./types"

const scope = { tables: [], schema_only: [], rows: null, customer_columns: [], withheld_columns: [], aggregate_only: false }

function session(user_id: string, conversation_id: string): SessionInfo {
  return { identity: { user_id, full_name: user_id, role: "analyst", region: "WEST" }, scope, conversation_id, suggestions: [] }
}

function response(conversation_id: string, steps: Step[] = [], outcome: Partial<ChatResponse["outcome"]> = {}): ChatResponse {
  const o = { status: "answered" as const, answer: "ok", refusal: null, error: null, context_reset: null, ...outcome }
  return {
    conversation_id,
    answer: o.answer,
    outcome: o,
    chart: null,
    audit: {
      turn_id: "t", ts: "", conversation_id, identity: session("u", conversation_id).identity, scope,
      question: "q", steps, outcome: o, latency_ms: 1, tokens: null,
    },
  }
}

function asAna(): State {
  return reducer(initialState, { type: "session_started", session: session("u_ana", "c1"), notice: null })
}

describe("identity switching", () => {
  it("clears every turn and moves to a new epoch", () => {
    let s = asAna()
    s = reducer(s, { type: "ask", id: "q1", question: "how many", epoch: s.epoch, conversationId: "c1" })
    const switched = reducer(s, { type: "session_started", session: session("u_rae", "c2"), notice: "New conversation as Rae" })
    expect(switched.turns).toEqual([])
    expect(switched.selected).toBeNull()
    expect(switched.epoch).toBe(s.epoch + 1)
    expect(switched.session?.identity.user_id).toBe("u_rae")
  })

  it("drops an answer that arrives after the switch", () => {
    let s = asAna()
    const sentAs = { epoch: s.epoch, conversationId: "c1" }
    s = reducer(s, { type: "ask", id: "q1", question: "ana's question", ...sentAs })
    s = reducer(s, { type: "session_started", session: session("u_rae", "c2"), notice: null })
    const after = reducer(s, { type: "answered", id: "q1", response: response("c1"), ...sentAs })
    expect(after).toBe(s)
    expect(after.turns).toEqual([])
  })

  it("drops a late failure after the switch too", () => {
    let s = asAna()
    const sentAs = { epoch: s.epoch, conversationId: "c1" }
    s = reducer(s, { type: "ask", id: "q1", question: "q", ...sentAs })
    s = reducer(s, { type: "session_started", session: session("u_ana", "c9"), notice: null })
    expect(reducer(s, { type: "failed", id: "q1", error: "409", ...sentAs })).toBe(s)
  })

  it("drops an answer for another conversation even in the same epoch", () => {
    let s = asAna()
    s = reducer(s, { type: "ask", id: "q1", question: "q", epoch: s.epoch, conversationId: "c1" })
    const after = reducer(s, { type: "answered", id: "q1", response: response("c_other"), epoch: s.epoch, conversationId: "c1" })
    expect(after.turns[0].status).toBe("pending")
  })

  it("applies an answer for the current conversation", () => {
    let s = asAna()
    s = reducer(s, { type: "ask", id: "q1", question: "q", epoch: s.epoch, conversationId: "c1" })
    s = reducer(s, { type: "answered", id: "q1", response: response("c1"), epoch: s.epoch, conversationId: "c1" })
    expect(s.turns[0].status).toBe("done")
  })

  it("an ended session clears the screen and drops late answers", () => {
    let s = asAna()
    const sentAs = { epoch: s.epoch, conversationId: "c1" }
    s = reducer(s, { type: "ask", id: "q1", question: "q", ...sentAs })
    s = reducer(s, { type: "session_ended" })
    expect(s.session).toBeNull()
    expect(s.turns).toEqual([])
    expect(reducer(s, { type: "answered", id: "q1", response: response("c1"), ...sentAs })).toBe(s)
  })

  it("ignores a question stamped with an old epoch", () => {
    const s = asAna()
    expect(reducer(s, { type: "ask", id: "q1", question: "q", epoch: s.epoch - 1, conversationId: "c1" })).toBe(s)
  })
})

describe("refusals read differently from empty results", () => {
  const ok = (row_count: number): Step => ({ tool: "run_sql", status: "ok", columns: ["n"], rows: [], row_count })
  const denied: Step = { tool: "run_sql", status: "access_denied", reason: "the analyst role can only see region WEST" }

  it("an empty result is empty, not a refusal", () => {
    expect(classify(response("c", [ok(0)])).kind).toBe("empty")
  })

  it("a server refusal is denied, with the server's reason", () => {
    const v = classify(response("c", [denied], { status: "declined", answer: "I can't help with EAST." }))
    expect(v.kind).toBe("denied")
    expect(v.reason).toBe("the analyst role can only see region WEST")
  })

  it("a refusal the model wrapped in prose still shows the server's reason", () => {
    const v = classify(response("c", [denied], { status: "declined", refusal: "access denied: the analyst role can only see region WEST" }))
    expect(v).toMatchObject({ kind: "denied", reason: "the analyst role can only see region WEST" })
  })

  it("a decline with no server refusal is a plain decline", () => {
    expect(classify(response("c", [], { status: "declined", answer: "No credit score column." })).kind).toBe("declined")
  })

  it("a decline the model labelled as access reads as access, not a plain decline", () => {
    const decline: Step = { tool: "decline", status: "ok", args: { reason: "only WEST", because: "access" } }
    expect(classify(response("c", [decline], { status: "declined", answer: "only WEST" })).kind).toBe("declined_access")
  })

  it("an unsupported query shape is its own kind", () => {
    const step: Step = { tool: "run_sql", status: "unsupported", reason: "group by one protected column" }
    expect(classify(response("c", [step], { status: "declined" })).kind).toBe("unsupported")
  })

  it("rows are an answer", () => {
    expect(classify(response("c", [ok(3)])).kind).toBe("answer")
  })
})
