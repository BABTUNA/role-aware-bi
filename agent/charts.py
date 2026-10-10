"""charts built on the server from an authorized query result, never from rows the model supplies

the model only names a mark and two columns
the data comes from the last successful run_sql in the same turn, after the scope, the floors
and suppression were applied, so a chart can't show anything the audit record doesn't
"""

import re

from .disclosure import SUPPRESSED

MARKS = ("bar", "line", "point")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


class ChartError(Exception):
    """the chart can't be drawn from the last result, returned to the model as an error"""


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def build(mark: str, x_field: str, y_field: str, title: str | None, result: dict | None) -> tuple[dict, list[str]]:
    """a Vega-Lite spec and notes about what was left out

    result is the trace of the last successful run_sql: columns, rows, truncated, redactions
    """
    if result is None:
        raise ChartError("there is no query result in this turn to chart, run the query first")
    if mark not in MARKS:
        raise ChartError(f"mark must be one of {', '.join(MARKS)}")
    columns = result.get("columns") or []
    if x_field not in columns or y_field not in columns:
        raise ChartError(f"x_field and y_field must be columns of the last result: {', '.join(columns)}")
    # a chart of a cut-off list would look complete when it isn't
    if result.get("truncated"):
        raise ChartError("the last result was truncated, aggregate or filter it before charting")

    xi, yi = columns.index(x_field), columns.index(y_field)
    values, left_out = [], 0
    for row in result.get("rows") or []:
        x, y = row[xi], row[yi]
        # suppressed cells stay suppressed, a bar would give their size away
        if x == SUPPRESSED or y == SUPPRESSED or y is None:
            left_out += 1
            continue
        if not _number(y):
            raise ChartError(f"{y_field} has to be numeric to chart")
        values.append({"x": x, "y": y})
    if not values:
        raise ChartError("nothing in the last result can be charted")

    notes = []
    if left_out:
        notes.append(f"{left_out} suppressed or empty value(s) not shown")
    if all(_number(v["x"]) for v in values) and mark != "bar":
        x_type = "quantitative"
    elif all(isinstance(v["x"], str) and _ISO_DATE.match(v["x"]) for v in values):
        x_type = "temporal"
    else:
        x_type = "nominal"

    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {"text": title or f"{y_field} by {x_field}", "subtitle": notes},
        "width": "container",
        # plain keys, column names like sum(t.amount_minor) break vega field paths
        "data": {"values": values},
        "mark": {"type": mark, "tooltip": True},
        "encoding": {
            "x": {"field": "x", "type": x_type, "title": x_field, "sort": None},
            "y": {"field": "y", "type": "quantitative", "title": y_field},
        },
    }
    return spec, notes
