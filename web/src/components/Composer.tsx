import { useEffect, useRef, useState } from "react"
import { ArrowUp } from "lucide-react"

type Props = { disabled: boolean; placeholder: string; onSend: (text: string) => void }

export default function Composer({ disabled, placeholder, onSend }: Props) {
  const [text, setText] = useState("")
  const ref = useRef<HTMLTextAreaElement>(null)

  // grow with the text up to a few lines
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [text])

  const send = () => {
    const q = text.trim()
    if (!q || disabled) return
    onSend(q)
    setText("")
  }

  return (
    <div className="border-t border-slate-200 bg-white/80 px-4 py-3 backdrop-blur">
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2 2xl:max-w-4xl rounded-xl border border-slate-200 bg-white p-1.5 shadow-sm focus-within:border-indigo-300 focus-within:ring-2 focus-within:ring-indigo-500/15">
        <textarea
          ref={ref}
          rows={1}
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              send()
            }
          }}
          className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-base outline-none placeholder:text-slate-400 sm:text-[15px]"
        />
        <button
          type="button"
          onClick={send}
          disabled={disabled || !text.trim()}
          aria-label="Send"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white transition hover:bg-indigo-500 disabled:bg-slate-200 disabled:text-slate-400"
        >
          <ArrowUp className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
