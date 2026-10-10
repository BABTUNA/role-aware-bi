import { useEffect, useRef, useState } from "react"
import { Check, ChevronDown } from "lucide-react"
import type { Identity } from "../types"
import { ROLE_STYLE, roleLabel } from "../format"

export function RoleBadge({ role }: { role: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-2 py-0.5 align-middle text-[11px] font-medium capitalize ring-1 ring-inset ${ROLE_STYLE[role] ?? ROLE_STYLE.admin}`}
    >
      {roleLabel(role)}
    </span>
  )
}

export function Avatar({ identity, size = "md" }: { identity: Identity; size?: "sm" | "md" }) {
  const initials = identity.full_name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
  const dims = size === "sm" ? "h-6 w-6 text-[10px]" : "h-8 w-8 text-xs"
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full font-semibold ring-1 ring-inset ${dims} ${ROLE_STYLE[identity.role] ?? ROLE_STYLE.admin}`}
    >
      {initials}
    </span>
  )
}

export function regionLabel(identity: Identity): string {
  return identity.region ?? "all regions"
}

// "Analyst · WEST", role capitalized, region as stored
export function RoleLine({ identity }: { identity: Identity }) {
  return (
    <span className="block text-xs text-slate-500">
      <span className="capitalize">{roleLabel(identity.role)}</span> · {regionLabel(identity)}
    </span>
  )
}

type Props = {
  users: Identity[]
  current: Identity | null
  disabled: boolean
  onPick: (userId: string) => void
}

export default function IdentityPicker({ users, current, disabled, onPick }: Props) {
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

  return (
    <div ref={ref} className="relative min-w-0">
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-9 min-w-0 max-w-full items-center gap-2 rounded-lg border border-slate-200 bg-white py-1 pl-1 pr-2.5 text-sm shadow-sm transition hover:border-slate-300 disabled:cursor-wait disabled:opacity-60"
      >
        {current ? (
          <>
            <Avatar identity={current} size="sm" />
            {/* one line at any width, phones get the first name */}
            <span className="shrink-0 whitespace-nowrap font-medium sm:min-w-0 sm:shrink sm:truncate">
              <span className="sm:hidden">{current.full_name.split(" ")[0]}</span>
              <span className="hidden sm:inline">{current.full_name}</span>
            </span>
            {/* the narrowest phones drop the badge, the menu and the empty state still show the role */}
            <span className="hidden min-[360px]:inline-flex">
              <RoleBadge role={current.role} />
            </span>
            <span className="hidden whitespace-nowrap text-slate-500 lg:inline">{regionLabel(current)}</span>
          </>
        ) : (
          <span className="whitespace-nowrap px-1.5 text-slate-600">Choose an identity</span>
        )}
        <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full z-30 mt-1.5 w-[min(18rem,calc(100vw-2rem))] rounded-xl border border-slate-200 bg-white p-1 shadow-lg"
        >
          <div className="px-2.5 pb-1 pt-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
            Act as
          </div>
          {users.map((u) => (
            <button
              key={u.user_id}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false)
                if (u.user_id !== current?.user_id) onPick(u.user_id)
              }}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition hover:bg-slate-50"
            >
              <Avatar identity={u} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{u.full_name}</span>
                <RoleLine identity={u} />
              </span>
              {current?.user_id === u.user_id && <Check className="h-4 w-4 shrink-0 text-indigo-600" />}
            </button>
          ))}
          <div className="mt-1 border-t border-slate-100 px-2.5 pb-1 pt-2 text-[11px] text-slate-400">
            Switching identity starts a new conversation.
          </div>
        </div>
      )}
    </div>
  )
}
