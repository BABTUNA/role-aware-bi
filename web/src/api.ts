import type { ChatResponse, Identity, SessionInfo } from "./types"

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText)
  }
  return res.json() as Promise<T>
}

export const api = {
  users: () => request<Identity[]>("/api/users"),
  // null when nobody has picked an identity yet
  session: () => request<SessionInfo | null>("/api/session"),
  // the session cookie is set by the server, identity never travels with a chat request
  startSession: (user_id: string) =>
    request<SessionInfo>("/api/session", { method: "POST", body: JSON.stringify({ user_id }) }),
  newConversation: () => request<SessionInfo>("/api/conversation", { method: "POST" }),
  chat: (conversation_id: string, question: string, signal: AbortSignal) =>
    request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ conversation_id, question }),
      signal,
    }),
}
