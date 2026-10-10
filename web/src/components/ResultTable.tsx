import type { Step } from "../types"
import { SUPPRESSED, formatCell, isNumericColumn } from "../format"

export default function ResultTable({ step }: { step: Step }) {
  const columns = step.columns ?? []
  const rows = step.rows ?? []
  const numeric = columns.map((_, i) => isNumericColumn(step, i))

  return (
    <div className="mt-3 overflow-hidden rounded-lg border border-slate-200">
      <div className="max-h-80 overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-slate-50 text-xs text-slate-500">
            <tr>
              {columns.map((c, i) => (
                <th
                  key={c + i}
                  className={`whitespace-nowrap border-b border-slate-200 px-3 py-2 font-medium ${numeric[i] ? "text-right" : "text-left"}`}
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row, ri) => (
              <tr key={ri} className="hover:bg-slate-50/70">
                {row.map((v, ci) => (
                  <td
                    key={ci}
                    className={`px-3 py-1.5 ${numeric[ci] ? "text-right tabular-nums" : ""} ${ci === 0 ? "font-medium text-slate-800" : "text-slate-700"}`}
                  >
                    {v === SUPPRESSED ? (
                      <span
                        title="Fewer than 3 people. Suppressed by the fair-lending reporting rule."
                        className="cursor-help rounded bg-slate-100 px-1.5 py-0.5 text-xs italic text-slate-500"
                      >
                        &lt;3
                      </span>
                    ) : v === null ? (
                      <span className="italic text-slate-300">null</span>
                    ) : (
                      formatCell(v, columns[ci])
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-200 bg-slate-50/70 px-3 py-1.5 text-xs text-slate-500">
        <span>
          {rows.length} row{rows.length === 1 ? "" : "s"}
        </span>
        {step.truncated && (
          <span className="text-amber-700">Only the first {rows.length} are shown, more matched</span>
        )}
        {(step.redactions ?? []).map((r) => (
          <span key={r}>{r}</span>
        ))}
      </div>
    </div>
  )
}
