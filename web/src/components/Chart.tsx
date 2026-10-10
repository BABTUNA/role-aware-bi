import { useEffect, useRef } from "react"
import embed, { type Result } from "vega-embed"
import type { ChartSpec } from "../types"

// the spec and its data come from the server, built from an authorized query result
// the browser only adds styling

const CONFIG = {
  font: "ui-sans-serif, system-ui, sans-serif",
  view: { stroke: null },
  axis: {
    labelColor: "#64748b",
    titleColor: "#475569",
    gridColor: "#f1f5f9",
    domainColor: "#cbd5e1",
    tickColor: "#cbd5e1",
    labelFontSize: 11,
    titleFontSize: 11,
    titleFontWeight: 500,
    labelLimit: 160,
  },
  title: {
    anchor: "start",
    fontSize: 13,
    fontWeight: 600,
    color: "#0f172a",
    subtitleColor: "#94a3b8",
    subtitleFontSize: 11,
    offset: 10,
  },
  bar: { color: "#6366f1", cornerRadiusEnd: 3 },
  line: { color: "#4f46e5", strokeWidth: 2 },
  point: { color: "#4f46e5", filled: true, size: 60 },
}

export default function Chart({ spec }: { spec: ChartSpec }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let result: Result | undefined
    let cancelled = false
    if (ref.current) {
      // category bars read better on their side, the data is untouched
      // the schema url is dropped, the installed vega-lite renders it either way
      const { $schema: _schema, ...rest } = spec
      const enc = spec.encoding as { x: Record<string, unknown>; y: Record<string, unknown> }
      const mark = spec.mark as { type?: string } | undefined
      const values = ((spec.data as { values?: { y?: unknown }[] })?.values ?? [])
      const horizontal = mark?.type === "bar" && enc?.x?.type === "nominal"
      // counts get whole-number ticks, not 0.5 steps
      const counts = values.every((v) => Number.isInteger(v.y))
      const valueEnc = { ...enc.y, axis: counts ? { tickMinStep: 1, format: "d" } : {} }
      const styled = {
        ...rest,
        ...(horizontal
          ? {
              // the bar labels already name the categories, so no axis title
              encoding: { y: { ...enc.x, title: null, axis: { labelLimit: 220 } }, x: valueEnc },
              height: Math.max(90, values.length * 30),
            }
          : { encoding: { x: enc.x, y: valueEnc }, height: 220 }),
        autosize: { type: "fit-x", contains: "padding" },
        // a long title ends in an ellipsis on a narrow screen instead of being cut off
        config: { ...CONFIG, title: { ...CONFIG.title, limit: Math.max(120, ref.current.clientWidth - 16) } },
      }
      embed(ref.current, styled as any, { actions: false, renderer: "svg" }).then((r) => {
        if (cancelled) r.finalize()
        else result = r
      })
    }
    return () => {
      cancelled = true
      result?.finalize()
    }
  }, [spec])

  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-white px-3 pb-2 pt-3">
      <div ref={ref} className="w-full" />
    </div>
  )
}
